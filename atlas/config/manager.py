"""Atlas configuration manager.

Single source of truth for configuration. Nothing else in Atlas reads YAML.

Loading order (later overrides earlier):
    1. config/defaults.yaml   (required, committed)
    2. config/local.yaml      (optional, gitignored, machine-specific)
    3. Environment variables  (ATLAS_<SECTION>_<KEY>, plus ATLAS_DB_PASSWORD)
    4. .env file at project root is loaded into the environment first

Secrets (e.g. the database password) are never stored in YAML. They come from
environment variables, typically loaded from a gitignored .env file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

PACKAGE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PACKAGE_DIR.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULTS_FILE = CONFIG_DIR / "defaults.yaml"
LOCAL_FILE = CONFIG_DIR / "local.yaml"
ENV_FILE = PROJECT_ROOT / ".env"


class SystemConfig(BaseModel):
    name: str = "Atlas"
    version: str = "0.1.0"
    timezone: str = "UTC"


class PathsConfig(BaseModel):
    data: Path
    documents: Path
    knowledge: Path
    embeddings: Path
    models: Path
    logs: Path
    checkpoints: Path
    state: Path
    cache: Path
    backups: Path

    def ensure_exist(self) -> None:
        """Create all configured directories if they do not exist."""
        for value in self.model_dump().values():
            Path(value).mkdir(parents=True, exist_ok=True)


class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    database: str = "atlas"
    user: str = "atlas"
    password: str = Field(default="", repr=False)
    pool_size: int = 5

    @property
    def conninfo(self) -> str:
        """libpq connection string for psycopg."""
        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password}"
        )


class LLMRole(BaseModel):
    """A role → model binding (D7). Callers ask ``LLMService`` for a *role*
    (chat/planner/researcher/summarizer/code/vision/embed); the service resolves
    it to a concrete (provider, model). Swap models by editing config only."""

    provider: str = "ollama"
    model: str


class LLMConfig(BaseModel):
    provider: str = "ollama"
    host: str = "http://localhost:11434"
    model: str = "qwen3:4b"
    embedding_model: str = "nomic-embed-text"  # pull before knowledge sprint
    temperature: float = 0.0
    timeout: float = 120.0  # seconds; model load on first call can be slow
    keep_alive: str = "5m"  # how long Ollama keeps the model resident
    # Reasoning models (qwen3) ignore think=false and leak chain-of-thought into
    # the answer; think=true makes Ollama separate it into a `thinking` field so
    # callers get clean text. Non-reasoning models fall back automatically.
    think: bool = True
    # R4 (hardware envelope): inference is CPU-only and RAM-heavy, so every LLM
    # call passes through a single "LLM lane" (a semaphore) — running two models
    # at once would thrash RAM. Concurrency for Atlas means parallel I/O, not
    # parallel inference. Raise only when RAM/hardware allows.
    max_concurrency: int = 1
    # Role → model registry (D7). Seeded below so today's single `model` /
    # `embedding_model` keep working: `chat` and `embed` always exist.
    roles: dict[str, LLMRole] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _seed_default_roles(self) -> "LLMConfig":
        # Back-compat: the legacy scalar model becomes the `chat` role and the
        # embedding model becomes the `embed` role, unless explicitly overridden.
        self.roles.setdefault(
            "chat", LLMRole(provider=self.provider, model=self.model)
        )
        self.roles.setdefault(
            "embed", LLMRole(provider=self.provider, model=self.embedding_model)
        )
        return self


class SchedulerConfig(BaseModel):
    workers: int = 2
    checkpoint_interval: int = 60
    max_retries: int = 3
    poll_interval: float = 1.0  # seconds a worker waits when no task is available
    backoff_base: float = 2.0  # retry delay = backoff_base * 2**retry_count seconds


class LoggingConfig(BaseModel):
    level: str = "INFO"
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5


class AuditConfig(BaseModel):
    retention_days: int = 90


class MonitoringConfig(BaseModel):
    health_interval: int = 30  # seconds between periodic health checks


class BackupConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 86400  # daily; 0 = manual only (no scheduled backups)
    retention: int = 7  # keep this many most-recent dumps (0 = keep all)
    pg_dump_path: str = "pg_dump"  # override if not on PATH
    pg_restore_path: str = "pg_restore"  # referenced by the restore script/docs


class KnowledgeConfig(BaseModel):
    chunk_max_words: int = 200  # max words per chunk
    chunk_overlap: int = 40  # words repeated between adjacent chunks
    embed_batch: int = 32  # chunks embedded per provider call


class AgentConfig(BaseModel):
    retrieval_k: int = 5  # chunks retrieved per query
    similarity_floor: float = 0.35  # below this, strict mode answers "I don't know"
    max_context_chars: int = 6000  # cap assembled context sent to the model
    # Grounding mode (ADR-0035). "strict": answer only from retrieved context, else
    # say so. "blended": the model may also use its own knowledge, labelling what is
    # not from the knowledge base. Switchable via config/env without code changes.
    grounding: str = "strict"
    system_preamble: str = "You are Atlas, answering from the provided context."


class ReactConfig(BaseModel):
    max_iterations: int = 6  # hard cap on reason->act->observe cycles
    reflection: bool = True  # run a self-review pass before answering
    max_observation_chars: int = 2000  # truncate each tool result fed back in
    temperature: float = 0.0
    # The JSON protocol carries reasoning in a "thought" field, so the model's
    # separate chain-of-thought ("think") is redundant here and much slower.
    think: bool = False
    system_preamble: str = (
        "You are Atlas, a capable assistant that can use tools to answer questions "
        "and accomplish tasks."
    )


class IngestionConfig(BaseModel):
    enabled: bool = True
    # File types the filesystem source extracts (ADR-0033; expanded S13 Document
    # Reader). PDFs use their embedded text layer; scanned/image-only PDFs need a
    # future OCRService.
    extensions: list[str] = [
        ".txt", ".md", ".pdf", ".html", ".htm",
        ".docx", ".pptx", ".xlsx", ".csv", ".json",
    ]
    scan_interval: int = 300  # seconds between scheduled scans (0 = manual only)


class FilesystemPluginConfig(BaseModel):
    root: str | None = None  # sandbox root; None => paths.documents
    max_bytes: int = 1_048_576  # refuse to read files larger than this (1 MiB)


class WebPluginConfig(BaseModel):
    timeout: float = 15.0
    max_bytes: int = 2_097_152  # cap fetched body (2 MiB)
    user_agent: str = "Atlas/0.1 (+https://localhost)"


class NetConfig(BaseModel):
    """Resilient, polite HTTP layer (D10 / §5c) shared by all web-facing plugins."""

    user_agent: str = "Atlas/0.1 (+https://localhost)"
    timeout: float = 15.0
    max_bytes: int = 2_097_152  # cap fetched body (2 MiB)
    per_domain_delay: float = 1.0  # min seconds between requests to one domain
    max_retries: int = 3  # bounded retries on 429/503/5xx/timeout
    backoff_base: float = 1.0  # delay = backoff_base * 2**attempt (+ jitter), capped
    backoff_cap: float = 30.0
    jitter: float = 0.25  # random 0..jitter seconds added to each backoff
    respect_robots: bool = True  # honour robots.txt allow/deny + crawl-delay
    cache_ttl: float = 300.0  # response cache TTL seconds (0 = disable cache)


class SearchPluginConfig(BaseModel):
    # Ordered providers (D5, provider fallback). First that returns results wins.
    providers: list[str] = Field(default_factory=lambda: ["duckduckgo"])
    max_results: int = 5
    endpoint: str = "https://html.duckduckgo.com/html/"  # DuckDuckGo HTML backend


class DownloaderPluginConfig(BaseModel):
    dir: str | None = None  # downloads dir; None => paths.data/downloads


class ScholarPluginConfig(BaseModel):
    # Ordered academic providers (provider fallback, mirrors D5 web search).
    providers: list[str] = Field(
        default_factory=lambda: ["semantic_scholar", "arxiv"]
    )
    max_results: int = 5
    arxiv_level: int = 3  # arXiv preprints ⇒ L3 (not peer-reviewed)
    semantic_scholar_level: int = 4  # published venues ⇒ L4 peer-reviewed
    semantic_scholar_api_key: str = ""  # optional; keyless works but is rate-limited


class YouTubePluginConfig(BaseModel):
    languages: list[str] = Field(default_factory=lambda: ["en"])


class GitPluginConfig(BaseModel):
    git_binary: str = "git"
    timeout: float = 15.0  # hard wall-clock per git invocation
    max_log: int = 50  # default commits returned by log/file_history


class SQLPluginConfig(BaseModel):
    root: str | None = None  # sandbox root for db files; None => paths.data
    default_source: str | None = None  # default db file if a call omits `source`
    max_rows: int = 1000  # cap rows returned by a query
    timeout: float = 15.0  # soft per-query wall-clock (interrupts the connection)


class OCRPluginConfig(BaseModel):
    root: str | None = None  # sandbox root for images; None => paths.documents
    lang: str = "eng"  # default tesseract language code
    max_bytes: int = 10_485_760  # refuse to OCR images larger than this (10 MiB)


class MailPluginConfig(BaseModel):
    # Read-only IMAP mailbox retrieval (S20d). The password is a *secret*: it is never
    # stored in YAML — it is read from the env var named by `password_env` at build time.
    host: str = ""  # IMAP server host; empty => capability reports "unavailable"
    port: int = 993
    username: str = ""
    password_env: str = "ATLAS_MAIL_PASSWORD"  # env var holding the password
    use_ssl: bool = True
    default_folder: str = "INBOX"
    max_results: int = 25  # cap messages returned by a search
    timeout: float = 20.0  # socket timeout per IMAP connection


class PluginsConfig(BaseModel):
    # Dotted module paths to load; each module exposes build(config) -> Plugin.
    enabled: list[str] = Field(default_factory=list)
    filesystem: FilesystemPluginConfig = FilesystemPluginConfig()
    web: WebPluginConfig = WebPluginConfig()
    search: SearchPluginConfig = SearchPluginConfig()
    downloader: DownloaderPluginConfig = DownloaderPluginConfig()
    scholar: ScholarPluginConfig = ScholarPluginConfig()
    youtube: YouTubePluginConfig = YouTubePluginConfig()
    git: GitPluginConfig = GitPluginConfig()
    sql: SQLPluginConfig = SQLPluginConfig()
    ocr: OCRPluginConfig = OCRPluginConfig()
    mail: MailPluginConfig = MailPluginConfig()


class MemoryConfig(BaseModel):
    recall_k: int = 5  # memories returned per recall
    similarity_floor: float = 0.0  # drop recalls below this cosine similarity
    working_ttl_seconds: int = 3600  # default TTL for working memory (0 = never)
    embed_working: bool = False  # embed working memory too (costlier; usually off)
    prune_interval: int = 3600  # seconds between expired-memory prunes (0 = manual)


class ConversationConfig(BaseModel):
    max_context_turns: int = 10  # recent messages assembled into prompt context
    working_memory_k: int = 5  # relevant working memories recalled per turn
    session_ttl_seconds: int = 0  # 0 = sessions never expire (persist indefinitely)


class JobConfig(BaseModel):
    # Concurrent jobs (R1) are bounded by scheduler.workers: each `advance_job` task
    # runs one step then re-enqueues, so many jobs interleave on the worker pool.
    # Raise scheduler.workers to run more jobs at once (LLM calls still serialise
    # through the single LLM lane, R4).
    max_concurrent: int = 3  # advisory; informs recommended scheduler.workers
    step_max_retries: int = 2  # per-step retries on transient error before `failed`
    retry_delay: float = 2.0  # seconds before a retried step is re-attempted
    # Decomposition (D2c): use the planner-role LLM to break objectives into steps.
    # Off => deterministic single-step plans only (safe default until models are set).
    llm_decompose: bool = False
    max_steps: int = 6  # cap on decomposed steps per job


class CodeConfig(BaseModel):
    # Code understanding (S14, D9/§5b). Pure-CPU parse; caps keep repo scans bounded.
    max_file_bytes: int = 1_048_576  # 1 MiB per-file parse cap
    max_files: int = 5000            # cap on files scanned per repo
    ingest_on_index: bool = False    # index() ingests code-aware chunks into knowledge


class SandboxConfig(BaseModel):
    # Python execution sandbox (S16, D6). Hybrid: subprocess default, docker later.
    backend: str = "subprocess"       # "subprocess" | "docker"
    timeout: float = 30.0             # wall-clock seconds before the run is killed
    cpu_seconds: int = 30             # RLIMIT_CPU (CPU-time seconds)
    memory_mb: int = 1024             # RLIMIT_AS (address-space cap, MiB)
    max_output_bytes: int = 262_144   # truncate stdout/stderr beyond this
    max_code_bytes: int = 262_144     # refuse code larger than this
    network: bool = False             # network disabled by default (soft block)
    dir: str | None = None            # workdir root; None => paths.data/sandbox


class ResearchConfig(BaseModel):
    # Evidence Budget (S15, D8/§5a): the per-job stopping criteria the Verification
    # Engine enforces. Stop on *convergence*, not a fixed paper count.
    min_sources: int = 5
    min_peer_reviewed: int = 3       # L4+ (peer-reviewed papers)
    min_government: int = 1          # L3 (government / national-lab reports)
    convergence: float = 0.90        # numeric agreement threshold to stop
    max_search_iterations: int = 20
    numeric_tolerance: float = 0.15  # relative window for "values agree"


class LearningConfig(BaseModel):
    """Continuous Learning (S18b, D11/§5d). Governance defaults are conservative:
    Atlas **never silently learns** — completed activities are only *proposed*, and
    promotion into a store is an explicit, reviewable, reversible action."""

    enabled: bool = True
    observe_jobs: bool = True  # propose an Experience from each completed job
    auto_apply: bool = False   # if True, apply proposals immediately (still governed)
    default_policy: str = "temporary"  # temporary | project | personal | verified
    default_level: int = 1     # Learning Level L1 (Store); higher levels land in S19
    recall_k: int = 5          # experiences returned per recall


class IntelligenceConfig(BaseModel):
    """Engineering Intelligence (S19, D11/§5d). Higher-order learners over the Code
    store — climb the Learning Levels (L2 Understand → L5 Recommend)."""

    enabled: bool = True
    default_policy: str = "project"      # repos are project-scoped by default (§5d.5)
    generalize_min_repos: int = 2        # need ≥N learned repos before generalizing
    generalize_min_prevalence: float = 0.6  # "you *always* use X" threshold (L4)
    recommend_top_k: int = 5


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"  # bind localhost by default (personal, self-hosted)
    port: int = 8000
    # API keys are secrets: never in YAML. Set ATLAS_API_KEYS (comma-separated) in
    # the environment / .env file (ADR-0013/0046). Empty => the API fails closed
    # (all protected routes return 401) so it is never accidentally open.
    keys: list[str] = Field(default_factory=list, repr=False)
    docs_enabled: bool = True  # serve Swagger/OpenAPI at /docs
    cors_origins: list[str] = Field(default_factory=list)
    metrics_enabled: bool = True  # expose Prometheus /metrics + JSON /v1/metrics

    @field_validator("keys", mode="before")
    @classmethod
    def _split_keys(cls, value: Any) -> Any:
        """Accept a comma-separated string (from env) or a list."""
        if isinstance(value, str):
            return [k.strip() for k in value.split(",") if k.strip()]
        return value


class AtlasConfig(BaseModel):
    system: SystemConfig
    paths: PathsConfig
    database: DatabaseConfig
    llm: LLMConfig
    scheduler: SchedulerConfig
    logging: LoggingConfig
    audit: AuditConfig
    monitoring: MonitoringConfig = MonitoringConfig()
    backup: BackupConfig = BackupConfig()
    knowledge: KnowledgeConfig = KnowledgeConfig()
    agent: AgentConfig = AgentConfig()
    react: ReactConfig = ReactConfig()
    ingestion: IngestionConfig = IngestionConfig()
    memory: MemoryConfig = MemoryConfig()
    conversation: ConversationConfig = ConversationConfig()
    jobs: JobConfig = JobConfig()
    net: NetConfig = NetConfig()
    code: CodeConfig = CodeConfig()
    sandbox: SandboxConfig = SandboxConfig()
    research: ResearchConfig = ResearchConfig()
    learning: LearningConfig = LearningConfig()
    intelligence: IntelligenceConfig = IntelligenceConfig()
    plugins: PluginsConfig = PluginsConfig()
    api: ApiConfig = ApiConfig()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Override known section keys from ATLAS_<SECTION>_<KEY> env vars.

    Pydantic coerces string values to the correct type during validation.
    """
    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        for key in list(values.keys()):
            env_key = f"ATLAS_{section.upper()}_{key.upper()}"
            if env_key in os.environ:
                values[key] = os.environ[env_key]

    # Secret: database password (never in YAML). Accept two aliases.
    password = os.environ.get("ATLAS_DB_PASSWORD") or os.environ.get(
        "ATLAS_DATABASE_PASSWORD"
    )
    if password:
        data.setdefault("database", {})["password"] = password

    # Secret: API keys (never in YAML). Comma-separated in ATLAS_API_KEYS.
    api_keys = os.environ.get("ATLAS_API_KEYS")
    if api_keys is not None:
        data.setdefault("api", {})["keys"] = api_keys

    return data


def load_config() -> AtlasConfig:
    """Load, merge, override, and validate the full Atlas configuration."""
    load_dotenv(ENV_FILE)

    data = _load_yaml(DEFAULTS_FILE)
    data = _deep_merge(data, _load_yaml(LOCAL_FILE))
    data = _apply_env_overrides(data)

    return AtlasConfig.model_validate(data)


_config: AtlasConfig | None = None


def get_config(reload: bool = False) -> AtlasConfig:
    """Return the singleton configuration, loading it on first use."""
    global _config
    if _config is None or reload:
        _config = load_config()
    return _config

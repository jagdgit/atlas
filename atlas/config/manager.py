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
from pydantic import BaseModel, Field, field_validator

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
    # File types the filesystem source extracts (ADR-0033). PDFs use their embedded
    # text layer; scanned/image-only PDFs need a future OCRService.
    extensions: list[str] = [".txt", ".md", ".pdf", ".html", ".htm"]
    scan_interval: int = 300  # seconds between scheduled scans (0 = manual only)


class FilesystemPluginConfig(BaseModel):
    root: str | None = None  # sandbox root; None => paths.documents
    max_bytes: int = 1_048_576  # refuse to read files larger than this (1 MiB)


class WebPluginConfig(BaseModel):
    timeout: float = 15.0
    max_bytes: int = 2_097_152  # cap fetched body (2 MiB)
    user_agent: str = "Atlas/0.1 (+https://localhost)"


class PluginsConfig(BaseModel):
    # Dotted module paths to load; each module exposes build(config) -> Plugin.
    enabled: list[str] = Field(default_factory=list)
    filesystem: FilesystemPluginConfig = FilesystemPluginConfig()
    web: WebPluginConfig = WebPluginConfig()


class MemoryConfig(BaseModel):
    recall_k: int = 5  # memories returned per recall
    similarity_floor: float = 0.0  # drop recalls below this cosine similarity
    working_ttl_seconds: int = 3600  # default TTL for working memory (0 = never)
    embed_working: bool = False  # embed working memory too (costlier; usually off)
    prune_interval: int = 3600  # seconds between expired-memory prunes (0 = manual)


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"  # bind localhost by default (personal, self-hosted)
    port: int = 8000
    # API keys are secrets: never in YAML. Set ATLAS_API_KEYS (comma-separated) in
    # the environment / .env file (ADR-0013/0046). Empty => the API fails closed
    # (all protected routes return 401) so it is never accidentally open.
    keys: list[str] = Field(default_factory=list, repr=False)
    docs_enabled: bool = True  # serve Swagger/OpenAPI at /docs
    cors_origins: list[str] = Field(default_factory=list)

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
    knowledge: KnowledgeConfig = KnowledgeConfig()
    agent: AgentConfig = AgentConfig()
    react: ReactConfig = ReactConfig()
    ingestion: IngestionConfig = IngestionConfig()
    memory: MemoryConfig = MemoryConfig()
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

"""Pattern mining (§5b.1 layer 6): recurring engineering patterns across a repo.

Turns structure + manifests into *reusable engineering patterns* ("always uses the
Repository pattern → service layer → UUIDs → pytest → Docker → structured logging →
Postgres"). This is the seed for the S19 Personal Coding Assistant / Engineering
Experience store: every pattern is **evidence-backed** (never asserted without a
concrete signal) so promotion into long-term knowledge stays governed and reviewable.
"""

from __future__ import annotations

from atlas.code.models import KIND_CLASS, FileParse, Pattern, RepoMap


def mine_patterns(repo_map: RepoMap, parses: list[FileParse]) -> list[Pattern]:
    classes = [s for fp in parses for s in fp.symbols if s.kind == KIND_CLASS]
    class_names = [c.name for c in classes]
    imports = {imp.module.lower().lstrip(".") for fp in parses for imp in fp.imports}
    import_bases = {m.split(".")[0] for m in imports if m}
    deps = {d.lower() for group in repo_map.dependencies.values() for d in group}
    frameworks = set(repo_map.frameworks)
    async_funcs = [
        s for fp in parses for s in fp.symbols if s.signature.startswith("async def")
    ]

    out: list[Pattern] = []

    def suffix_pattern(suffix: str, name: str, desc: str) -> None:
        hits = [c for c in class_names if c.endswith(suffix)]
        if len(hits) >= 2:
            out.append(
                Pattern(
                    name=name,
                    description=desc,
                    confidence=min(0.95, 0.55 + 0.08 * len(hits)),
                    evidence=[f"{len(hits)} classes named *{suffix}: "
                              + ", ".join(sorted(set(hits))[:6])],
                )
            )

    suffix_pattern("Repository", "Repository pattern",
                   "Data access encapsulated behind *Repository classes.")
    suffix_pattern("Repo", "Repository pattern",
                   "Data access encapsulated behind *Repo classes.")
    suffix_pattern("Service", "Service layer",
                   "Business logic organised into *Service classes.")
    suffix_pattern("Registry", "Registry / dependency injection",
                   "Components resolved via *Registry objects.")
    suffix_pattern("Manager", "Manager objects",
                   "Lifecycle/coordination handled by *Manager classes.")

    if "pytest" in deps:
        out.append(Pattern("pytest testing", "Tests written with pytest.", 0.9,
                           ["pytest in dependencies"]))
    elif any("test" in fp.path.lower() for fp in parses):
        out.append(Pattern("pytest testing", "Test files present.", 0.65,
                           ["test_*/tests/ files found"]))

    if "Docker" in frameworks:
        out.append(Pattern("Docker", "Containerised with Docker.", 0.9,
                           ["Dockerfile/compose present"]))

    if {"psycopg", "psycopg2", "asyncpg"} & deps or "PostgreSQL" in frameworks:
        out.append(Pattern("PostgreSQL", "Persists to PostgreSQL.", 0.9,
                           ["postgres driver in dependencies"]))

    if "uuid" in import_bases:
        out.append(Pattern("UUID identifiers", "Uses UUIDs as identifiers.", 0.8,
                           ["`uuid` imported"]))

    if "dataclasses" in import_bases:
        out.append(Pattern("Dataclasses", "Models expressed as dataclasses.", 0.8,
                           ["`dataclasses` imported"]))

    if "structlog" in deps:
        out.append(Pattern("Structured logging", "Structured logs via structlog.", 0.9,
                           ["structlog in dependencies"]))
    elif "logging" in import_bases:
        logging_files = sum(
            1 for fp in parses if any(i.module.lstrip(".") == "logging" for i in fp.imports)
        )
        if logging_files >= 3:
            out.append(Pattern("Logging", "Consistent use of the logging module.", 0.6,
                               [f"`logging` imported in {logging_files} files"]))

    if async_funcs:
        out.append(Pattern("Async I/O", "Uses async/await coroutines.",
                           min(0.9, 0.5 + 0.05 * len(async_funcs)),
                           [f"{len(async_funcs)} async functions"]))

    for fw in frameworks:
        if fw in ("Django", "FastAPI", "Flask", "React", "Next.js", "Vue"):
            out.append(Pattern(f"{fw} framework", f"Built on {fw}.", 0.85,
                               [f"{fw} inferred from dependencies/layout"]))

    out.sort(key=lambda p: p.confidence, reverse=True)
    return out

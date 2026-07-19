"""Repo map (§5b.1 layer 2): directory + manifests → architecture overview.

Walks a repository (skipping vendored/build dirs), reads the common manifests, and
infers dependencies, frameworks, and entry points — the high-level "what is this
project" view the ``code``-role LLM and the S18/S19 learning stages build on.
"""

from __future__ import annotations

import json
import logging
import tomllib
from pathlib import Path

from atlas.code.languages import language_for
from atlas.code.models import FileParse, RepoMap

_logger = logging.getLogger("atlas.code.repomap")

DEFAULT_IGNORES = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        "dist", "build", "target", ".next", ".cache", ".tox", "site-packages",
        ".idea", ".vscode", "coverage", "htmlcov", ".eggs",
    }
)

_MANIFESTS = (
    "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
    "package.json", "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
)

_ENTRY_FILES = frozenset(
    {
        "main.py", "__main__.py", "manage.py", "app.py", "run.py", "wsgi.py",
        "asgi.py", "index.js", "index.ts", "server.js", "main.go", "main.rs",
    }
)

# dependency name -> framework label (best-effort inference)
_FRAMEWORK_BY_DEP = {
    "django": "Django", "flask": "Flask", "fastapi": "FastAPI",
    "sqlalchemy": "SQLAlchemy", "pydantic": "Pydantic", "pytest": "pytest",
    "react": "React", "next": "Next.js", "vue": "Vue", "express": "Express",
    "svelte": "Svelte", "@angular/core": "Angular", "numpy": "NumPy",
    "pandas": "pandas", "torch": "PyTorch", "tensorflow": "TensorFlow",
    "psycopg": "PostgreSQL", "psycopg2": "PostgreSQL", "asyncpg": "PostgreSQL",
    "redis": "Redis", "celery": "Celery", "uvicorn": "uvicorn",
    # JS/TS ecosystem (B.4): frameworks, meta-frameworks, tooling.
    "@nestjs/core": "NestJS", "nestjs": "NestJS", "nuxt": "Nuxt",
    "@remix-run/react": "Remix", "remix": "Remix", "gatsby": "Gatsby",
    "@sveltejs/kit": "SvelteKit", "solid-js": "SolidJS", "preact": "Preact",
    "koa": "Koa", "fastify": "Fastify", "@hapi/hapi": "hapi",
    "typescript": "TypeScript", "vite": "Vite", "webpack": "webpack",
    "jest": "Jest", "vitest": "Vitest", "mocha": "Mocha",
    "tailwindcss": "Tailwind CSS", "electron": "Electron",
    "react-native": "React Native", "prisma": "Prisma", "typeorm": "TypeORM",
    "mongoose": "Mongoose", "graphql": "GraphQL", "axios": "axios",
}


def iter_source_files(
    root: Path,
    *,
    ignores: frozenset[str] = DEFAULT_IGNORES,
    max_files: int = 5000,
) -> list[Path]:
    """Return source files under ``root`` whose extension maps to a language."""
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(out) >= max_files:
            _logger.info("repo scan hit max_files=%d; truncating", max_files)
            break
        if not path.is_file():
            continue
        if any(part in ignores for part in path.parts):
            continue
        if language_for(path.name):
            out.append(path)
    return out


def read_manifests(root: Path) -> dict[str, str]:
    """Read known manifest files that exist at the repo root or one level down."""
    found: dict[str, str] = {}
    for name in _MANIFESTS:
        p = root / name
        if p.is_file():
            try:
                found[name] = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return found


def build_repo_map(root: Path, parses: list[FileParse], manifests: dict[str, str]) -> RepoMap:
    languages: dict[str, int] = {}
    total_loc = 0
    files: list[dict] = []
    for fp in parses:
        languages[fp.lang] = languages.get(fp.lang, 0) + 1
        total_loc += fp.loc
        files.append(
            {"path": fp.path, "lang": fp.lang, "loc": fp.loc, "symbols": len(fp.symbols)}
        )

    dependencies = _dependencies(manifests)
    frameworks = _frameworks(dependencies, manifests, root)
    entry_points = _entry_points(root, manifests)

    return RepoMap(
        root=str(root),
        file_count=len(parses),
        total_loc=total_loc,
        languages=dict(sorted(languages.items(), key=lambda kv: -kv[1])),
        manifests=sorted(manifests),
        dependencies=dependencies,
        frameworks=frameworks,
        entry_points=entry_points,
        files=files,
    )


# --- manifest parsing -----------------------------------------------------
def _dependencies(manifests: dict[str, str]) -> dict[str, list[str]]:
    deps: dict[str, list[str]] = {}
    if "pyproject.toml" in manifests:
        py = _pyproject_deps(manifests["pyproject.toml"])
        if py:
            deps["python"] = py
    if "requirements.txt" in manifests:
        req = _requirements_deps(manifests["requirements.txt"])
        if req:
            deps.setdefault("python", [])
            deps["python"] = sorted(set(deps["python"]) | set(req))
    if "package.json" in manifests:
        js = _package_json_deps(manifests["package.json"])
        if js:
            deps["node"] = js
    if "Cargo.toml" in manifests:
        rust = _toml_section_keys(manifests["Cargo.toml"], "dependencies")
        if rust:
            deps["rust"] = rust
    if "go.mod" in manifests:
        go = _go_mod_deps(manifests["go.mod"])
        if go:
            deps["go"] = go
    return deps


def _pep508_name(spec: str) -> str:
    spec = spec.strip()
    for sep in (" ", "[", ">", "<", "=", "!", "~", ";", "("):
        idx = spec.find(sep)
        if idx != -1:
            spec = spec[:idx]
    return spec.strip()


def _pyproject_deps(text: str) -> list[str]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    names: set[str] = set()
    project = data.get("project", {})
    for spec in project.get("dependencies", []) or []:
        name = _pep508_name(spec)
        if name:
            names.add(name)
    for group in (project.get("optional-dependencies", {}) or {}).values():
        for spec in group or []:
            name = _pep508_name(spec)
            if name:
                names.add(name)
    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    for name in poetry:
        if name.lower() != "python":
            names.add(name)
    return sorted(names)


def _requirements_deps(text: str) -> list[str]:
    names: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        name = _pep508_name(line)
        if name:
            names.add(name)
    return sorted(names)


def _package_json_deps(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        names.update((data.get(key) or {}).keys())
    return sorted(names)


def _toml_section_keys(text: str, section: str) -> list[str]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return []
    return sorted((data.get(section) or {}).keys())


def _go_mod_deps(text: str) -> list[str]:
    names: set[str] = set()
    in_block = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("require ("):
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if in_block and line:
            names.add(line.split()[0])
        elif line.startswith("require "):
            parts = line.split()
            if len(parts) >= 2:
                names.add(parts[1])
    return sorted(names)


# --- inference ------------------------------------------------------------
def _frameworks(
    dependencies: dict[str, list[str]], manifests: dict[str, str], root: Path
) -> list[str]:
    found: set[str] = set()
    all_deps = {d.lower() for deps in dependencies.values() for d in deps}
    for dep, label in _FRAMEWORK_BY_DEP.items():
        if dep.lower() in all_deps:
            found.add(label)
    if "Dockerfile" in manifests or "docker-compose.yml" in manifests or "docker-compose.yaml" in manifests:
        found.add("Docker")
    if (root / "manage.py").is_file():
        found.add("Django")
    return sorted(found)


def _entry_points(root: Path, manifests: dict[str, str]) -> list[str]:
    entries: set[str] = set()
    for name in _ENTRY_FILES:
        if (root / name).is_file():
            entries.add(name)
    if "pyproject.toml" in manifests:
        try:
            data = tomllib.loads(manifests["pyproject.toml"])
            for target in (data.get("project", {}).get("scripts", {}) or {}).values():
                entries.add(str(target))
        except tomllib.TOMLDecodeError:
            pass
    if "package.json" in manifests:
        try:
            data = json.loads(manifests["package.json"])
            if isinstance(data.get("main"), str):
                entries.add(data["main"])
        except json.JSONDecodeError:
            pass
    return sorted(entries)

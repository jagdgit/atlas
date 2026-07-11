"""Code graph (§5b.1 layer 4, Tier B): import graph + cross-file call graph.

Import edges are resolved for every language we can (Python fully, via module-path
mapping incl. relative imports); the **cross-file call graph** is Python-first — calls
are resolved against the repo's symbol table with conservative heuristics (exact
qualname, unique name, or ``self.method`` within the caller's class). Unresolved but
*known* names are counted (never guessed); builtins/externals are ignored, not faked.
"""

from __future__ import annotations

from atlas.code.languages import PYTHON
from atlas.code.models import KIND_CLASS, CodeGraph, FileParse, Symbol


def build_graph(parses: list[FileParse]) -> CodeGraph:
    module_map = _module_map(parses)
    import_edges: list[tuple[str, str]] = []
    external = 0

    for fp in parses:
        for imp in fp.imports:
            target = _resolve_import(imp.module, fp.path, module_map)
            if target:
                import_edges.append((fp.path, target))
            else:
                external += 1

    call_edges, unresolved = _call_graph(parses)
    return CodeGraph(
        import_edges=sorted(set(import_edges)),
        call_edges=sorted(set(call_edges)),
        unresolved_calls=unresolved,
        external_imports=external,
    )


# --- imports --------------------------------------------------------------
def _module_map(parses: list[FileParse]) -> dict[str, str]:
    """Map a dotted module path → in-repo file (Python only)."""
    mapping: dict[str, str] = {}
    for fp in parses:
        if fp.lang != PYTHON:
            continue
        parts = fp.path.replace("\\", "/").split("/")
        if not parts[-1].endswith(".py"):
            continue
        stem = parts[-1][:-3]
        mod_parts = parts[:-1] + ([] if stem == "__init__" else [stem])
        if mod_parts:
            mapping[".".join(mod_parts)] = fp.path
    return mapping


def _resolve_import(module: str, importer: str, module_map: dict[str, str]) -> str | None:
    if not module:
        return None
    if module.startswith("."):
        module = _absolutise_relative(module, importer)
        if module is None:
            return None
    if module in module_map:
        return module_map[module]
    # `from a.b import c` where c is itself a submodule/package.
    parent = module.rsplit(".", 1)[0] if "." in module else module
    return module_map.get(parent)


def _absolutise_relative(module: str, importer: str) -> str | None:
    level = len(module) - len(module.lstrip("."))
    name = module[level:]
    parts = importer.replace("\\", "/").split("/")
    pkg = parts[:-1]  # importer's package dir
    # level 1 = current package; each extra dot climbs one more.
    climb = level - 1
    base = pkg[: len(pkg) - climb] if climb <= len(pkg) else []
    combined = base + ([name] if name else [])
    return ".".join(p for p in combined if p) or None


# --- calls ----------------------------------------------------------------
def _call_graph(parses: list[FileParse]) -> tuple[list[tuple[str, str]], int]:
    by_name: dict[str, list[Symbol]] = {}
    for fp in parses:
        for sym in fp.symbols:
            if sym.kind == KIND_CLASS:
                continue
            by_name.setdefault(sym.name, []).append(sym)

    edges: list[tuple[str, str]] = []
    unresolved = 0
    for fp in parses:
        if fp.lang != PYTHON:
            continue
        for call in fp.calls:
            tokens = call.callee.split(".")
            last = tokens[-1]
            cands = by_name.get(last)
            if not cands:
                continue  # external/builtin — not counted, not guessed
            if tokens[0] in ("self", "cls") and len(tokens) == 2:
                cands = _in_caller_class(cands, fp.path, call.caller)
            target = _pick(cands, fp.path)
            if target is None:
                unresolved += 1
                continue
            caller_id = f"{fp.path}::{call.caller}" if call.caller else f"{fp.path}::<module>"
            edges.append((caller_id, f"{target.file}::{target.qualname}"))
    return edges, unresolved


def _in_caller_class(cands: list[Symbol], file: str, caller: str) -> list[Symbol]:
    cls = caller.split(".")[0] if caller else ""
    scoped = [s for s in cands if s.file == file and (s.parent or "").split(".")[0] == cls]
    return scoped or cands


def _pick(cands: list[Symbol], file: str) -> Symbol | None:
    if len(cands) == 1:
        return cands[0]
    same_file = [s for s in cands if s.file == file]
    if len(same_file) == 1:
        return same_file[0]
    return None  # ambiguous

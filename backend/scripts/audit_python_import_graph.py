#!/usr/bin/env python3
"""Build a static graph of local Python imports under the backend directory.

The audit is intentionally read-only: it parses source with the AST and emits
JSON to stdout. It does not import application modules or execute project code.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any


_EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache"}


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _canonical_local_name(name: str, modules: set[str], packages: set[str], root_name: str) -> str | None:
    if name in modules or name in packages:
        return name
    prefix = f"{root_name}."
    if name.startswith(prefix):
        candidate = name[len(prefix):]
        if candidate in modules or candidate in packages:
            return candidate
    return None


def build_import_graph(root: Path) -> dict[str, Any]:
    root = root.resolve()
    files = sorted(
        path for path in root.rglob("*.py")
        if not any(part in _EXCLUDED_DIRS for part in path.parts)
    )
    module_paths = {_module_name(path, root): path for path in files}
    modules = set(module_paths)
    packages = {
        ".".join(path.relative_to(root).parts[:index])
        for path in root.rglob("*")
        if path.is_dir() and not any(part in _EXCLUDED_DIRS for part in path.parts)
        for index in (len(path.relative_to(root).parts),)
        if index > 0
    }
    graph: dict[str, list[dict[str, Any]]] = {}
    syntax_errors: list[dict[str, Any]] = []
    unresolved_relative: list[dict[str, Any]] = []

    for path in files:
        source_module = _module_name(path, root)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            syntax_errors.append({
                "file": path.relative_to(root).as_posix(),
                "line": getattr(exc, "lineno", None),
                "error": str(exc),
            })
            continue

        edges: list[dict[str, Any]] = []
        for node in ast.walk(tree):
            targets: list[str] = []
            relative = False
            if isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                relative = node.level > 0
                if relative:
                    current_parts = source_module.split(".") if source_module else []
                    if path.name != "__init__.py" and current_parts:
                        current_parts = current_parts[:-1]
                    ascend = node.level - 1
                    if ascend > len(current_parts):
                        unresolved_relative.append({
                            "file": path.relative_to(root).as_posix(),
                            "line": node.lineno,
                            "module": node.module,
                            "level": node.level,
                        })
                        continue
                    base_parts = current_parts[:len(current_parts) - ascend]
                    if node.module:
                        base_parts.extend(node.module.split("."))
                    base = ".".join(part for part in base_parts if part)
                else:
                    base = node.module or ""
                if base:
                    local_base = _canonical_local_name(base, modules, packages, root.name)
                    if local_base:
                        targets.append(local_base)
                    for alias in node.names:
                        candidate = f"{base}.{alias.name}"
                        local_candidate = _canonical_local_name(candidate, modules, packages, root.name)
                        if local_candidate:
                            targets.append(local_candidate)
                elif relative:
                    if base:
                        targets.append(base)
            for target in sorted(set(targets)):
                local_target = _canonical_local_name(target, modules, packages, root.name)
                if local_target:
                    edges.append({
                        "module": local_target,
                        "line": node.lineno,
                    })
                elif relative:
                    unresolved_relative.append({
                        "file": path.relative_to(root).as_posix(),
                        "line": node.lineno,
                        "module": target,
                    })
        graph[source_module] = sorted(edges, key=lambda item: (item["module"], item["line"]))

    return {
        "root": str(root),
        "module_count": len(module_paths),
        "modules": {
            name: {
                "file": path.relative_to(root).as_posix(),
                "imports": graph.get(name, []),
            }
            for name, path in sorted(module_paths.items())
        },
        "syntax_errors": syntax_errors,
        "unresolved_relative_imports": unresolved_relative,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = build_import_graph(args.root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["syntax_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

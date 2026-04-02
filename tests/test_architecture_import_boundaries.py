from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "sena"


def _iter_python_modules(directory: Path) -> list[tuple[Path, str]]:
    modules: list[tuple[Path, str]] = []
    for path in sorted(directory.rglob("*.py")):
        if "/legacy/" in path.as_posix():
            continue
        module = ".".join(("sena", *path.relative_to(SRC_ROOT).with_suffix("").parts))
        modules.append((path, module))
    return modules


def _resolved_imports(module_name: str, tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue

        if node.level == 0:
            base = node.module or ""
        else:
            package_parts = module_name.split(".")[: -node.level]
            base_parts = package_parts + ([node.module] if node.module else [])
            base = ".".join(part for part in base_parts if part)

        if base:
            imports.add(base)
        for alias in node.names:
            if alias.name == "*":
                continue
            imports.add(f"{base}.{alias.name}" if base else alias.name)
    return imports


def _depends_on(imports: set[str], target: str) -> bool:
    return any(name == target or name.startswith(f"{target}.") for name in imports)


def test_dependency_directions_are_enforced() -> None:
    violations: list[str] = []

    for layer in ("policy", "engine", "core"):
        for path, module_name in _iter_python_modules(SRC_ROOT / layer):
            imports = _resolved_imports(
                module_name, ast.parse(path.read_text(encoding="utf-8"))
            )
            if _depends_on(imports, "sena.api"):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)} ({module_name}) must not import from sena.api"
                )

    for path, module_name in _iter_python_modules(SRC_ROOT / "services"):
        imports = _resolved_imports(
            module_name, ast.parse(path.read_text(encoding="utf-8"))
        )
        if _depends_on(imports, "sena.api.routes"):
            violations.append(
                f"{path.relative_to(REPO_ROOT)} ({module_name}) must not import from sena.api.routes"
            )

    for path, module_name in _iter_python_modules(SRC_ROOT / "api" / "routes"):
        imports = _resolved_imports(
            module_name, ast.parse(path.read_text(encoding="utf-8"))
        )
        for forbidden in ("sena.policy", "sena.engine", "sena.core"):
            if _depends_on(imports, forbidden):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)} ({module_name}) must not import from {forbidden}"
                )

    assert not violations, "\n".join(violations)

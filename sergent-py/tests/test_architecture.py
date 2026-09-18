"""Mechanical guardrails for the workspace structure (gold spec sections 2 and 10).

Source checks enforce acyclic package imports, an I/O-free core, async-only
transport, no production dependencies on test implementations, and framework
vocabulary. The copied specification documents have a separate vocabulary check.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# import-name -> workspace directory
PACKAGES = {
    "sergent_py_core": "sergent-py-core",
    "sergent_py_runtime": "sergent-py-runtime",
    "sergent_py_providers": "sergent-py-providers",
    "sergent_py": "sergent-py",
}
WORKSPACE_NAMES = set(PACKAGES)

# which workspace packages each package's source may import
ALLOWED = {
    "sergent_py_core": set(),
    "sergent_py_runtime": {"sergent_py_core"},
    "sergent_py_providers": {"sergent_py_core"},
    "sergent_py": {"sergent_py_core", "sergent_py_runtime", "sergent_py_providers"},
}

CORE_SRC = REPO_ROOT / "sergent-py-core" / "src" / "sergent_py_core"
CORE_MODULES = set(
    """errors.py identifiers.py intent.py mindbuf.py model_calls.py operation.py patch.py plan.py
    proposals/_dialect.py proposals/operation_registry.py proposals/schema.py recipe.py result.py
    run_record.py scene.py scene_actions.py strict_model.py target.py timing.py""".split()
)
RETIRED_CORE_STEMS = frozenset("contracts identity observation records schema_base seams".split())
NOTE_DOMAIN_TERM = re.compile(r"\b(markdown|notes?|paragraphs?|sidecars?)\b", re.IGNORECASE)


def _joined(*pieces: str) -> str:
    return "".join(pieces)


SPECIFICATION_BANNED_TERMS = (
    (_joined("dra", "ft"), re.compile(rf"\b{_joined('dra', 'fts?')}\b", re.IGNORECASE)),
    (_joined("por", "t"), re.compile(rf"\b{_joined('por', 'ts?')}\b", re.IGNORECASE)),
    (
        f"{_joined('rou', 'te')}/{_joined('rou', 'ter')}",
        re.compile(rf"\b{_joined('rou', 't')}(?:es?|ers?)\b", re.IGNORECASE),
    ),
    (_joined("aug", "ment"), re.compile(rf"\b{_joined('aug', 'ment')}\b", re.IGNORECASE)),
    (
        "Run Log/Run Ledger",
        re.compile(r"run(?:\s+|[._/-]*)(?:logs?|logging|ledgers?)(?=\b|_|(?-i:[A-Z]))", re.I),
    ),
)


def _src_root(import_name: str) -> Path:
    return REPO_ROOT / PACKAGES[import_name] / "src" / import_name


def _source_files(import_name: str) -> list[Path]:
    root = _src_root(import_name)
    if not root.exists():
        return []
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _specification_files() -> list[Path]:
    return list((REPO_ROOT / "sergent" / "docs").glob("*.md"))


def _active_learning_doc_files() -> list[Path]:
    relative_paths = """
    README.md docs/KNOWLEDGE.md docs/application-patterns.md sergent/README.md
    sergent-py-core/README.md
    sergent-py-core/docs/KNOWLEDGE.md sergent-py-runtime/README.md
    sergent-py-runtime/docs/KNOWLEDGE.md sergent-py-providers/README.md
    sergent-py-providers/docs/KNOWLEDGE.md sergent-py/README.md sergent-py/docs/KNOWLEDGE.md
    CLAUDE.md sergent-py-core/CLAUDE.md
    sergent-py-runtime/CLAUDE.md sergent-py-providers/CLAUDE.md sergent-py/CLAUDE.md
    """.split()
    paths = [REPO_ROOT / relative for relative in relative_paths]
    paths.extend((REPO_ROOT / "sergent" / "docs").glob("*.md"))
    return sorted({path for path in paths if path.exists()})


def _policy_line(line: str) -> bool:
    lowered = line.lower()
    return any(
        marker in lowered
        for marker in ("banned", "bannded", "cannot be used", "never use", "avoid ")
    )


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _imported_dotted(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            names.add(base)
            separator = "" if base.endswith(".") else "."
            names.update(f"{base}{separator}{alias.name}" for alias in node.names)
    return names


def _workspace_python_files() -> list[Path]:
    return [
        path
        for directory in set(PACKAGES.values())
        for path in (REPO_ROOT / directory).rglob("*.py")
        if not {".tmp", ".venv", "__pycache__"} & set(path.parts)
    ]


def _is_retired_core_import(path: Path, dotted: str, stems: frozenset[str]) -> bool:
    if dotted.startswith("sergent_py_core."):
        return dotted.split(".", 2)[1] in stems
    return (
        CORE_SRC in path.parents
        and dotted.startswith(".")
        and dotted.lstrip(".").split(".")[0] in stems
    )


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _class_def(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} not found")


def _methods(class_def: ast.ClassDef) -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    return {
        node.name: node
        for node in class_def.body
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }


def _argument_names(method: ast.AsyncFunctionDef | ast.FunctionDef) -> list[str]:
    return [arg.arg for arg in method.args.posonlyargs + method.args.args]


def _property_names(class_def: ast.ClassDef) -> set[str]:
    return {
        node.name
        for node in class_def.body
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(decorator, ast.Name) and decorator.id == "property"
            for decorator in node.decorator_list
        )
    }


def _property_setter_names(class_def: ast.ClassDef) -> set[str]:
    setters: set[str] = set()
    for node in class_def.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Attribute)
                and decorator.attr == "setter"
                and isinstance(decorator.value, ast.Name)
            ):
                setters.add(decorator.value.id)
    return setters


def _annotated_fields(class_def: ast.ClassDef) -> set[str]:
    return {
        node.target.id
        for node in class_def.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }


def test_workspace_members_are_the_expected_packages() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    members = set(data["tool"]["uv"]["workspace"]["members"])
    assert members == set(PACKAGES.values())


def test_workspace_sources_reference_declared_members() -> None:
    """Keep workspace source bindings consistent with the declared package graph."""
    root = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    members = root["tool"]["uv"]["workspace"]["members"]
    manifests = {
        member: tomllib.loads((REPO_ROOT / member / "pyproject.toml").read_text(encoding="utf-8"))
        for member in members
    }
    names = {manifest["project"]["name"] for manifest in manifests.values()}
    for member, manifest in {".": root, **manifests}.items():
        sources = manifest.get("tool", {}).get("uv", {}).get("sources", {})
        workspace_sources = {name for name, source in sources.items() if source.get("workspace")}
        assert workspace_sources <= names, f"{member}: missing members {workspace_sources - names}"


def test_import_direction_is_one_directional_and_acyclic() -> None:
    violations: list[str] = []
    for owner in PACKAGES:
        for path in _source_files(owner):
            for root in _imported_roots(path):
                if root in WORKSPACE_NAMES and root != owner and root not in ALLOWED[owner]:
                    rel = path.relative_to(REPO_ROOT)
                    violations.append(f"{rel}: {owner} imports {root}")
    assert violations == [], violations


def test_runtime_never_imports_providers() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _source_files("sergent_py_runtime")
        if "sergent_py_providers" in _imported_roots(path)
    ]
    assert offenders == [], offenders


def test_core_imports_no_io_or_concurrency() -> None:
    forbidden = {"asyncio", "httpx", "threading", "argparse", "dotenv"}
    violations: list[str] = []
    for path in _source_files("sergent_py_core"):
        leaked = forbidden & _imported_roots(path)
        if leaked:
            violations.append(f"{path.relative_to(REPO_ROOT)}: {sorted(leaked)}")
    assert violations == [], violations


def test_no_production_source_imports_a_testing_module() -> None:
    violations: list[str] = []
    for import_name in PACKAGES:
        for path in _source_files(import_name):
            if "testing" in path.relative_to(_src_root(import_name)).parts:
                continue
            for dotted in _imported_dotted(path):
                parts = dotted.split(".")
                if len(parts) >= 2 and parts[0] in WORKSPACE_NAMES and "testing" in parts:
                    violations.append(f"{path.relative_to(REPO_ROOT)}: imports {dotted}")
    assert violations == [], violations


def test_framework_packages_have_no_banned_terms() -> None:
    word_port = re.compile(r"\bports?\b", re.IGNORECASE)
    violations: list[str] = []
    for import_name in WORKSPACE_NAMES:
        for path in _source_files(import_name):
            rel = path.relative_to(REPO_ROOT)
            name = path.name.lower()
            if "augment" in name or "rout" in name or word_port.search(path.stem):
                violations.append(f"{rel}: banned filename")
            text = path.read_text(encoding="utf-8")
            lowered = text.lower()
            if "augment" in lowered:
                violations.append(f"{rel}: contains 'augment'")
            if "rout" in lowered:
                violations.append(f"{rel}: contains 'rout' (route/router)")
            if word_port.search(text):
                violations.append(f"{rel}: contains standalone 'port'")
    assert violations == [], violations


def test_framework_source_has_no_note_domain_terms() -> None:
    violations: list[str] = []
    for import_name in WORKSPACE_NAMES:
        for path in _source_files(import_name):
            rel = path.relative_to(REPO_ROOT)
            if NOTE_DOMAIN_TERM.search(path.stem):
                violations.append(f"{rel}: note-domain filename")
            if NOTE_DOMAIN_TERM.search(path.read_text(encoding="utf-8")):
                violations.append(f"{rel}: contains note-domain vocabulary")
    assert violations == [], violations


def test_specification_files_have_no_domain_banned_terms() -> None:
    violations: list[str] = []
    for path in _specification_files():
        rel = path.relative_to(REPO_ROOT)
        text = path.read_text(encoding="utf-8")
        violations.extend(
            f"{rel}: contains '{label}'"
            for label, pattern in SPECIFICATION_BANNED_TERMS
            if pattern.search(text)
        )
    assert violations == [], violations


def test_active_learning_docs_do_not_teach_retired_framework_terms() -> None:
    retired_terms = (
        (_joined("dra", "ft"), re.compile(rf"\b{_joined('dra', 'fts?')}\b", re.IGNORECASE)),
        (_joined("por", "t"), re.compile(rf"\b{_joined('por', 'ts?')}\b", re.IGNORECASE)),
        (
            f"{_joined('rou', 'te')}/{_joined('rou', 'ter')}",
            re.compile(
                rf"\b{_joined('rou', 'tes?')}\b|\b{_joined('rou', 'ters?')}\b",
                re.IGNORECASE,
            ),
        ),
    )
    violations: list[str] = []
    for path in _active_learning_doc_files():
        rel = path.relative_to(REPO_ROOT)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _policy_line(line):
                continue
            violations.extend(
                f"{rel}:{line_number}: contains '{label}'"
                for label, pattern in retired_terms
                if pattern.search(line)
            )
    assert violations == [], violations


def test_active_learning_docs_preserve_proposal_derivation_boundary() -> None:
    model_proposes_execution_plan = re.compile(
        rf"\bmodel\s+proposes\s+(an?\s+)?{_joined('Execution', 'Plan')}\b",
        re.IGNORECASE,
    )
    violations: list[str] = []
    for path in _active_learning_doc_files():
        rel = path.relative_to(REPO_ROOT)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if model_proposes_execution_plan.search(line):
                violations.append(f"{rel}:{line_number}: model proposal skips derivation")
    assert violations == [], violations


def test_core_interfaces_keep_model_call_async_and_scene_recipe_hooks_sync() -> None:
    model_calls = _tree(CORE_SRC / "model_calls.py")
    model_client = _class_def(model_calls, "ModelClient")
    assert isinstance(_methods(model_client).get("invoke"), ast.AsyncFunctionDef)

    scene_actions = _tree(CORE_SRC / "scene_actions.py")
    scene_async_methods = [
        node.name
        for node in _class_def(scene_actions, "SceneActions").body
        if isinstance(node, ast.AsyncFunctionDef)
    ]
    assert scene_async_methods == []

    recipe = _tree(CORE_SRC / "recipe.py")
    recipe_type = _class_def(recipe, "SergentRecipe")
    recipe_async_methods = [
        node.name for node in recipe_type.body if isinstance(node, ast.AsyncFunctionDef)
    ]
    assert recipe_async_methods == []

    recipe_methods = _methods(recipe_type)
    assert _argument_names(recipe_methods["build_intent_request"]) == (
        "self scene mindbuf target model_name proposal_schema".split()
    )
    assert _argument_names(recipe_methods["build_plan_request"]) == (
        "self scene target intent mindbuf model_name proposal_schema".split()
    )
    assert _argument_names(recipe_methods["compile_patch"]) == ["self", "plan"]


def test_model_request_carries_provider_model_settings() -> None:
    model_calls = _tree(CORE_SRC / "model_calls.py")
    model_request = _class_def(model_calls, "ModelRequest")
    assert _annotated_fields(model_request) == {
        "model_name",
        "messages",
        "model_settings",
        "proposal_schema",
    }

    settings = _tree(_src_root("sergent_py_providers") / "settings.py")
    model_settings = _class_def(settings, "ModelSettings")
    assert _annotated_fields(model_settings) == {
        "thinking_effort",
        "max_output_tokens",
        "timeout_seconds",
    }


def test_operation_trace_declares_only_op_id_field() -> None:
    operation_module = _tree(CORE_SRC / "operation.py")
    operation_trace = _class_def(operation_module, "OperationTrace")
    assert _annotated_fields(operation_trace) == {"op_id"}


def test_core_declares_the_base_operation_vocabulary() -> None:
    operation_module = _tree(CORE_SRC / "operation.py")
    operation = _class_def(operation_module, "Operation")
    class_names = {node.name for node in operation_module.body if isinstance(node, ast.ClassDef)}
    assert "_OperationInternal" not in class_names
    fields = _annotated_fields(operation)
    assert fields == {"_op_id", "call"}
    assert "call_name" not in fields
    assert "internal" not in fields
    assert "op_id" not in fields
    assert "run_id" not in fields
    assert "op_id" in _property_names(operation)
    assert "run_id" not in _property_names(operation)
    assert "op_id" not in _property_setter_names(operation)
    methods = _methods(operation)
    assert {"__setattr__", "__delattr__", "validate_for", "apply"} <= set(methods)
    assert "bind_run" not in methods


def test_core_module_inventory_retires_old_files_and_imports() -> None:
    init_modules = list(CORE_SRC.rglob("__init__.py"))
    assert init_modules and all(path.read_bytes() == b"" for path in init_modules)
    python_files = list(CORE_SRC.rglob("*.py"))
    actual_modules = {
        path.relative_to(CORE_SRC).as_posix() for path in python_files if path.name != "__init__.py"
    }
    assert actual_modules == CORE_MODULES
    assert not RETIRED_CORE_STEMS & {path.stem for path in python_files}
    violations = [
        f"{path.relative_to(REPO_ROOT)}: imports {dotted}"
        for path in _workspace_python_files()
        for dotted in _imported_dotted(path)
        if _is_retired_core_import(path, dotted, RETIRED_CORE_STEMS)
    ]
    assert violations == [], violations


def test_no_sync_httpx_client_in_tree() -> None:
    violations: list[str] = []
    for import_name in PACKAGES:
        for path in _source_files(import_name):
            if "httpx.Client" in path.read_text(encoding="utf-8"):
                violations.append(str(path.relative_to(REPO_ROOT)))
    assert violations == [], violations


def test_no_async_twins_in_framework() -> None:
    violations: list[str] = []
    for import_name in WORKSPACE_NAMES:
        for path in _source_files(import_name):
            if "_async" in path.read_text(encoding="utf-8"):
                violations.append(str(path.relative_to(REPO_ROOT)))
    assert violations == [], violations

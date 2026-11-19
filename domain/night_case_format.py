"""Strict, side-effect-free loader and V1 schema gate for Night City case drafts.

Later semantic validators consume ``ValidationIssue`` and must keep incomplete
checks as ``not_checked`` until their full contract is implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable


CASE_SCHEMA_ID = "night-city-case/1"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs/tasks/night_city/case.schema.json"
MAX_CASE_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 100_000
CHECK_CODES = tuple(f"V{i}" for i in range(1, 12)) + tuple(f"U{i}" for i in range(1, 11))


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    pointer: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    content_hash: str | None
    checks: dict[str, str]
    issues: tuple[ValidationIssue, ...]
    publishable: bool = False
    validator_version: str = "night-city-validator/0.1"
    validation_scope: str = "schema_and_structure"


class CaseFormatError(ValueError):
    def __init__(self, issue: ValidationIssue):
        self.issue = issue
        super().__init__(issue.message)


def _fail(code: str, message: str, pointer: str = "") -> None:
    raise CaseFormatError(ValidationIssue(code, pointer, message))


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_key", f"Повторный ключ JSON: {key}")
        result[key] = value
    return result


def _no_nonfinite(value: str) -> None:
    _fail("nonfinite_number", f"Недопустимое число JSON: {value}")


def _check_tree(value: Any, *, max_depth: int, max_nodes: int) -> None:
    # Iterative traversal keeps this bound independent of Python recursion.
    stack = [(value, 1, "")]
    nodes = 0
    while stack:
        node, depth, pointer = stack.pop()
        nodes += 1
        if nodes > max_nodes:
            _fail("node_limit", f"Превышен лимит узлов: {max_nodes}", pointer)
        if depth > max_depth:
            _fail("depth_limit", f"Превышена глубина JSON: {max_depth}", pointer)
        if isinstance(node, dict):
            stack.extend((child, depth + 1, pointer + "/" + _escape(key)) for key, child in node.items())
        elif isinstance(node, list):
            stack.extend((child, depth + 1, pointer + "/" + str(i)) for i, child in enumerate(node))
        elif isinstance(node, float) and not math.isfinite(node):
            _fail("nonfinite_number", "Число вне конечного диапазона", pointer)


def _escape(part: str) -> str:
    return str(part).replace("~", "~0").replace("/", "~1")


def load_case_bytes(
    raw: bytes, *, max_bytes: int = MAX_CASE_BYTES,
    max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES,
) -> Any:
    """Parse bounded UTF-8 JSON, accepting a single UTF-8 BOM explicitly."""
    if len(raw) > max_bytes:
        _fail("file_too_large", f"JSON превышает {max_bytes} байт")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        _fail("invalid_utf8", f"Ожидается UTF-8: {exc}")
    try:
        document = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_nonfinite)
    except CaseFormatError:
        raise
    except (ValueError, RecursionError) as exc:
        _fail("invalid_json", f"Некорректный JSON: {exc}")
    _check_tree(document, max_depth=max_depth, max_nodes=max_nodes)
    return document


def load_case(
    path: str | Path, *, max_bytes: int = MAX_CASE_BYTES,
    max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES,
) -> Any:
    """Read at most max_bytes + 1 bytes; never write to the source path."""
    try:
        with Path(path).open("rb") as source:
            raw = source.read(max_bytes + 1)
    except OSError as exc:
        _fail("read_error", f"Не удалось прочитать JSON: {exc}")
    return load_case_bytes(raw, max_bytes=max_bytes, max_depth=max_depth, max_nodes=max_nodes)


def canonical_content_hash(document: Any) -> str:
    """SHA-256 of compact UTF-8 JSON with sorted object keys and original array order."""
    canonical = json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _report(hash_value: str | None, issues: list[ValidationIssue], *, v1: str) -> ValidationReport:
    checks = {code: "not_checked" for code in CHECK_CODES}
    checks["V1"] = v1
    return ValidationReport(hash_value, checks, tuple(issues))


def _schema_refs(schema: Any) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    stack = [(schema, "")]
    while stack:
        node, pointer = stack.pop()
        if isinstance(node, dict):
            for key, child in node.items():
                child_pointer = pointer + "/" + _escape(key)
                if key in ("$ref", "$dynamicRef") and (not isinstance(child, str) or not child.startswith("#/")):
                    issues.append(ValidationIssue("schema_external_ref", child_pointer, "Разрешены только локальные ссылки JSON Pointer"))
                if key in ("$id", "$dynamicAnchor", "$anchor") and pointer:
                    issues.append(ValidationIssue("schema_external_ref", child_pointer, "Вложенные идентификаторы и якоря схемы запрещены"))
                stack.append((child, child_pointer))
        elif isinstance(node, list):
            stack.extend((child, pointer + "/" + str(i)) for i, child in enumerate(node))
    return issues


def validate_case(document: Any, *, schema: Any | None = None) -> ValidationReport:
    """Check schema and static structure; semantic V/U checks remain incomplete."""
    try:
        _check_tree(document, max_depth=MAX_DEPTH, max_nodes=MAX_NODES)
        hash_value = canonical_content_hash(document)
    except (CaseFormatError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        issue = exc.issue if isinstance(exc, CaseFormatError) else ValidationIssue("invalid_document", "", str(exc))
        return _report(None, [issue], v1="failed")
    try:
        active_schema = load_case(SCHEMA_PATH) if schema is None else schema
        try:
            _check_tree(active_schema, max_depth=MAX_DEPTH, max_nodes=MAX_NODES)
        except CaseFormatError as exc:
            issue = ValidationIssue("invalid_schema", exc.issue.pointer, exc.issue.message)
            return _report(hash_value, [issue], v1="failed")
        issues = _schema_refs(active_schema)
        if not isinstance(active_schema, dict) or active_schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema" or active_schema.get("$id") != CASE_SCHEMA_ID:
            issues.append(ValidationIssue("unknown_schema", "", "Неизвестная версия схемы валидатора"))
        if issues:
            return _report(hash_value, issues, v1="failed")
        Draft202012Validator.check_schema(active_schema)
        validator = Draft202012Validator(active_schema)
        errors = sorted(validator.iter_errors(document), key=lambda error: (tuple(str(p) for p in error.path), error.message))
        issues = [ValidationIssue("V1.schema", "".join("/" + _escape(part) for part in error.absolute_path), error.message) for error in errors]
        if issues:
            return _report(hash_value, issues, v1="failed")

        # Import after V1 so the format module owns the public report type without
        # creating a module cycle with the structural validator.
        from domain.night_case_validator import validate_structure

        structural_issues = list(validate_structure(document))
        checks = {code: "not_checked" for code in CHECK_CODES}
        checks["V1"] = "failed" if any(item.code.startswith("V1.") for item in structural_issues) else "passed"
        if any(item.code.startswith("V5.") for item in structural_issues):
            checks["V5"] = "failed"
        return ValidationReport(hash_value, checks, tuple(structural_issues))
    except (CaseFormatError, SchemaError, Unresolvable, ValueError, TypeError, RecursionError) as exc:
        issue = exc.issue if isinstance(exc, CaseFormatError) else ValidationIssue("invalid_schema", "", str(exc))
        return _report(hash_value, [issue], v1="failed")


def validate_case_file(path: str | Path) -> ValidationReport:
    try:
        document = load_case(path)
    except CaseFormatError as exc:
        return _report(None, [exc.issue], v1="failed")
    return validate_case(document)

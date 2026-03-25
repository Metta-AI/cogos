"""Schema validation engine for channel message payloads."""

from __future__ import annotations

import re
from typing import Any

_PRIMITIVE_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "bool": bool,
    "list": list,
    "dict": dict,
}

_LIST_PATTERN = re.compile(r"^list\[(.+)]$")


class SchemaValidationError(Exception):
    """Raised when a payload fails schema validation."""


class SchemaValidator:
    """Validates dict payloads against a schema definition.

    Parameters
    ----------
    schema:
        ``{"fields": {"field_name": "type_or_schema", ...}}``
    schema_registry:
        Optional mapping of schema names to schema definitions, used to
        resolve named sub-schema references.
    """

    def __init__(
        self,
        schema: dict[str, Any],
        *,
        schema_registry: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._fields: dict[str, Any] = schema["fields"]
        self._registry: dict[str, dict[str, Any]] = schema_registry if schema_registry is not None else {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, payload: Any) -> None:
        """Validate *payload* against the schema.

        Raises :class:`SchemaValidationError` on any mismatch.
        """
        if not isinstance(payload, dict):
            raise SchemaValidationError("Payload must be a dict")
        self._validate_fields(self._fields, payload, path="")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_fields(
        self, fields: dict[str, Any], data: dict[str, Any], path: str
    ) -> None:
        data_keys = set(data.keys())
        schema_keys = set(fields.keys())

        missing = schema_keys - data_keys
        if missing:
            raise SchemaValidationError(
                f"Missing required field(s) at '{path}': {sorted(missing)}"
            )

        extra = data_keys - schema_keys
        if extra:
            raise SchemaValidationError(
                f"Extra field(s) at '{path}': {sorted(extra)}"
            )

        for name, type_spec in fields.items():
            field_path = f"{path}.{name}" if path else name
            self._validate_value(type_spec, data[name], field_path)

    def _validate_value(self, type_spec: Any, value: Any, path: str) -> None:
        # Inline sub-schema (dict of field defs)
        if isinstance(type_spec, dict):
            if not isinstance(value, dict):
                raise SchemaValidationError(
                    f"Expected dict at '{path}', got {type(value).__name__}"
                )
            self._validate_fields(type_spec, value, path)
            return

        if not isinstance(type_spec, str):
            raise SchemaValidationError(
                f"Invalid type spec at '{path}': {type_spec!r}"
            )

        # Typed list: list[T]
        m = _LIST_PATTERN.match(type_spec)
        if m:
            if not isinstance(value, list):
                raise SchemaValidationError(
                    f"Expected list at '{path}', got {type(value).__name__}"
                )
            inner = m.group(1)
            for i, item in enumerate(value):
                self._validate_value(
                    self._resolve_type(inner, f"{path}[{i}]"),
                    item,
                    f"{path}[{i}]",
                )
            return

        # Plain primitive
        if type_spec in _PRIMITIVE_TYPES:
            self._check_primitive(type_spec, value, path)
            return

        # Named schema reference
        if type_spec in self._registry:
            if not isinstance(value, dict):
                raise SchemaValidationError(
                    f"Expected dict at '{path}', got {type(value).__name__}"
                )
            sub = self._registry[type_spec]
            self._validate_fields(sub["fields"], value, path)
            return

        raise SchemaValidationError(
            f"Unknown type '{type_spec}' at '{path}'"
        )

    def _resolve_type(self, inner: str, path: str) -> Any:
        """Resolve the inner type of ``list[T]``.

        If *inner* is a primitive type name, return it as-is (string).
        If it names a registered schema, return the schema's fields dict
        (so ``_validate_value`` will treat it as an inline sub-schema).
        Otherwise raise.
        """
        if inner in _PRIMITIVE_TYPES:
            return inner
        if inner in self._registry:
            return self._registry[inner]["fields"]
        raise SchemaValidationError(
            f"Unknown element type '{inner}' at '{path}'"
        )

    @staticmethod
    def _check_primitive(type_spec: str, value: Any, path: str) -> None:
        expected = _PRIMITIVE_TYPES[type_spec]

        # bool is a subclass of int in Python, so we need special handling.
        if type_spec == "number" and isinstance(value, bool):
            raise SchemaValidationError(
                f"Expected number at '{path}', got bool"
            )
        if type_spec == "bool" and not isinstance(value, bool):
            raise SchemaValidationError(
                f"Expected bool at '{path}', got {type(value).__name__}"
            )

        if not isinstance(value, expected):
            raise SchemaValidationError(
                f"Expected {type_spec} at '{path}', got {type(value).__name__}"
            )

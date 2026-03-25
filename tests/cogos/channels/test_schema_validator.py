"""Tests for schema validation -- type checking, nested schemas, inline schemas."""
import pytest

from cogos.channels.schema_validator import SchemaValidationError, SchemaValidator


class TestBasicTypes:
    def test_string_valid(self):
        v = SchemaValidator({"fields": {"name": "string"}})
        v.validate({"name": "hello"})

    def test_string_invalid(self):
        v = SchemaValidator({"fields": {"name": "string"}})
        with pytest.raises(SchemaValidationError):
            v.validate({"name": 123})

    def test_number_valid(self):
        v = SchemaValidator({"fields": {"value": "number"}})
        v.validate({"value": 42})
        v.validate({"value": 3.14})

    def test_number_rejects_bool(self):
        v = SchemaValidator({"fields": {"value": "number"}})
        with pytest.raises(SchemaValidationError):
            v.validate({"value": True})

    def test_bool_valid(self):
        v = SchemaValidator({"fields": {"flag": "bool"}})
        v.validate({"flag": True})

    def test_bool_rejects_int(self):
        v = SchemaValidator({"fields": {"flag": "bool"}})
        with pytest.raises(SchemaValidationError):
            v.validate({"flag": 1})

    def test_list_valid(self):
        v = SchemaValidator({"fields": {"items": "list"}})
        v.validate({"items": [1, 2, 3]})

    def test_typed_list_valid(self):
        v = SchemaValidator({"fields": {"tags": "list[string]"}})
        v.validate({"tags": ["a", "b"]})

    def test_typed_list_invalid_element(self):
        v = SchemaValidator({"fields": {"tags": "list[string]"}})
        with pytest.raises(SchemaValidationError):
            v.validate({"tags": ["a", 123]})

    def test_dict_valid(self):
        v = SchemaValidator({"fields": {"meta": "dict"}})
        v.validate({"meta": {"k": "v"}})

    def test_missing_required_field(self):
        v = SchemaValidator({"fields": {"name": "string"}})
        with pytest.raises(SchemaValidationError):
            v.validate({})

    def test_extra_field_rejected(self):
        v = SchemaValidator({"fields": {"name": "string"}})
        with pytest.raises(SchemaValidationError):
            v.validate({"name": "hi", "extra": True})


class TestNestedSchemas:
    def test_inline_sub_schema(self):
        v = SchemaValidator({"fields": {"pos": {"x": "number", "y": "number"}}})
        v.validate({"pos": {"x": 1.0, "y": 2.0}})

    def test_inline_sub_schema_invalid(self):
        v = SchemaValidator({"fields": {"pos": {"x": "number", "y": "number"}}})
        with pytest.raises(SchemaValidationError):
            v.validate({"pos": {"x": "bad"}})

    def test_named_sub_schema(self):
        registry = {
            "position": {"fields": {"x": "number", "y": "number"}},
        }
        v = SchemaValidator(
            {"fields": {"pos": "position"}},
            schema_registry=registry,
        )
        v.validate({"pos": {"x": 1.0, "y": 2.0}})

    def test_list_of_sub_schema(self):
        registry = {
            "position": {"fields": {"x": "number", "y": "number"}},
        }
        v = SchemaValidator(
            {"fields": {"targets": "list[position]"}},
            schema_registry=registry,
        )
        v.validate({"targets": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]})

    def test_list_of_sub_schema_invalid(self):
        registry = {
            "position": {"fields": {"x": "number", "y": "number"}},
        }
        v = SchemaValidator(
            {"fields": {"targets": "list[position]"}},
            schema_registry=registry,
        )
        with pytest.raises(SchemaValidationError):
            v.validate({"targets": [{"x": 1, "y": "bad"}]})

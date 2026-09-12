"""Validate the final response shape independently of expected values."""

from datetime import date
import re


def valid_value(value: object, kind: str) -> bool:
    if kind in ("money", "percent"):
        return isinstance(value, str) and re.fullmatch(r"-?[0-9]+\.[0-9]{2}", value) is not None
    if kind == "boolean":
        return type(value) is bool
    if kind == "date":
        if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            return False
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False
    return kind == "string" and isinstance(value, str)


def schema_errors(output: object, fields: dict[str, str]) -> list[str]:
    if not isinstance(output, dict):
        return ["output must be an object"]
    errors = []
    for section in ("values", "evidence"):
        if not isinstance(output.get(section), dict):
            errors.append(f"{section} must be an object")
        elif set(output[section]) != set(fields):
            errors.append(f"{section} must contain exactly the requested fields")
    if errors:
        return errors
    for field, kind in fields.items():
        if not valid_value(output["values"][field], kind):
            errors.append(f"values.{field}: expected {kind}")
        refs = output["evidence"][field]
        if not isinstance(refs, list) or not refs:
            errors.append(f"evidence.{field}: expected nonempty list")
            continue
        for ref in refs:
            if not (isinstance(ref, dict)
                    and isinstance(ref.get("document_id"), str) and ref["document_id"]
                    and type(ref.get("page")) is int and ref["page"] >= 1
                    and isinstance(ref.get("box"), str) and ref["box"]):
                errors.append(f"evidence.{field}: invalid document/page/box")
    return errors

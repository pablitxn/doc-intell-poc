"""Strict JSON parsing for dataset files and harness transport boundaries."""

import json
import math


def strict_json_loads(text: str | bytes | bytearray) -> object:
    """Reject ambiguous object keys and every representation of non-finite numbers."""
    def object_without_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                # Never include keys or values: they may contain private output.
                raise ValueError("Duplicate JSON object key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("Non-finite JSON number")

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Non-finite JSON number")
        return result

    return json.loads(
        text, object_pairs_hook=object_without_duplicates,
        parse_constant=invalid_constant, parse_float=finite_float,
    )

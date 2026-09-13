"""Apply response validation and deterministic grading outside the harness."""

from pathlib import Path

from ..contracts import Example
from .grading import grade
from .schema import schema_errors

EVALUATOR_VERSION = "tax-mini-v2"
GRADER_PATH = Path(__file__).with_name("grading.py")


def evaluate(output: object, example: Example, execution_status: str = "success") -> dict:
    return score_answer(output, example.expected, example.input.fields, execution_status)


def score_answer(output: object, expected: dict, fields: dict, execution_status: str = "success") -> dict:
    errors = schema_errors(output, fields)
    # Failures stay in the denominator, even if an adapter had partial output.
    prediction = output if execution_status == "success" and isinstance(output, dict) else {}
    report = grade(
        {"answers": {"task": prediction}},
        {"answers": {"task": expected}},
        {"task": fields},
    )
    status = "invalid_response" if execution_status == "success" and errors else execution_status
    return {
        "schema_valid": not errors and execution_status == "success",
        "schema_errors": errors,
        "value_accuracy": report["value_accuracy"],
        "evidence_accuracy": report["evidence_accuracy"],
        "task_pass": status == "success" and report["per_task"][0]["passed"],
        "execution_status": status,
        "fields": report["per_task"][0]["fields"],
    }

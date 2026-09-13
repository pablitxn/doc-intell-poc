"""Export the same local scoring functions as self-contained Phoenix evaluators."""

import ast
import inspect

from .schema import schema_errors, valid_value
from .tax_mini import EVALUATOR_VERSION, GRADER_PATH, score_answer

EVALUATOR_DEFINITIONS = {
    "schema_valid": "Required fields and types, decimal strings, and document/page/box references.",
    "value_accuracy": "Fraction of requested values matching the reference; Decimal comparison; missing differs from zero.",
    "evidence_accuracy": "Fraction of fields whose document/page/box reference set exactly matches the reference.",
    "task_pass": "Successful execution, valid schema and every required value and evidence correct.",
    "execution_status": "Execution outcome; score 1 for success and 0 for errors, invalid responses or unsupported tasks.",
}


def code_definitions() -> list[dict]:
    grader_source = GRADER_PATH.read_text()
    functions = [
        ast.get_source_segment(grader_source, node)
        for node in ast.parse(grader_source).body
        if isinstance(node, ast.FunctionDef) and node.name in ("equal_value", "reference_key", "grade")
    ]
    shared = "from decimal import Decimal, InvalidOperation\nfrom datetime import date\nimport re\n\n"
    shared += "\n\n".join(functions + [
        inspect.getsource(valid_value), inspect.getsource(schema_errors), inspect.getsource(score_answer),
    ])
    definitions = []
    for name, description in EVALUATOR_DEFINITIONS.items():
        score = 'float(value == "success")' if name == "execution_status" else "float(value)"
        label = "value" if name == "execution_status" else "None"
        source = shared + (
            "\n\ndef evaluate(output, reference, metadata):\n"
            "    scores = score_answer(output['answer'], reference, metadata['field_types'], output['execution_status'])\n"
            f"    value = scores[{name!r}]\n"
            f"    return {{'score': {score}, 'label': {label}, 'explanation': {description!r}}}\n"
        )
        definitions.append({
            "name": name,
            "description": f"{description} Policy: {EVALUATOR_VERSION}. Also executed by the local runner.",
            "source_code": source,
            "input_mapping": {
                "literalMapping": {},
                "pathMapping": {"output": "output", "reference": "reference", "metadata": "metadata"},
            },
        })
    return definitions

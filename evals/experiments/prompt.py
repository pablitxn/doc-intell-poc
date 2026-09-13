"""Render the single text input sent to the harness."""

import json
from pathlib import Path

from ..contracts import TaskInput

PROMPT_VERSION = "tax-mini-text-v4"


def build_prompt(task: TaskInput, dataset: Path, *, document_root: Path | None = None) -> str:
    # A container uses the same paths on every host; the dataset identity stays separate.
    document_root = document_root or dataset
    documents = "\n".join(
        f"- {doc['document_id']}: {(document_root / doc['path']).resolve()}"
        for doc in task.documents
    )
    fields = "\n".join(f"- {name}: {kind}" for name, kind in task.fields.items())
    return (
        f"Dataset: {dataset.name}\n"
        f"Dataset inputs: {(document_root / 'inputs').resolve()}\n"
        f"Task ID: {task.task_id}\n"
        f"Case: {task.case_id}\n"
        f"Tax year: {task.tax_year}\n\n"
        f"Documents for this task:\n{documents}\n\n"
        f"{task.instruction}\n\n"
        f"Requested fields and types:\n{fields}\n\n"
        "Use only the listed documents as evidence.\n"
        "Value formats apply to every task: money and percent must be decimal strings "
        "with exactly two fractional digits, no currency/percent symbols and no thousands "
        "separators (for example, \"1234.50\"). Percent values are percentage points "
        "(\"1.20\" means 1.20%). Boolean values must be JSON true/false; dates use YYYY-MM-DD.\n"
        "For evidence.box, use the box identifier printed at the start of the document's "
        "field label, without adding a form name or the word box/line.\n"
        "Return only one JSON object for this task, with all requested fields.\n"
        "Use exactly the top-level keys values and evidence, with exactly the requested field keys in both. "
        "Evidence is evaluated as the exact set of document_id/page/box references requested by the task, "
        "not merely by matching an amount elsewhere in a document.\n"
        "Do not wrap it in answers/TASK_ID or Markdown.\n"
        f"Response format:\n{json.dumps(task.response_format, indent=2)}\n"
    )

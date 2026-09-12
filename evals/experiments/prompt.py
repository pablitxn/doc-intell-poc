"""Render the single text input sent to the harness."""

import json
from pathlib import Path

from ..contracts import TaskInput

PROMPT_VERSION = "tax-mini-text-v1"


def build_prompt(task: TaskInput, dataset: Path) -> str:
    documents = "\n".join(
        f"- {doc['document_id']}: {(dataset / doc['path']).resolve()}"
        for doc in task.documents
    )
    fields = "\n".join(f"- {name}: {kind}" for name, kind in task.fields.items())
    return (
        f"Dataset: {dataset.name}\n"
        f"Dataset inputs: {(dataset / 'inputs').resolve()}\n"
        f"Task ID: {task.task_id}\n"
        f"Case: {task.case_id}\n"
        f"Tax year: {task.tax_year}\n\n"
        f"Documents for this task:\n{documents}\n\n"
        f"{task.instruction}\n\n"
        f"Requested fields and types:\n{fields}\n\n"
        "Use only the listed documents as evidence.\n"
        "Return only one JSON object for this task, with all requested fields.\n"
        "Do not wrap it in answers/TASK_ID or Markdown.\n"
        f"Response format:\n{json.dumps(task.response_format, indent=2)}\n"
    )

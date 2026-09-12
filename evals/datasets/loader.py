"""Load the supplied dataset without putting reference answers in task inputs."""

import hashlib
import json
from pathlib import Path

from ..contracts import Example, TaskInput


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_examples(root: Path) -> tuple[list[Example], str]:
    tasks = read_json(root / "tasks.json")
    manifest = read_json(root / "manifest.json")
    expected = read_json(root / "ground_truth/expected.json")["answers"]
    documents = {}
    for entry in manifest:
        # Explicit allowlist: never forward labels or expected values.
        doc = {key: entry[key] for key in ("document_id", "path", "sha256", "page_count")}
        path = (root / doc["path"]).resolve()
        if not path.is_relative_to((root / "inputs").resolve()):
            raise ValueError("Document must be under inputs/")
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
            raise ValueError(f"Document hash mismatch: {doc['path']}")
        documents[doc["path"]] = doc

    examples = [
        Example(
            input=TaskInput(
                task_id=task["task_id"],
                case_id=tasks["case_id"],
                tax_year=tasks["tax_year"],
                instruction=task["instruction"],
                fields=task["fields"],
                documents=tuple(documents[path] for path in task["documents"]),
                response_format={"values": {"FIELD_KEY": "value"}, "evidence": {
                    "FIELD_KEY": [{"document_id": "DOC-ID", "page": 1, "box": "BOX_ID"}]
                }},
            ),
            expected=expected[task["task_id"]],
            group="reconciliation" if len(task["documents"]) > 1 else "extraction",
        )
        for task in tasks["tasks"]
    ]
    # Includes prompt/schema, reference answers and verified PDF hashes.
    digest = hashlib.sha256()
    for name in ("tasks.json", "manifest.json", "ground_truth/expected.json"):
        digest.update(name.encode() + b"\0" + (root / name).read_bytes() + b"\0")
    return examples, digest.hexdigest()

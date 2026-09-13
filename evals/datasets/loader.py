"""Load the supplied dataset without putting reference answers in task inputs."""

import hashlib
from pathlib import Path, PurePosixPath
import re

from ..contracts import Example, TaskInput
from ..evaluators.schema import schema_errors
from ..json_io import strict_json_loads


FIELD_KINDS = {"money", "percent", "boolean", "date", "string"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not any(
        char in value for char in ("\0", "\r", "\n")
    )


def read_json(path: Path):
    return strict_json_loads(path.read_text(encoding="utf-8"))


def load_examples(root: Path) -> tuple[list[Example], str]:
    if not (root / "tasks.json").is_file() and (root / "coverage.json").is_file():
        raise ValueError(
            "This acquisition kit is not a runnable dataset: prepare a derived dataset with "
            "tasks.json, manifest.json and verified ground_truth before selecting it with --dataset"
        )
    tasks = read_json(root / "tasks.json")
    manifest = read_json(root / "manifest.json")
    reference = read_json(root / "ground_truth/expected.json")
    field_types = read_json(root / "ground_truth/field_types.json")
    _require(isinstance(tasks, dict) and _text(tasks.get("case_id")), "Dataset requires a case_id")
    _require(type(tasks.get("tax_year")) is int and 1 <= tasks["tax_year"] <= 9999,
             "Dataset tax_year must be a calendar year")
    _require(isinstance(tasks.get("tasks"), list) and bool(tasks["tasks"]),
             "Dataset requires nonempty tasks")
    _require(isinstance(reference, dict) and isinstance(reference.get("answers"), dict),
             "Dataset reference must contain an answers object")
    expected = reference["answers"]
    _require(isinstance(field_types, dict), "Dataset field_types must be an object")
    _require(isinstance(manifest, list) and bool(manifest), "Dataset requires a nonempty manifest")
    documents = {}
    document_ids = set()
    resolved_paths = set()
    for entry in manifest:
        _require(isinstance(entry, dict) and all(
            key in entry for key in ("document_id", "path", "sha256", "page_count")
        ), "Manifest entry is missing required document metadata")
        # Explicit allowlist: never forward labels or expected values.
        doc = {key: entry[key] for key in ("document_id", "path", "sha256", "page_count")}
        _require(_text(doc["document_id"]) and doc["document_id"] not in document_ids,
                 "Manifest document IDs must be nonempty and unique")
        _require(_text(doc["path"]), "Manifest document path must be text")
        relative = PurePosixPath(doc["path"])
        _require(not relative.is_absolute() and bool(relative.parts) and relative.parts[0] == "inputs"
                 and len(relative.parts) > 1 and ".." not in relative.parts
                 and relative.as_posix() == doc["path"] and "\\" not in doc["path"],
                 "Document must use a canonical relative path under inputs/")
        _require(type(doc["page_count"]) is int and doc["page_count"] > 0,
                 "Manifest page_count must be a positive integer")
        _require(isinstance(doc["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", doc["sha256"]) is not None,
                 "Manifest document hash must be SHA256")
        path = (root / doc["path"]).resolve()
        if not path.is_relative_to((root / "inputs").resolve()):
            raise ValueError("Document must be under inputs/")
        _require(doc["path"] not in documents and path not in resolved_paths,
                 "Manifest document paths must be unique")
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
            raise ValueError(f"Document hash mismatch: {doc['path']}")
        documents[doc["path"]] = doc
        document_ids.add(doc["document_id"])
        resolved_paths.add(path)

    task_ids = set()
    for task in tasks["tasks"]:
        _require(isinstance(task, dict), "Each task must be an object")
        tid = task.get("task_id")
        _require(_text(tid) and tid not in {".", ".."} and "/" not in tid and "\\" not in tid,
                 "Task ID must be a safe nonempty filename component")
        _require(tid not in task_ids, "Task IDs must be unique")
        task_ids.add(tid)
        _require(_text(task.get("case_id", tasks["case_id"])), "Task case_id must be nonempty text")
        year = task.get("tax_year", tasks["tax_year"])
        _require(type(year) is int and 1 <= year <= 9999, "Task tax_year must be a calendar year")
        _require(isinstance(task.get("instruction"), str) and bool(task["instruction"].strip()),
                 "Task instruction must be nonempty text")
        fields = task.get("fields")
        _require(isinstance(fields, dict) and bool(fields) and all(
            _text(key) and isinstance(kind, str) and kind in FIELD_KINDS for key, kind in fields.items()
        ), "Task fields must be nonempty with supported types")
        paths = task.get("documents")
        _require(isinstance(paths, list) and bool(paths) and all(
            isinstance(path, str) and path in documents for path in paths
        ), "Task documents must be nonempty and present in the manifest")
        _require(len(set(paths)) == len(paths), "Task documents must not contain duplicates")
        _require(tid in field_types and field_types[tid] == fields,
                 "Task fields differ from the standalone grader field_types")
        answer = expected.get(tid)
        _require(isinstance(answer, dict) and set(answer) == {"values", "evidence"}
                 and not schema_errors(answer, fields),
                 "Reference answer must exactly match requested fields and types")
        assigned = {documents[path]["document_id"]: documents[path]["page_count"] for path in paths}
        for refs in answer["evidence"].values():
            for ref in refs:
                # Reference annotations also carry bbox, which is deliberately
                # outside this evaluator's scoring scope. Preserve that metadata.
                _require(ref["document_id"] in assigned
                         and 1 <= ref["page"] <= assigned[ref["document_id"]]
                         and _text(ref["box"]),
                         "Reference evidence must cite an assigned document and valid page/box")
    _require(set(expected) == task_ids and set(field_types) == task_ids,
             "Task, reference, and field_types memberships must match exactly")

    examples = [
        Example(
            input=TaskInput(
                task_id=task["task_id"],
                case_id=task.get("case_id", tasks["case_id"]),
                tax_year=task.get("tax_year", tasks["tax_year"]),
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
    for name in ("tasks.json", "manifest.json", "ground_truth/expected.json", "ground_truth/field_types.json"):
        digest.update(name.encode() + b"\0" + (root / name).read_bytes() + b"\0")
    return examples, digest.hexdigest()

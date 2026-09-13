"""Publish saved traces to Phoenix with a confirmed-delivery checkpoint."""

import hashlib
import json
from pathlib import Path

from ..telemetry.otlp import _rejected_spans, encode_otlp
from ..telemetry.spans import _validate_spans


def publish_traces(http, run_dir: Path, *, project_name: str = "doc-intell-poc") -> dict:
    """Upload saved spans once confirmed; a retry never invokes a harness.

    An uncertain HTTP outcome may require resending the same stable span IDs.
    This checkpoint makes no claim of exactly-once delivery across that boundary.
    """
    path = run_dir / "traces.json"
    if not path.exists():
        return {"complete": True, "spans": 0, "legacy_without_traces": True}
    payload = path.read_bytes()
    spans = json.loads(payload)
    if not isinstance(spans, list):
        raise ValueError("Trace artifact must contain a list of spans")
    _validate_spans(spans)
    digest = hashlib.sha256(payload).hexdigest()
    state_path = run_dir / "traces-upload.json"
    destination = str(getattr(http, "base_url", ""))
    expected = {"sha256": digest, "project_name": project_name, "destination": destination}
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if any(state.get(key) != value for key, value in expected.items()):
            raise ValueError("Trace upload checkpoint belongs to different content or destination")
        if state.get("complete"):
            return state
    if spans:
        encoded = encode_otlp(spans, project_name=project_name)
        response = http.post("/v1/traces", content=encoded,
                             headers={"Content-Type": "application/x-protobuf"})
        response.raise_for_status()
        if _rejected_spans(response.content):
            raise RuntimeError("Phoenix rejected one or more trace spans")
    state = {**expected, "spans": len(spans), "complete": True}
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(state_path)
    return state

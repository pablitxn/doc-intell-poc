"""Measured task spans, observed native lifecycles, and explicit OTLP publication."""

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re


_HEX = re.compile(r"^[0-9a-f]+$")
_TOKEN_ATTRIBUTES = {
    "input_tokens": "llm.token_count.prompt",
    "output_tokens": "llm.token_count.completion",
    "cache_read_tokens": "llm.token_count.prompt_details.cache_read",
    "cache_write_tokens": "llm.token_count.prompt_details.cache_write",
}


def _span_id(trace_id: str, name: str) -> str:
    return hashlib.sha256(f"{trace_id}:{name}".encode()).hexdigest()[:16]


def _span(trace_id, span_id, parent, name, start, end, attributes, status="OK"):
    return {
        "trace_id": trace_id, "span_id": span_id, "parent_span_id": parent,
        "name": name, "kind": "INTERNAL", "start_time_unix_nano": start,
        "end_time_unix_nano": end, "status": status, "attributes": attributes,
    }


def _usage_attributes(usage: dict) -> dict:
    # Cache counts are subcategories; do not add them again to prompt/total tokens.
    return {
        attribute: usage[key] for key, attribute in _TOKEN_ATTRIBUTES.items()
        if type(usage.get(key)) is int and usage[key] >= 0
    }


def build_task_trace(
    row: dict, *, trace_id: str, root_span_id: str, harness_span_id: str,
    harness_start_ns: int, harness_end_ns: int, task_end_ns: int,
    events: list[dict], metadata: dict,
) -> list[dict]:
    """Build external spans plus internal spans only for observed native starts.

    An unmatched end is not evidence of a start time. An unmatched start is closed
    at the observed process boundary and explicitly marked incomplete. The caller
    retains native OTel correlation separately; these spans do not reparent it.
    """
    if not 0 <= harness_start_ns <= harness_end_ns <= task_end_ns:
        raise ValueError("Task trace timestamps must be ordered")
    task_start_ns = harness_start_ns
    if row.get("start_time"):
        started = datetime.fromisoformat(row["start_time"])
        task_start_ns = min(int(started.timestamp() * 1_000_000_000), harness_start_ns)
    execution_status = row.get("execution_status", "success")
    status = "OK" if execution_status == "success" else "ERROR"
    attributes = {
        "openinference.span.kind": "CHAIN",
        "benchmark.task_id": row["task_id"],
        "benchmark.repetition": row.get("repetition", 1),
        "benchmark.execution_status": execution_status,
        "metadata": json.dumps(metadata, sort_keys=True, allow_nan=False),
    }
    for name in ("schema_valid", "value_accuracy", "evidence_accuracy", "task_pass"):
        if name in row.get("scores", {}):
            attributes[f"benchmark.score.{name}"] = row["scores"][name]
    if "input" in row:
        attributes.update({"input.value": row["input"], "input.mime_type": "text/plain"})
    if "output" in row:
        attributes.update({"output.value": json.dumps(row["output"], allow_nan=False),
                           "output.mime_type": "application/json"})
    spans = [
        _span(trace_id, root_span_id, None, "task.execute", task_start_ns,
              task_end_ns, attributes, status),
        _span(trace_id, harness_span_id, root_span_id, "harness.execute", harness_start_ns,
              harness_end_ns, {"openinference.span.kind": "AGENT",
                               "benchmark.execution_status": execution_status,
                               "metadata": json.dumps({**row.get("telemetry", {}),
                                                       "usage": row.get("usage", {})},
                                                      sort_keys=True, allow_nan=False)}, status),
        _span(trace_id, _span_id(trace_id, "evaluate"), root_span_id, "evaluate",
              harness_end_ns, task_end_ns, {"openinference.span.kind": "EVALUATOR"}),
    ]
    opened, finished = {}, set()
    for event in events:
        kind = event.get("kind", "")
        if kind not in ("llm_start", "llm_end", "tool_start", "tool_end"):
            continue
        identity, timestamp = event.get("id"), event.get("timestamp_ns")
        if (not isinstance(identity, str) or not identity or type(timestamp) is not int
                or timestamp < 0 or event.get("timestamp_source") != "observed"):
            continue
        family, phase = kind.split("_")
        key = family, identity
        if key in finished:
            continue
        if phase == "start":
            opened.setdefault(key, event)
            continue
        start = opened.get(key)
        if start is None or timestamp < start["timestamp_ns"]:
            continue
        del opened[key]
        finished.add(key)
        native_attributes = {
            "openinference.span.kind": "LLM" if family == "llm" else "TOOL",
            "benchmark.native_event_id": identity,
            "benchmark.timestamp_source": "observed",
        }
        if family == "llm":
            native_attributes.update(_usage_attributes(event.get("usage") or {}))
            for key, attribute in (("model", "llm.model_name"), ("provider", "llm.provider")):
                value = row.get("telemetry", {}).get(key)
                if isinstance(value, str) and value:
                    native_attributes[attribute] = value
        native_status = "ERROR" if event.get("status") in ("error", "failed", "ERROR") else "OK"
        spans.append(_span(trace_id, _span_id(trace_id, f"{family}:{identity}"), harness_span_id,
                           start.get("name") or family, start["timestamp_ns"], timestamp,
                           native_attributes, native_status))
    for (family, identity), start in opened.items():
        spans.append(_span(
            trace_id, _span_id(trace_id, f"{family}:{identity}"), harness_span_id,
            start.get("name") or family, start["timestamp_ns"],
            max(start["timestamp_ns"], harness_end_ns), {
                "openinference.span.kind": "LLM" if family == "llm" else "TOOL",
                "benchmark.native_event_id": identity,
                "benchmark.timestamp_source": "observed",
                "benchmark.end_time_source": "process_boundary",
                "benchmark.incomplete": True,
            }, "ERROR",
        ))
    return spans


def _validate_spans(spans: list[dict]) -> None:
    identities = set()
    for span in spans:
        if not isinstance(span, dict):
            raise ValueError("Trace spans must be objects")
        for field, length in (("trace_id", 32), ("span_id", 16), ("parent_span_id", 16)):
            value = span.get(field)
            if field == "parent_span_id" and value is None:
                continue
            if (not isinstance(value, str) or len(value) != length or not _HEX.fullmatch(value)
                    or int(value, 16) == 0):
                raise ValueError(f"Invalid trace span {field}")
        identity = span["trace_id"], span["span_id"]
        if identity in identities:
            raise ValueError("Duplicate trace/span identity")
        identities.add(identity)
        start, end = span.get("start_time_unix_nano"), span.get("end_time_unix_nano")
        if type(start) is not int or type(end) is not int or not 0 <= start <= end:
            raise ValueError("Invalid trace span timestamps")
        if not isinstance(span.get("name"), str) or not span["name"]:
            raise ValueError("Trace span name is required")
        if span.get("status") not in ("OK", "ERROR", "UNSET"):
            raise ValueError("Invalid trace span status")
        if not isinstance(span.get("attributes"), dict):
            raise ValueError("Trace span attributes must be an object")


def encode_otlp(spans: list[dict], *, project_name: str) -> bytes:
    """Serialize with the official protobuf package, imported only for export."""
    _validate_spans(spans)
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    request = ExportTraceServiceRequest()
    resource = request.resource_spans.add()
    for key, value in (("service.name", "doc-intell-poc"), ("openinference.project.name", project_name)):
        attribute = resource.resource.attributes.add(key=key)
        attribute.value.string_value = value
    scope = resource.scope_spans.add()
    scope.scope.name, scope.scope.version = "doc-intell-poc", "1"
    for item in spans:
        span = scope.spans.add(
            trace_id=bytes.fromhex(item["trace_id"]), span_id=bytes.fromhex(item["span_id"]),
            parent_span_id=bytes.fromhex(item["parent_span_id"]) if item.get("parent_span_id") else b"",
            name=item["name"], kind=1, start_time_unix_nano=item["start_time_unix_nano"],
            end_time_unix_nano=item["end_time_unix_nano"],
        )
        span.status.code = {"UNSET": 0, "OK": 1, "ERROR": 2}[item["status"]]
        for key, value in item["attributes"].items():
            if value is None:
                continue
            attribute = span.attributes.add(key=key)
            if isinstance(value, bool):
                attribute.value.bool_value = value
            elif isinstance(value, int):
                attribute.value.int_value = value
            elif isinstance(value, float) and math.isfinite(value):
                attribute.value.double_value = value
            elif isinstance(value, str):
                attribute.value.string_value = value
            else:
                attribute.value.string_value = json.dumps(value, sort_keys=True, allow_nan=False)
    return request.SerializeToString()


def _rejected_spans(body: bytes) -> int:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse

    result = ExportTraceServiceResponse()
    result.ParseFromString(body)
    return result.partial_success.rejected_spans


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

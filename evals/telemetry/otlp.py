"""Encode local span evidence and decode OTLP collector acknowledgements."""

import json
import math

from .spans import _validate_spans


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

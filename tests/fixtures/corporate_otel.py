"""Model-free corporate process: stdin -> JSON stdout plus genuine SDK spans."""

import json
import os
import sys

from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode


prompt = sys.stdin.read()
compression = {"none": Compression.NoCompression, "gzip": Compression.Gzip}[sys.argv[1]]
provider = TracerProvider(resource=Resource.create({"service.name": "corporate-conformance"}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(compression=compression, timeout=10)))
tracer = provider.get_tracer("doc-intell-corporate-fixture", "1.0")
parent = extract({"traceparent": os.environ["TRACEPARENT"]})
with tracer.start_as_current_span("corporate.execute", context=parent) as operation:
    with tracer.start_as_current_span("corporate.read_document") as child:
        child.set_attribute("benchmark.conformance", True)
        child.set_status(Status(StatusCode.OK))
        child_id = format(child.get_span_context().span_id, "016x")
    operation.set_status(Status(StatusCode.OK))
    operation_id = format(operation.get_span_context().span_id, "016x")
    trace_id = format(operation.get_span_context().trace_id, "032x")
flushed = provider.force_flush(timeout_millis=15000)
provider.shutdown()
print(json.dumps({
    "values": {
        "flushed": flushed, "prompt": prompt, "trace_id": trace_id,
        "operation_span_id": operation_id, "child_span_id": child_id,
        "traceparent": os.environ["TRACEPARENT"],
        "run_id": os.environ["DOC_INTELL_RUN_ID"],
        "task_id": os.environ["DOC_INTELL_TASK_ID"],
        "repetition": os.environ["DOC_INTELL_REPETITION"],
        "endpoint": os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"],
        "protocol": os.environ["OTEL_EXPORTER_OTLP_TRACES_PROTOCOL"],
        "resource_attributes": os.environ["OTEL_RESOURCE_ATTRIBUTES"],
        "compression": sys.argv[1],
        "provider_credentials_absent": not any(os.environ.get(name) for name in (
            "OPENAI_API_KEY", "OPENAI_CODEX_ACCESS_TOKEN", "PHOENIX_API_KEY")),
    },
    "evidence": {},
}))

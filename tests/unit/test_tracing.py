"""Trace evidence and upload recovery; no harnesses or providers are invoked."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from evals.reporting.trace_upload import publish_traces
from evals.telemetry.otlp import encode_otlp
from evals.telemetry.spans import build_task_trace


TRACE = "1" * 32
ROOT = "2" * 16
HARNESS = "3" * 16


def task_trace(events=(), **changes):
    row = {"task_id": "extract", "repetition": 2, "execution_status": "success",
           "scores": {"task_pass": False}, "output": {"values": {}}}
    row.update(changes)
    return build_task_trace(
        row, trace_id=TRACE, root_span_id=ROOT, harness_span_id=HARNESS,
        harness_start_ns=100, harness_end_ns=200, task_end_ns=220,
        events=list(events), metadata={"profile": "test"},
    )


def event(kind, identity, timestamp, **kwargs):
    return {"kind": kind, "id": identity, "timestamp_ns": timestamp,
            "timestamp_source": "observed", **kwargs}


class TracingTests(unittest.TestCase):
    def test_external_hierarchy_preserves_execution_and_quality_distinction(self):
        spans = task_trace()
        self.assertEqual([span["name"] for span in spans], ["task.execute", "harness.execute", "evaluate"])
        self.assertEqual([span["parent_span_id"] for span in spans], [None, ROOT, ROOT])
        self.assertTrue(all(span["trace_id"] == TRACE for span in spans))
        self.assertEqual(spans[0]["status"], "OK")
        self.assertFalse(spans[0]["attributes"]["benchmark.score.task_pass"])
        self.assertEqual(spans[2]["start_time_unix_nano"], 200)
        self.assertEqual(spans[2]["end_time_unix_nano"], 220)
        self.assertEqual(task_trace(execution_status="timeout")[1]["status"], "ERROR")

    def test_only_observed_lifecycles_create_internal_spans_without_double_counting(self):
        usage = {"input_tokens": 10, "output_tokens": 3, "cache_read_tokens": 4,
                 "cache_write_tokens": None}
        start = event("llm_start", "message-1", 110, name="model.call")
        end = event("llm_end", "message-1", 150, usage=usage)
        spans = task_trace([
            start, start, end, end,
            event("tool_start", "tool-1", 160, name="read_pdf"),
            event("tool_end", "tool-1", 180),
            event("llm_end", "unknown-start", 190, usage=usage),
            {**start, "id": "unobserved", "timestamp_source": "estimated"},
        ], usage=usage, telemetry={"model": "observed-model", "provider": "observed-provider"})
        self.assertEqual(len(spans), 5)
        llm = spans[3]
        self.assertEqual(llm["parent_span_id"], HARNESS)
        self.assertEqual((llm["start_time_unix_nano"], llm["end_time_unix_nano"]), (110, 150))
        self.assertEqual(llm["attributes"]["llm.token_count.prompt"], 10)
        self.assertEqual(llm["attributes"]["llm.token_count.completion"], 3)
        self.assertEqual(llm["attributes"]["llm.model_name"], "observed-model")
        self.assertNotIn("llm.token_count.total", llm["attributes"])
        token_spans = [span for span in spans if "llm.token_count.prompt" in span["attributes"]]
        self.assertEqual(len(token_spans), 1)
        self.assertEqual(spans[4]["attributes"]["openinference.span.kind"], "TOOL")

    def test_interrupted_native_span_is_explicitly_incomplete(self):
        span = task_trace([event("tool_start", "open", 175)], execution_status="timeout")[-1]
        self.assertEqual(span["end_time_unix_nano"], 200)
        self.assertTrue(span["attributes"]["benchmark.incomplete"])
        self.assertEqual(span["attributes"]["benchmark.end_time_source"], "process_boundary")
        self.assertEqual(span["status"], "ERROR")

    def test_aggregate_usage_without_llm_boundaries_remains_inspectable(self):
        usage = {"input_tokens": 20, "output_tokens": 8, "cache_read_tokens": 10}
        spans = task_trace(usage=usage, telemetry={"session_id": "native-session"})
        metadata = json.loads(spans[1]["attributes"]["metadata"])
        self.assertEqual(metadata["usage"], usage)
        self.assertEqual(metadata["session_id"], "native-session")
        self.assertTrue(all(not any(key.startswith("llm.token_count") for key in span["attributes"])
                            for span in spans))

    def test_native_identifiers_make_retry_serialization_stable(self):
        events = [event("llm_start", "1", 110), event("llm_end", "1", 150)]
        self.assertEqual(task_trace(events), task_trace(events))
        json.dumps(task_trace(events), allow_nan=False)

    def test_real_protobuf_encoding_preserves_ids_parent_and_attributes(self):
        try:
            from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
        except ImportError:
            self.skipTest("Optional OTLP dependency is not installed in this Python runtime")
        encoded = encode_otlp(task_trace(), project_name="benchmark")
        request = ExportTraceServiceRequest.FromString(encoded)
        resource = request.resource_spans[0]
        self.assertEqual(resource.resource.attributes[1].value.string_value, "benchmark")
        spans = resource.scope_spans[0].spans
        self.assertEqual(spans[0].trace_id.hex(), TRACE)
        self.assertEqual(spans[1].parent_span_id.hex(), ROOT)
        self.assertEqual(spans[0].status.code, 1)

    def test_invalid_span_artifact_fails_before_network_mutation(self):
        http = SimpleNamespace(post=lambda *args, **kwargs: self.fail("Unexpected HTTP request"))
        for mutation in ("duplicate", "trace_id", "time"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as tmp:
                spans = task_trace()
                if mutation == "duplicate":
                    spans.append(deepcopy(spans[0]))
                elif mutation == "trace_id":
                    spans[0]["trace_id"] = "bad"
                else:
                    spans[0]["end_time_unix_nano"] = 0
                directory = Path(tmp)
                (directory / "traces.json").write_text(json.dumps(spans))
                with self.assertRaises(ValueError):
                    publish_traces(http, directory)
                self.assertFalse((directory / "traces-upload.json").exists())

    def test_upload_retry_only_checkpoints_confirmed_success(self):
        calls = []
        def post(url, **kwargs):
            calls.append((url, kwargs))
            if len(calls) == 1:
                raise ConnectionError("interrupted")
            return SimpleNamespace(content=b"", raise_for_status=lambda: None)
        http = SimpleNamespace(base_url="http://localhost:6006/", post=post)
        with TemporaryDirectory() as tmp, patch("evals.reporting.trace_upload.encode_otlp", return_value=b"protobuf"), \
                patch("evals.reporting.trace_upload._rejected_spans", return_value=0):
            directory = Path(tmp)
            (directory / "traces.json").write_text(json.dumps(task_trace()))
            with self.assertRaises(ConnectionError):
                publish_traces(http, directory)
            self.assertFalse((directory / "traces-upload.json").exists())
            state = publish_traces(http, directory)
            self.assertEqual(state, publish_traces(http, directory))
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0], calls[1])
            self.assertTrue(state["complete"])
            self.assertEqual(calls[1][0], "/v1/traces")
            self.assertEqual(calls[1][1]["headers"]["Content-Type"], "application/x-protobuf")

    def test_partial_rejection_does_not_report_complete(self):
        http = SimpleNamespace(post=lambda *args, **kwargs: SimpleNamespace(
            content=b"", raise_for_status=lambda: None))
        with TemporaryDirectory() as tmp, patch("evals.reporting.trace_upload.encode_otlp", return_value=b"protobuf"), \
                patch("evals.reporting.trace_upload._rejected_spans", return_value=1):
            directory = Path(tmp)
            (directory / "traces.json").write_text(json.dumps(task_trace()))
            with self.assertRaisesRegex(RuntimeError, "rejected"):
                publish_traces(http, directory)
            self.assertFalse((directory / "traces-upload.json").exists())

    def test_legacy_report_without_trace_artifact_does_not_import_exporter(self):
        with TemporaryDirectory() as tmp:
            state = publish_traces(None, Path(tmp))
        self.assertTrue(state["complete"])
        self.assertTrue(state["legacy_without_traces"])


if __name__ == "__main__":
    unittest.main()

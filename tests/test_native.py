"""Exercise native wire fixtures through harmless real Python subprocesses.

Fixtures follow official schemas: earendil-works/pi packages/coding-agent/docs/json.md,
huggingface/tau src/tau_agent/{events,messages}.py, and openai/codex
codex-rs/exec/src/exec_events.rs (reviewed 2026-09-13).
"""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from evals.adapters import native
from evals.adapters.native import NativeHarness
from evals.contracts import HarnessInvocation, ProcessSpec


def assistant(text='{"answer":42}', *, timestamp=10, usage=None, tool=False):
    content = [{"type": "text", "text": text}]
    if tool:
        content.append({"type": "toolCall", "id": "call-1", "name": "read",
                        "arguments": {"path": "private-path"}})
    message = {"role": "assistant", "content": content, "api": "openai-codex-responses",
               "provider": "openai-codex", "model": "fixture-model", "timestamp": timestamp,
               "stopReason": "toolUse" if tool else "stop"}
    if usage is not None:
        message["usage"] = usage
    return message


def pi_events(message=None):
    message = message or assistant()
    return [{"type": "session", "version": 3, "id": "session-1"},
            {"type": "agent_start"}, {"type": "turn_start"},
            {"type": "message_start", "message": {"role": "assistant", "content": []}},
            {"type": "message_end", "message": message},
            {"type": "turn_end", "message": message, "toolResults": []},
            {"type": "agent_end", "messages": [message]}]


def codex_events(text='{"answer":42}'):
    return [{"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "item-1", "type": "agent_message", "text": text}},
            {"type": "turn.completed", "usage": {"input_tokens": 15, "cached_input_tokens": 5,
                                                   "output_tokens": 4}}]


def emit_code(events):
    text = "".join(json.dumps(event) + "\n" for event in events)
    return f"import sys; sys.stdout.write({text!r}); sys.stdout.flush()"


class NativeHarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.invocation = HarnessInvocation(
            input_text="Read a dataset path. ¿Qué dice?\n", task_id="task-1", repetition=1,
            dataset=self.root, documents=(), artifact_dir=self.root,
            trace_id="1" * 32, parent_span_id="2" * 16,
        )

    def harness(self, code, mode="pi-jsonl", timeout=2.0, **spec_fields):
        @contextmanager
        def prepare(invocation):
            self.assertIs(invocation, self.invocation)
            yield ProcessSpec(argv=(sys.executable, "-c", code), **spec_fields)
        return NativeHarness({"output_mode": mode}, prepare, timeout)

    def run_events(self, events, mode="pi-jsonl"):
        return self.harness(emit_code(events), mode).invoke(self.invocation)

    def test_generic_json_passes_exact_stdin_and_preserves_answer(self):
        result = self.harness(
            "import json,sys; print(json.dumps({'input':sys.stdin.read(),'value':False}))",
            "json",
        ).invoke(self.invocation)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.output, {"input": self.invocation.input_text, "value": False})
        self.assertEqual(result.events, [])
        self.assertTrue(all(value is None for value in result.usage.values()))

    def test_each_invocation_starts_a_fresh_process(self):
        harness = self.harness("import json,os; print(json.dumps(os.getpid()))", "json")
        self.assertNotEqual(harness.invoke(self.invocation).output, harness.invoke(self.invocation).output)

    def test_prepared_environment_and_cwd_are_used_without_shell(self):
        result = self.harness(
            "import json,os; print(json.dumps({'cwd':os.getcwd(),'value':os.environ['TEST_VALUE']}))",
            "json", cwd=self.root, env={"TEST_VALUE": "$(must-not-run); `id`"},
        ).invoke(self.invocation)
        self.assertEqual(result.output, {"cwd": str(self.root.resolve()), "value": "$(must-not-run); `id`"})

    def test_pi_and_tau_camelcase_fixtures_produce_only_safe_metadata(self):
        for mode in ("pi-jsonl", "tau-jsonl"):
            with self.subTest(mode=mode):
                message = assistant(usage={"input": 10, "output": 0, "cacheRead": 3, "cacheWrite": 2})
                result = self.run_events(pi_events(message), mode)
                self.assertEqual(result.status, "success")
                self.assertEqual(result.output, {"answer": 42})
                self.assertEqual(result.usage["input_tokens"], 15)
                self.assertEqual(result.usage["output_tokens"], 0)
                self.assertIsNone(result.usage["reasoning_tokens"])
                self.assertEqual(result.metadata["provider"], "openai-codex")
                self.assertEqual(result.metadata["session_id"], "session-1")
                self.assertEqual([e["kind"] for e in result.events], ["llm_start", "llm_end"])
                for event in result.events:
                    self.assertEqual(event["timestamp_source"], "observed")
                    self.assertGreater(event["timestamp_ns"], 0)

    def test_tool_json_decoy_and_intermediate_assistant_never_become_final(self):
        first = assistant('{"decoy":"assistant"}', tool=True)
        final = assistant('{"answer":"final"}', timestamp=20)
        events = pi_events(first)[:-1] + [
            {"type": "tool_execution_start", "toolCallId": "call-1", "toolName": "read",
             "args": {"private": "synthetic-secret"}},
            {"type": "tool_execution_end", "toolCallId": "call-1", "toolName": "read",
             "result": {"content": [{"type": "text", "text": '{"secret":"synthetic-secret"}'}]}, "isError": False},
            {"type": "message_end", "message": {"role": "toolResult", "content": [{"type": "text", "text": '{"decoy":true}'}]}},
            {"type": "message_start", "message": {"role": "assistant", "content": []}},
            {"type": "message_end", "message": final},
            {"type": "agent_end", "messages": [first, final]},
        ]
        result = self.run_events(events)
        self.assertEqual(result.output, {"answer": "final"})
        self.assertNotIn("synthetic-secret", repr(result))
        self.assertNotIn("private-path", repr(result))
        self.assertEqual([e["kind"] for e in result.events],
                         ["llm_start", "llm_end", "tool_start", "tool_end", "llm_start", "llm_end"])

    def test_tool_use_without_final_answer_is_invalid(self):
        result = self.run_events(pi_events(assistant('{}', tool=True)))
        self.assertEqual(result.status, "invalid_response")
        self.assertEqual(result.error, "MissingFinalResponse")

    def test_codex_subscription_composite_tool_ids_do_not_invalidate_pi_tau_answers(self):
        # Tau 0.4.3 openai_codex._ToolCallState.build uses call_id|item_id.
        # These are opaque correlation IDs, not restricted identifier names.
        for mode in ("pi-jsonl", "tau-jsonl"):
            with self.subTest(mode=mode):
                events = pi_events()
                events[2:2] = [
                    {"type": "tool_execution_start", "toolCallId": "call_example|fc_example",
                     "toolName": "bash", "args": {"command": "private command"}},
                    {"type": "tool_execution_end", "toolCallId": "call_example|fc_example",
                     "toolName": "bash", "result": {}, "isError": False},
                ]
                result = self.run_events(events, mode)
                self.assertEqual(result.status, "success")
                self.assertEqual(result.output, {"answer": 42})
                tools = [event for event in result.events if event["kind"].startswith("tool_")]
                self.assertEqual([event["kind"] for event in tools], ["tool_start", "tool_end"])
                self.assertEqual(tools[0]["id"], tools[1]["id"])
                self.assertNotIn("private command", repr(result))

    def test_explicit_final_phase_excludes_commentary_in_same_message(self):
        message = assistant()
        message["content"] = [
            {"type": "text", "text": "I will examine the documents.",
             "textSignature": json.dumps({"v": 1, "id": "part-1", "phase": "commentary"})},
            {"type": "text", "text": '{"answer":42}',
             "textSignature": json.dumps({"v": 1, "id": "part-2", "phase": "final_answer"})},
        ]
        self.assertEqual(self.run_events(pi_events(message)).output, {"answer": 42})
        message["content"] = message["content"][:1]
        self.assertEqual(self.run_events(pi_events(message)).status, "invalid_response")

    def test_only_last_assistant_response_is_parsed(self):
        events = pi_events()[:-1] + [
            {"type": "message_end", "message": assistant("not json", timestamp=20)},
            {"type": "agent_end", "messages": []},
        ]
        self.assertEqual(self.run_events(events).status, "invalid_response")

    def test_codex_tools_and_usage_are_observed_without_fabricated_llm_spans(self):
        events = codex_events()
        events[2:2] = [
            {"type": "item.started", "item": {"id": "tool-1", "type": "command_execution", "command": "private command", "status": "in_progress"}},
            {"type": "item.completed", "item": {"id": "tool-1", "type": "command_execution", "aggregated_output": '{"decoy":true}', "exit_code": 0, "status": "completed"}},
        ]
        events.append(events[-1])  # repeated accumulated usage, not another charge
        result = self.run_events(events, "codex-jsonl")
        self.assertEqual(result.output, {"answer": 42})
        self.assertEqual(result.usage["input_tokens"], 15)
        self.assertEqual(result.usage["cache_read_tokens"], 5)
        self.assertIsNone(result.usage["cache_write_tokens"])
        self.assertEqual([e["kind"] for e in result.events], ["tool_start", "tool_end"])
        self.assertNotIn("private command", repr(result))

    def test_codex_mcp_and_failed_tools_keep_only_safe_lifecycle(self):
        events = codex_events()
        events[2:2] = [
            {"type": "item.started", "item": {"id": "mcp-1", "type": "mcp_tool_call", "server": "documents", "tool": "analyze", "arguments": {"credential": "synthetic-secret"}, "status": "in_progress"}},
            {"type": "item.completed", "item": {"id": "mcp-1", "type": "mcp_tool_call", "tool": "analyze", "error": {"message": "synthetic-secret"}, "status": "failed"}},
        ]
        result = self.run_events(events, "codex-jsonl")
        self.assertEqual(result.status, "success")  # task may recover from tool errors
        self.assertEqual(result.events[-1]["status"], "error")
        self.assertNotIn("synthetic-secret", repr(result))

    def test_pi_duplicate_message_end_and_aggregate_copies_do_not_double_usage(self):
        message = assistant(usage={"input": 7, "output": 2})
        events = pi_events(message)
        events.insert(-1, {"type": "message_end", "message": message})
        result = self.run_events(events)
        self.assertEqual(result.usage["input_tokens"], 7)
        self.assertEqual(result.usage["output_tokens"], 2)
        self.assertEqual(len(result.events), 2)

    def test_missing_usage_stays_unknown_and_reported_zero_is_preserved(self):
        missing = self.run_events(pi_events())
        zero = self.run_events(pi_events(assistant(usage={"input": 0, "output": 0})))
        self.assertIsNone(missing.usage["input_tokens"])
        self.assertEqual(zero.usage["input_tokens"], 0)
        self.assertIsNone(zero.usage["cache_read_tokens"])

    def test_partial_usage_is_not_reported_as_complete_total(self):
        first = assistant('{}', tool=True)
        final = assistant(usage={"input": 7, "output": 2}, timestamp=20)
        events = pi_events(first)[:-1] + [
            {"type": "message_end", "message": final},
            {"type": "agent_end", "messages": [first, final]},
        ]
        result = self.run_events(events)
        self.assertIsNone(result.usage["input_tokens"])
        self.assertIsNone(result.usage["output_tokens"])

    def test_json_is_strict_without_markdown_or_extra_object_repair(self):
        for value in ("```json\n{}\n```", "{}\n{}", "NaN", "1e999", "", "invalid secret"):
            with self.subTest(value=value):
                result = self.run_events(codex_events(value), "codex-jsonl")
                self.assertEqual(result.status, "invalid_response")
                self.assertEqual(result.error, "InvalidJSONResponse")
                self.assertIsNone(result.output)

    def test_duplicate_response_keys_are_rejected_for_every_transport(self):
        payloads = (
            '{"values":{},"values":{"amount":42}}',
            '{"values":{"amount":1,"amount":42}}',
            r'{"values":{"amount":1,"\u0061mount":42}}',
        )
        for mode in ("json", "pi-jsonl", "tau-jsonl", "codex-jsonl"):
            for payload in payloads:
                with self.subTest(mode=mode, payload=payload):
                    if mode == "json":
                        result = self.harness(f"import sys; sys.stdout.write({payload!r})", mode).invoke(self.invocation)
                    else:
                        events = codex_events(payload) if mode == "codex-jsonl" else pi_events(assistant(payload))
                        result = self.run_events(events, mode)
                    self.assertEqual(result.status, "invalid_response")
                    self.assertEqual(result.error, "InvalidJSONResponse")
                    self.assertIsNone(result.output)

    def test_duplicate_wire_event_keys_fail_safely_and_preserve_prior_telemetry(self):
        for mode in ("pi-jsonl", "tau-jsonl", "codex-jsonl"):
            with self.subTest(mode=mode):
                events = codex_events() if mode == "codex-jsonl" else pi_events(assistant(usage={"input": 10, "output": 2}))
                wire = "".join(json.dumps(event) + "\n" for event in events)
                wire += '{"type":"error","type":"agent_end","private-key-sentinel":true}\n'
                result = self.harness(f"import sys; sys.stdout.write({wire!r})", mode).invoke(self.invocation)
                self.assertEqual(result.status, "invalid_response")
                self.assertEqual(result.error, "InvalidStream")
                self.assertIsNone(result.output)
                self.assertIsNotNone(result.usage["input_tokens"])
                self.assertNotIn("private-key-sentinel", repr(result))

    def test_incomplete_native_stream_is_invalid_even_with_an_assistant_item(self):
        for mode, events in (("codex-jsonl", codex_events()), ("pi-jsonl", pi_events())):
            with self.subTest(mode=mode):
                result = self.run_events(events[:-1], mode)
                self.assertEqual(result.status, "invalid_response")
                self.assertEqual(result.error, "IncompleteStream")

    def test_invalid_utf8_and_malformed_stream_fail_safely(self):
        for code in ("import sys; sys.stdout.buffer.write(b'\\xff')", "print('synthetic-secret')"):
            result = self.harness(code).invoke(self.invocation)
            self.assertEqual(result.status, "invalid_response")
            self.assertEqual(result.error, "InvalidStream")
            self.assertNotIn("synthetic-secret", repr(result))

    def test_missing_final_message_is_distinct_from_invalid_json_text(self):
        result = self.run_events([{"type": "agent_start"}, {"type": "agent_end", "messages": []}])
        self.assertEqual(result.status, "invalid_response")
        self.assertEqual(result.error, "MissingFinalResponse")
        invalid = self.harness("print('not-json')", "json").invoke(self.invocation)
        self.assertEqual(invalid.status, "invalid_response")
        self.assertEqual(invalid.error, "InvalidJSONResponse")

    def test_unknown_event_payload_is_not_retained(self):
        result = self.run_events([{"type": "diagnostic", "payload": "synthetic-secret"}, *pi_events()])
        self.assertEqual(result.status, "success")
        self.assertNotIn("synthetic-secret", repr(result))

    def test_nonzero_exit_preserves_events_and_suppresses_diagnostics(self):
        code = emit_code(pi_events()) + "; print('synthetic-secret',file=sys.stderr); sys.exit(9)"
        result = self.harness(code).invoke(self.invocation)
        self.assertEqual(result.status, "adapter_error")
        self.assertEqual(result.error, "ProcessExitError")
        self.assertEqual(len(result.events), 2)
        self.assertNotIn("synthetic-secret", repr(result))

    def test_native_fatal_event_is_error_even_when_process_exits_zero(self):
        result = self.run_events([*codex_events(), {"type": "turn.failed", "error": {"message": "synthetic-secret"}}], "codex-jsonl")
        self.assertEqual(result.status, "adapter_error")
        self.assertEqual(result.error, "HarnessError")
        self.assertNotIn("synthetic-secret", repr(result))

    def test_timeout_preserves_received_events_and_does_not_wait_for_children(self):
        code = emit_code(pi_events()) + "; import subprocess,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(4)']); time.sleep(4)"
        started = time.monotonic()
        result = self.harness(code, timeout=0.25).invoke(self.invocation)
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.error, "Timeout")
        self.assertEqual(len(result.events), 2)
        self.assertLess(time.monotonic() - started, 2)

    def test_stdout_and_line_limits_preserve_earlier_events(self):
        for constant in ("MAX_STDOUT_BYTES", "MAX_LINE_BYTES"):
            with self.subTest(constant=constant), patch.object(native, constant, 4096):
                code = emit_code(pi_events()) + "; sys.stdout.write('x'*8192); sys.stdout.flush()"
                result = self.harness(code).invoke(self.invocation)
                self.assertEqual(result.status, "adapter_error")
                self.assertEqual(result.error, "OutputLimit")

    def test_closing_stdout_then_sleeping_is_still_bounded(self):
        code = "import os,time; os.close(1); time.sleep(4)"
        started = time.monotonic()
        result = self.harness(code, timeout=0.2).invoke(self.invocation)
        self.assertEqual(result.status, "timeout")
        self.assertLess(time.monotonic() - started, 2)

    def test_prepare_and_cleanup_exceptions_are_sanitized(self):
        @contextmanager
        def prepare(_):
            raise RuntimeError("synthetic-secret")
            yield
        result = NativeHarness({"output_mode": "json"}, prepare).invoke(self.invocation)
        self.assertEqual(result.error, "PreparationError")
        self.assertNotIn("synthetic-secret", repr(result))

        @contextmanager
        def cleanup(_):
            yield ProcessSpec((sys.executable, "-c", emit_code(pi_events())))
            raise RuntimeError("synthetic-secret")
        result = NativeHarness({"output_mode": "pi-jsonl"}, cleanup).invoke(self.invocation)
        self.assertEqual(result.error, "PreparationError")
        self.assertEqual(len(result.events), 2)

    def test_invalid_timeouts_and_output_modes_fail_before_launch(self):
        for timeout in (0, -1, float("nan"), float("inf"), True, "3", None):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "finite positive"):
                NativeHarness({"output_mode": "json"}, None, timeout)
        with self.assertRaisesRegex(ValueError, "output mode"):
            NativeHarness({"output_mode": "magic"}, None)


if __name__ == "__main__":
    unittest.main()

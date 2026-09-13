"""Normalize native CLI streams into final answers and lifecycle metadata.

Wire contracts: Pi docs/json.md, Tau src/tau_agent/{events,messages}.py,
and Codex codex-rs/exec/src/exec_events.rs in their official repositories.
Raw diagnostics, tool arguments/results and intermediate model text never
cross this boundary into persisted events.
"""

import hashlib
import json
import re
import time

from evals.contracts import HarnessResult
from evals.json_io import strict_json_loads as _strict_json


MAX_EVENTS = 20000
OUTPUT_MODES = {"json", "pi-jsonl", "tau-jsonl", "codex-jsonl"}
_USAGE_KEYS = (
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "reasoning_tokens",
)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:/-]{1,200}\Z")


def _identifier(value: object) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def _event_identifier(value: object) -> str | None:
    """Normalize opaque wire IDs without rejecting valid provider punctuation.

    Pi/Tau's Codex provider joins call and item IDs with a pipe. Other providers
    may use different opaque strings. Hash non-simple IDs so lifecycle pairing
    survives while arbitrary text cannot enter the saved metadata.
    """
    if not isinstance(value, str) or not value:
        return None
    return _identifier(value) or "opaque-" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _counter(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _pick(mapping: dict, *keys: str) -> object:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _usage(value: object, *, codex: bool = False) -> dict:
    source = value if isinstance(value, dict) else {}
    aliases = (
        ("input_tokens",), ("output_tokens",), ("cached_input_tokens",),
        ("cache_write_input_tokens",), ("reasoning_output_tokens",),
    ) if codex else (
        ("input",), ("output",), ("cacheRead", "cache_read"),
        ("cacheWrite", "cache_write"), ("reasoning",),
    )
    normalized = {name: _counter(_pick(source, *fields)) for name, fields in zip(_USAGE_KEYS, aliases)}
    # Pi/Tau expose fresh input separately; Codex exposes total prompt input.
    # Normalize to total input while retaining cache subsets independently.
    if not codex and normalized["input_tokens"] is not None:
        normalized["input_tokens"] += sum(
            normalized[key] or 0 for key in ("cache_read_tokens", "cache_write_tokens")
        )
    return normalized


class StreamFailure(Exception):
    def __init__(self, category: str):
        self.category = category


class EventCollector:
    def __init__(self, mode: str):
        self.mode = mode
        self.events: list[dict] = []
        self.metadata: dict = {"timestamp_source": "observed"}
        self.usages: dict[str, dict] = {}
        self.final_text: str | None = None
        self.protocol_error = False
        self.harness_error = False
        self.last_assistant_failed = False
        self.completed = False
        self._seen_messages: set[str] = set()
        self._seen_events: set[tuple[str, str]] = set()
        self._active_message: str | None = None
        self._message_number = 0
        self._turn_number = 0

    def emit(self, kind: str, identifier: str, timestamp: int, **fields) -> None:
        key = (kind, identifier)
        if key in self._seen_events:
            return
        if len(self.events) >= MAX_EVENTS:
            raise StreamFailure("OutputLimit")
        self._seen_events.add(key)
        self.events.append({
            "kind": kind, "id": identifier, "timestamp_ns": timestamp,
            "timestamp_source": "observed", **fields,
        })

    def accept(self, line: bytes) -> None:
        if not line.strip():
            return
        timestamp = time.time_ns()
        try:
            event = _strict_json(line.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            self.protocol_error = True
            return
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            self.protocol_error = True
            return
        if self.mode == "codex-jsonl":
            self._codex(event, timestamp)
        else:
            self._pi_tau(event, timestamp)

    def _pi_tau(self, event: dict, timestamp: int) -> None:
        kind = event["type"]
        if kind == "agent_start":
            self.completed = False
            self.final_text = None
        elif kind in {"agent_end", "agent_settled"}:
            self.completed = True
        elif kind == "session":
            session = _identifier(event.get("id"))
            if session:
                self.metadata["session_id"] = session
        elif kind == "error" and event.get("recoverable") is not True:
            self.harness_error = True
        elif kind in {"message_start", "message_end"}:
            message = event.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                return
            if kind == "message_start":
                self._message_number += 1
                self._active_message = f"llm-{self._message_number}"
                self.emit("llm_start", self._active_message, timestamp)
                return
            # message_end is authoritative. turn_end/agent_end contain copies;
            # never count their messages again or treat tool results as answers.
            fingerprint = hashlib.sha256(
                json.dumps(message, sort_keys=True, ensure_ascii=True).encode()
            ).hexdigest()
            if fingerprint in self._seen_messages:
                return
            self._seen_messages.add(fingerprint)
            if self._active_message is None:
                self._message_number += 1
            identifier = self._active_message or f"llm-{self._message_number}"
            self._active_message = None
            usage = _usage(message.get("usage"))
            self.usages[identifier] = usage
            reason = _pick(message, "stopReason", "stop_reason")
            self.last_assistant_failed = reason in {"error", "aborted"}
            self.emit("llm_end", identifier, timestamp, usage=usage,
                      status="error" if self.last_assistant_failed else "success")
            for key in ("provider", "model"):
                value = _identifier(message.get(key))
                if value and value != "unknown":
                    self.metadata[key] = value
            for key, aliases in (
                ("response_model", ("responseModel", "response_model")),
                ("response_provider", ("responseProvider", "response_provider")),
            ):
                value = _identifier(_pick(message, *aliases))
                if value:
                    self.metadata[key] = value
            content = message.get("content")
            self.final_text = None
            if isinstance(content, list):
                tool_calls = any(isinstance(block, dict) and block.get("type") == "toolCall"
                                 for block in content)
                if not tool_calls and reason != "toolUse":
                    blocks = [block for block in content
                              if isinstance(block, dict) and block.get("type") == "text"
                              and isinstance(block.get("text"), str)]
                    final_blocks = []
                    has_phases = False
                    for block in blocks:
                        signature = _pick(block, "textSignature", "text_signature")
                        try:
                            parsed = _strict_json(signature) if isinstance(signature, str) else None
                        except (ValueError, RecursionError):
                            parsed = None
                        phase = parsed.get("phase") if isinstance(parsed, dict) else None
                        if phase in {"commentary", "final_answer"}:
                            has_phases = True
                        if phase == "final_answer":
                            final_blocks.append(block)
                    # OpenAI Responses may place commentary and final blocks in
                    # one message. Its explicit phase is authoritative when present.
                    selected = final_blocks if has_phases else blocks
                    self.final_text = "".join(block["text"] for block in selected)
        elif kind in {"tool_execution_start", "tool_execution_end"}:
            identifier = _event_identifier(_pick(event, "toolCallId", "tool_call_id"))
            if identifier is None:
                self.protocol_error = True
                return
            name = _identifier(_pick(event, "toolName", "tool_name"))
            fields = {"name": name} if name else {}
            if kind.endswith("end"):
                fields["status"] = "error" if _pick(event, "isError", "is_error") is True else "success"
            self.emit("tool_start" if kind.endswith("start") else "tool_end",
                      identifier, timestamp, **fields)

    def _codex(self, event: dict, timestamp: int) -> None:
        kind = event["type"]
        if kind == "thread.started":
            identifier = _identifier(event.get("thread_id"))
            if identifier:
                self.metadata["session_id"] = identifier
        elif kind == "turn.started":
            self._turn_number += 1
            self.completed = False
            self.final_text = None
        elif kind == "turn.completed":
            self.usages[f"turn-{self._turn_number}"] = _usage(event.get("usage"), codex=True)
            self.completed = True
        elif kind in {"turn.failed", "error"}:
            self.harness_error = True
        elif kind in {"item.started", "item.completed"}:
            item = event.get("item")
            if not isinstance(item, dict):
                self.protocol_error = True
                return
            item_type = item.get("type")
            if item_type == "agent_message" and kind == "item.completed":
                self.final_text = item.get("text") if isinstance(item.get("text"), str) else None
            elif item_type in {"command_execution", "mcp_tool_call", "collab_tool_call", "web_search", "file_change"}:
                identifier = _event_identifier(item.get("id"))
                if identifier is None:
                    self.protocol_error = True
                    return
                name = _identifier(item.get("tool")) or item_type
                fields = {"name": name}
                if kind == "item.completed":
                    failed = item.get("status") in {"failed", "declined"}
                    if item_type == "command_execution":
                        failed = failed or item.get("exit_code") not in (None, 0)
                    fields["status"] = "error" if failed else "success"
                self.emit("tool_start" if kind == "item.started" else "tool_end",
                          identifier, timestamp, **fields)
            # Codex exec aggregates model usage at turn completion. Its message
            # items are not LLM request boundaries; do not fabricate LLM spans.

    def result(self, *, status="success", error=None) -> HarnessResult:
        totals = {}
        for key in _USAGE_KEYS:
            values = [usage[key] for usage in self.usages.values()]
            totals[key] = sum(values) if values and all(value is not None for value in values) else None
        return HarnessResult(status=status, error=error, events=self.events,
                             usage=totals, metadata=self.metadata)

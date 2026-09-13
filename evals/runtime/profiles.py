"""Load pinned or custom harness profiles and resolve command placeholders."""

import json
from pathlib import Path
import re


DEFAULT_IMAGE = "doc-intell-harnesses:pi-0.85.1_tau-0.4.3_codex-0.145.0"
PROFILE_DIR = Path(__file__).resolve().parents[2] / "harnesses"
OUTPUT_MODES = {"pi-jsonl", "tau-jsonl", "codex-jsonl", "json"}
TELEMETRY_MODES = {"events", "native-otel", "none"}


def load_profile(name_or_path, model=None, thinking=None) -> dict:
    """Load a builtin name or explicit JSON path; resolve command placeholders."""
    candidate = Path(name_or_path).expanduser()
    path = candidate if candidate.is_file() else PROFILE_DIR / f"{name_or_path}.json"
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("Harness profile was not found or is not valid JSON") from None
    if not isinstance(profile, dict):
        raise ValueError("Harness profile must be an object")
    for key in ("name", "model", "provider", "version"):
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            raise ValueError(f"Harness profile requires a nonempty {key}")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", profile["name"]):
        raise ValueError("Harness profile name may only contain letters, numbers, dots, dashes, underscores")
    if profile.get("output_mode") not in OUTPUT_MODES:
        raise ValueError("Harness profile has an unsupported output_mode")
    if profile.get("telemetry", "none") not in TELEMETRY_MODES:
        raise ValueError("Harness profile has an unsupported telemetry mode")
    profile.setdefault("telemetry", "none")
    profile.setdefault("auth", "none")
    if profile["auth"] not in {"codex-account", "none"}:
        raise ValueError("Harness profile auth must be codex-account or none")
    if profile["auth"] == "codex-account" and profile["name"] not in {"pi", "tau", "codex"}:
        raise ValueError("The Codex account bridge supports only pi, tau, and codex")
    for key, override in (("model", model), ("thinking", thinking)):
        if override is not None:
            if not isinstance(override, str) or not override.strip() or "\0" in override:
                raise ValueError(f"Harness {key} must be nonempty text")
            profile[key] = override
    profile.setdefault("thinking", "medium")
    argv = profile.get("command")
    if not isinstance(argv, list) or not argv or any(
        not isinstance(arg, str) or "\0" in arg for arg in argv
    ) or not argv[0]:
        raise ValueError("Harness profile command must be a nonempty argument array")
    fields = {name: profile[name] for name in ("model", "thinking", "provider")}
    try:
        profile["command"] = [arg.format_map(fields) for arg in argv]
    except (KeyError, ValueError):
        raise ValueError("Command placeholders may only reference model, thinking, provider") from None
    forwarded = profile.get("forward_env", [])
    if not isinstance(forwarded, list) or any(
        not isinstance(name, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name)
        for name in forwarded
    ):
        raise ValueError("forward_env must contain environment variable names")
    # The runner owns isolation and trace identity/destination. Importing host
    # OTel settings could silently drop spans or detach them from the task.
    protected = {"HOME", "PATH", "CODEX_HOME", "PI_CODING_AGENT_DIR", "LD_PRELOAD", "PYTHONPATH", "NODE_OPTIONS", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "NODE_USE_ENV_PROXY", "TRACEPARENT", "TRACESTATE", "BAGGAGE"}
    if protected.intersection(forwarded) or any(
        name.startswith(("DOC_INTELL_", "OTEL_")) for name in forwarded
    ):
        raise ValueError("forward_env cannot override the isolated runtime configuration")
    return profile

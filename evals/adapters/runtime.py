"""Pinned CLI profiles and disposable document-only Docker workspaces.

The runner owns prompts and evaluation. This module only prepares transport,
native account authentication, and the filesystem presented to the harness.
"""

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import time
from uuid import uuid4

from evals.contracts import HarnessInvocation, ProcessSpec
from evals.adapters.network import restricted_network


DEFAULT_IMAGE = "doc-intell-harnesses:pi-0.85.1_tau-0.4.3_codex-0.145.0"
PROFILE_DIR = Path(__file__).resolve().parents[2] / "harnesses"
OUTPUT_MODES = {"pi-jsonl", "tau-jsonl", "codex-jsonl", "json"}
TELEMETRY_MODES = {"events", "native-otel", "none"}
MIN_AUTH_VALIDITY_SECONDS = 900


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


def _codex_auth_path() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"


def _read_account_seed() -> dict:
    """Read only the current access credential; never export the refresh secret."""
    try:
        auth = json.loads(_codex_auth_path().read_text(encoding="utf-8"))
        tokens = auth["tokens"]
        access = tokens["access_token"]
        part = access.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        expires = claims["exp"]
        account = tokens.get("account_id") or claims["https://api.openai.com/auth"]["chatgpt_account_id"]
        if not isinstance(access, str) or not isinstance(account, str) or not account:
            raise ValueError
        if isinstance(expires, bool) or not isinstance(expires, (int, float)):
            raise ValueError
        if expires - time.time() < MIN_AUTH_VALIDITY_SECONDS:
            raise TimeoutError
    except TimeoutError:
        raise ValueError("Codex account access expires in under 15 minutes; refresh your Codex login before running") from None
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        raise ValueError("A valid existing Codex ChatGPT account login is required; run codex login first") from None
    return {
        "access_token": access,
        "id_token": tokens.get("id_token", ""),
        "account_id": account,
        "expires": int(expires * 1000),
        "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _docker_command(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Docker could not complete the preflight check") from None


def _image_info(docker: str, image: str, profile: dict) -> dict:
    result = _docker_command([docker, "image", "inspect", image])
    if result.returncode:
        raise ValueError(f"Harness image is unavailable: build {image} using containers/harnesses.Dockerfile")
    try:
        info = json.loads(result.stdout)[0]
        image_id = info["Id"]
        labels = info.get("Config", {}).get("Labels") or {}
        if profile.get("auth") == "codex-account":
            label = f"org.doc-intell.{profile['name']}.version"
            if labels.get(label) != profile["version"]:
                raise ValueError("Harness image version does not match the selected profile")
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise ValueError("Docker returned invalid image metadata") from None
    return {"image": image, "image_id": image_id}


def preflight(profile: dict, *, image=DEFAULT_IMAGE, execution="docker") -> dict:
    """Check local prerequisites without a provider request or exposing secrets."""
    if execution != "docker":
        raise ValueError("Native profiles require Docker; use the explicit legacy command mode for host execution")
    docker = shutil.which("docker")
    if not docker:
        raise ValueError("Docker CLI is required for native harness profiles")
    result = _docker_command([docker, "version", "--format", "{{.Server.Version}}"])
    if result.returncode:
        raise ValueError("Docker engine is unavailable; start Docker and retry")
    metadata = _image_info(docker, image, profile)
    if profile.get("auth") == "codex-account":
        _read_account_seed()
    missing = [name for name in profile.get("forward_env", []) if not os.environ.get(name)]
    if missing:
        raise ValueError("Missing profile environment variables: " + ", ".join(missing))
    if profile.get("auth") == "none":
        # Inspect availability without invoking a custom harness, mounting its
        # credentials, forwarding provider secrets, or permitting network access.
        container = "doc-intell-check-" + uuid4().hex
        try:
            command_check = _docker_command([
                docker, "run", "--rm", "--name", container,
                "--network", "none", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
                "--workdir", "/workspace", "--entrypoint", "python3",
                metadata["image_id"], "-c",
                "import shutil,sys; sys.exit(0 if shutil.which(sys.argv[1]) else 3)",
                profile["command"][0],
            ])
        finally:
            try:
                subprocess.run([docker, "rm", "-f", container], capture_output=True, timeout=15, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if command_check.returncode:
            raise ValueError("Harness executable is unavailable in the selected image; install it before running")
        metadata["command_available"] = True
    metadata.update({
        **{key: profile[key] for key in ("name", "version", "model", "provider", "thinking", "output_mode", "telemetry")},
        "execution": "docker", "filesystem_isolated": True,
        "evaluator_network_isolated": True, "model_access": "not_tested",
        "auth": profile.get("auth", "none"),
        "auth_refresh_exported": False,
    })
    return metadata


def _document_mounts(invocation: HarnessInvocation) -> list[str]:
    dataset = invocation.dataset.resolve()
    inputs = (dataset / "inputs").resolve()
    mounts = []
    destinations = set()
    for document in invocation.documents:
        relative = PurePosixPath(document["path"])
        if not relative.parts or relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "inputs":
            raise ValueError("Harness documents must be relative paths under dataset/inputs")
        source = (dataset / str(relative)).resolve()
        if not source.is_file() or not source.is_relative_to(inputs) or source.suffix.lower() != ".pdf":
            raise ValueError("Only assigned PDF files within dataset/inputs may be mounted")
        if "," in str(source) or "," in str(relative):
            raise ValueError("Document paths cannot contain Docker mount separators")
        destination = f"/workspace/{relative}"
        if destination in destinations:
            raise ValueError("Duplicate harness document destination")
        destinations.add(destination)
        mounts.extend(["--mount", f"type=bind,src={source},dst={destination},readonly"])
    return mounts


@contextmanager
def prepare_invocation(profile: dict, invocation: HarnessInvocation, *, image=DEFAULT_IMAGE, execution="docker", phoenix_url="http://127.0.0.1:6006"):
    """Yield a fresh native CLI, then forcibly remove its container on any exit."""
    if execution != "docker":
        raise ValueError("Native profiles require Docker")
    docker = shutil.which("docker")
    if not docker:
        raise ValueError("Docker CLI is required for native harness profiles")
    mounts = _document_mounts(invocation)
    image_metadata = _image_info(docker, image, profile)
    name = "doc-intell-" + uuid4().hex
    with restricted_network(image_metadata["image_id"], profile.get("allowed_hosts"), phoenix_url=phoenix_url) as egress, tempfile.TemporaryDirectory(prefix="doc-intell-auth-") as temporary:
        argv = [
            docker, "run", "--rm", "-i", "--init", "--name", name,
            "--network", egress["network"],
            "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=256", "--memory=4g", "--cpus=2",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--tmpfs", "/workspace:rw,nosuid,nodev,mode=1777,size=512m",
            "--tmpfs", "/home/agent:rw,nosuid,nodev,mode=1777,size=128m",
            "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777,size=512m",
            "--workdir", "/workspace", "--env", "HOME=/home/agent",
            "--env", "CODEX_HOME=/home/agent/.codex",
            "--env", "PI_CODING_AGENT_DIR=/home/agent/.pi/agent",
            "--env", f"DOC_INTELL_HARNESS={profile['name']}",
            "--env", f"HTTPS_PROXY={egress['proxy_url']}",
            "--env", f"HTTP_PROXY={egress['proxy_url']}",
            "--env", f"https_proxy={egress['proxy_url']}",
            "--env", f"http_proxy={egress['proxy_url']}",
            "--env", "NO_PROXY=localhost,127.0.0.1",
            "--env", "NODE_USE_ENV_PROXY=1",
            "--env", f"TRACEPARENT=00-{invocation.trace_id}-{invocation.parent_span_id}-01",
            "--env", f"DOC_INTELL_RUN_ID={invocation.run_id}",
            "--env", f"DOC_INTELL_TASK_ID={invocation.task_id}",
            "--env", f"DOC_INTELL_REPETITION={invocation.repetition}",
            "--env", (f"OTEL_RESOURCE_ATTRIBUTES=benchmark.run_id={invocation.run_id},"
                      f"benchmark.task_id={invocation.task_id},benchmark.repetition={invocation.repetition},"
                      f"benchmark.harness={profile['name']},openinference.project.name=doc-intell-poc"),
            *mounts,
        ]
        if profile.get("telemetry") == "native-otel":
            argv.extend(["--env", f"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT={egress['proxy_url']}/v1/traces",
                         "--env", "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf"])
        if profile.get("auth") == "codex-account":
            seed = Path(temporary) / "account.json"
            fd = os.open(seed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(_read_account_seed(), handle)
            argv.extend(["--mount", f"type=bind,src={seed},dst=/run/harness-account.json,readonly"])
        for variable in profile.get("forward_env", []):
            # Docker resolves the value from its own environment; secrets never enter argv.
            argv.extend(["--env", variable])
        argv.extend([image_metadata["image_id"], *profile["command"]])
        try:
            yield ProcessSpec(
                argv=tuple(argv),
                metadata={
                    **image_metadata, "execution": "docker", "filesystem_isolated": True,
                    "evaluator_network_isolated": True, "auth_refresh_exported": False,
                },
            )
        finally:
            # Killing only the Docker client does not guarantee its worker has stopped.
            try:
                subprocess.run([docker, "rm", "-f", name], capture_output=True, timeout=15, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass


def make_preparer(profile: dict, *, image=DEFAULT_IMAGE, execution="docker", phoenix_url="http://127.0.0.1:6006"):
    """Return the context-manager factory consumed by NativeHarness."""
    def prepare(invocation):
        return prepare_invocation(profile, invocation, image=image, execution=execution, phoenix_url=phoenix_url)
    return prepare

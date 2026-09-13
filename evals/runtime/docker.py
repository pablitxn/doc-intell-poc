"""Check Docker and prepare disposable workspaces containing assigned inputs."""

from contextlib import contextmanager
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
from uuid import uuid4

from evals.contracts import HarnessInvocation, ProcessSpec
from .account import read_account_seed
from .network import restricted_network
from .profiles import DEFAULT_IMAGE


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
        read_account_seed()
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
        if (not source.is_file() or not source.is_relative_to(inputs)
                or source.suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png", ".json"}):
            raise ValueError("Only assigned PDF, JPEG, PNG or JSON files within dataset/inputs may be mounted")
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
                json.dump(read_account_seed(), handle)
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

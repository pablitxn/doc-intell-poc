"""Disposable Phoenix for opt-in integration tests; never uses saved history."""

from contextlib import contextmanager
import json
import subprocess
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4


PHOENIX_TEST_IMAGE = "arizephoenix/phoenix:version-20.11.0"


@contextmanager
def temporary_phoenix():
    """Yield an empty localhost origin and remove only its owned container."""
    name = "doc-intell-phoenix-test-" + uuid4().hex[:12]
    try:
        result = subprocess.run([
            "docker", "run", "--detach", "--rm", "--pull", "never", "--name", name,
            "--publish", "127.0.0.1::6006", PHOENIX_TEST_IMAGE,
        ], capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError("Could not start the temporary Phoenix image; install the pinned image first")
        inspected = subprocess.run([
            "docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}", name,
        ], capture_output=True, text=True, check=True, timeout=15)
        port = json.loads(inspected.stdout)["6006/tcp"][0]["HostPort"]
        origin = f"http://127.0.0.1:{int(port)}"
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with opener.open(origin + "/readyz", timeout=2) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                time.sleep(0.25)
        else:
            raise RuntimeError("Temporary Phoenix did not become ready within 60 seconds")
        yield origin
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15, check=False)

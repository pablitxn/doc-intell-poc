import base64
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from evals.adapters.runtime import (
    DEFAULT_IMAGE, _read_account_seed, load_profile, make_preparer, preflight,
)
from evals.contracts import HarnessInvocation


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.dataset = self.root / "dataset"
        (self.dataset / "inputs").mkdir(parents=True)
        (self.dataset / "inputs/doc.pdf").write_bytes(b"%PDF-test")
        (self.dataset / "ground_truth").mkdir()
        (self.dataset / "ground_truth/expected.json").write_text('{"answer": 42}')
        body = base64.urlsafe_b64encode(json.dumps({
            "exp": time.time() + 3600,
            "https://api.openai.com/auth": {"chatgpt_account_id": "account-test"},
        }).encode()).decode().rstrip("=")
        self.access = "header." + body + ".signature-secret"
        self.auth = self.root / "auth.json"
        self.auth.write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {
            "access_token": self.access, "refresh_token": "refresh-secret-never-export",
            "id_token": "id-secret", "account_id": "account-test",
        }}))
        self.invocation = HarnessInvocation(
            input_text="Read /workspace/inputs/doc.pdf", task_id="extract", repetition=1,
            dataset=self.dataset, documents=({"path": "inputs/doc.pdf"},),
            artifact_dir=self.root / "reports", trace_id="1" * 32, parent_span_id="2" * 16,
        )
        self.labels = {f"org.doc-intell.{name}.version": version for name, version in
                       (("pi", "0.85.1"), ("tau", "0.4.3"), ("codex", "0.145.0"))}

    def docker_result(self, argv, **kwargs):
        if "inspect" in argv:
            stdout = json.dumps([{"Id": "sha256:test-image", "Config": {"Labels": self.labels}}])
        else:
            stdout = "29.0.0"
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    @contextmanager
    def runtime(self):
        with patch("evals.adapters.runtime.shutil.which", return_value="/usr/bin/docker"), \
             patch("evals.adapters.runtime.subprocess.run", side_effect=self.docker_result) as run, \
             patch("evals.adapters.runtime._codex_auth_path", return_value=self.auth), \
             patch("evals.adapters.runtime.restricted_network") as network:
            network.return_value.__enter__.return_value = {"network": "internal-test", "proxy_url": "http://egress:8080"}
            yield run

    def test_profiles_pin_native_cli_and_resolve_settings(self):
        for name in ("pi", "tau", "codex"):
            profile = load_profile(name, model="gpt-5.5", thinking="high")
            self.assertIn("gpt-5.5", profile["command"])
            self.assertEqual(profile["provider"], "openai-codex")
            self.assertEqual(profile["telemetry"], "events")
            self.assertEqual(profile["thinking"], "high")
            self.assertNotIn("latest", profile["version"])
            self.assertNotIn("{", " ".join(profile["command"]))
        self.assertIn('model_reasoning_effort="high"', load_profile("codex", thinking="high")["command"])

    def test_requested_luna_sol_terra_slugs_are_preserved_for_every_harness(self):
        for name in ("pi", "tau", "codex"):
            self.assertEqual(load_profile(name)["model"], "gpt-5.6-sol")
            self.assertEqual(load_profile(name)["thinking"], "medium")
            for model in ("gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"):
                with self.subTest(harness=name, model=model):
                    profile = load_profile(name, model=model, thinking="medium")
                    self.assertEqual(profile["model"], model)
                    self.assertEqual(profile["provider"], "openai-codex")
                    command = profile["command"]
                    self.assertEqual(command[command.index("--model") + 1], model)
                    if name == "codex":
                        self.assertIn('model_reasoning_effort="medium"', command)
                    else:
                        self.assertEqual(command[command.index("--thinking") + 1], "medium")

    def test_corporate_profile_accepts_native_otel_without_event_stream(self):
        profile = load_profile("corporate.example")
        self.assertEqual(profile["output_mode"], "json")
        self.assertEqual(profile["telemetry"], "native-otel")
        self.assertEqual(profile["auth"], "none")

    def test_forwarded_host_environment_cannot_replace_trace_identity_or_exporter(self):
        profile = load_profile("corporate.example")
        destination = self.root / "corporate.json"
        reserved = (
            "TRACEPARENT", "TRACESTATE", "BAGGAGE", "DOC_INTELL_RUN_ID",
            "DOC_INTELL_TASK_ID", "DOC_INTELL_REPETITION", "DOC_INTELL_HARNESS",
            "DOC_INTELL_FUTURE_CONTEXT", "OTEL_RESOURCE_ATTRIBUTES",
            "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_TRACES_SAMPLER", "OTEL_SDK_DISABLED",
        )
        for variable in reserved:
            with self.subTest(variable=variable):
                destination.write_text(json.dumps({**profile, "forward_env": [variable]}))
                with self.assertRaisesRegex(ValueError, "cannot override"):
                    load_profile(destination)
        destination.write_text(json.dumps({**profile, "forward_env": ["CORPORATE_PROVIDER_KEY"]}))
        self.assertEqual(load_profile(destination)["forward_env"], ["CORPORATE_PROVIDER_KEY"])

    def test_corporate_preflight_checks_executable_without_running_harness_or_forwarding_secrets(self):
        profile = load_profile("corporate.example")
        profile["command"] = ["corporate-harness", "--provider-key", "argument-secret-sentinel"]
        profile["forward_env"] = ["CORPORATE_PROVIDER_KEY"]
        with self.runtime() as run, patch.dict(os.environ, {"CORPORATE_PROVIDER_KEY": "env-secret-sentinel"}):
            metadata = preflight(profile)
        launch = next(call.args[0] for call in run.call_args_list if call.args[0][1] == "run")
        self.assertEqual(launch[launch.index("--network") + 1], "none")
        self.assertEqual(launch[launch.index("--entrypoint") + 1], "python3")
        self.assertIn("--read-only", launch)
        self.assertIn("sha256:test-image", launch)
        self.assertIn("shutil.which", launch[-2])
        self.assertEqual(launch[-1], "corporate-harness")
        self.assertNotIn("--env", launch)
        self.assertNotIn("--mount", launch)
        self.assertNotIn("secret-sentinel", repr(launch))
        self.assertTrue(metadata["command_available"])
        self.assertEqual(metadata["model_access"], "not_tested")
        self.assertEqual(run.call_args.args[0][1:3], ["rm", "-f"])

    def test_corporate_preflight_rejects_missing_binary_and_discards_process_output(self):
        def result(argv, **kwargs):
            if argv[1] == "run":
                return subprocess.CompletedProcess(argv, 3, "private-output-sentinel", "private-output-sentinel")
            return self.docker_result(argv, **kwargs)

        with self.runtime() as run:
            run.side_effect = result
            with self.assertRaisesRegex(ValueError, "executable is unavailable") as raised:
                preflight(load_profile("corporate.example"))
        self.assertNotIn("private-output-sentinel", str(raised.exception))
        self.assertEqual(run.call_args.args[0][1:3], ["rm", "-f"])

    def test_preparer_passes_configured_phoenix_origin_only_to_sidecar(self):
        profile = load_profile("corporate.example")
        with self.runtime(), patch("evals.adapters.runtime.restricted_network") as network:
            network.return_value.__enter__.return_value = {"network": "internal-test", "proxy_url": "http://egress:8080"}
            with make_preparer(profile, phoenix_url="https://phoenix.corp.example:8443")(self.invocation) as spec:
                network.assert_called_once_with("sha256:test-image", None, phoenix_url="https://phoenix.corp.example:8443")
                self.assertIn("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://egress:8080/v1/traces", spec.argv)
                self.assertNotIn("phoenix.corp.example", repr(spec.argv))

    def test_seed_excludes_refresh_and_host_config_and_auth_is_unchanged(self):
        before = self.auth.read_bytes()
        with self.runtime():
            seed = _read_account_seed()
            self.assertEqual(seed["access_token"], self.access)
            self.assertNotIn("refresh-secret-never-export", json.dumps(seed))
            self.assertNotIn("refresh_token", seed)
        self.assertEqual(before, self.auth.read_bytes())

    def test_only_assigned_documents_mounted_no_repo_ground_truth_or_artifacts(self):
        with self.runtime() as run:
            with make_preparer(load_profile("pi"))(self.invocation) as spec:
                argv = spec.argv
                mounts = [argv[i + 1] for i, value in enumerate(argv) if value == "--mount"]
                self.assertEqual(len(mounts), 2)  # one assigned PDF and minimal auth seed
                self.assertTrue(any("dst=/workspace/inputs/doc.pdf,readonly" in item for item in mounts))
                self.assertFalse(any("ground_truth" in item or "reports" in item or "docker.sock" in item for item in mounts))
                self.assertIn("--read-only", argv)
                self.assertEqual(argv[argv.index("--network") + 1], "internal-test")
                self.assertIn("HTTPS_PROXY=http://egress:8080", argv)
                self.assertIn("--cap-drop=ALL", argv)
                self.assertIn("sha256:test-image", argv)
                self.assertNotIn(self.access, repr(spec))
                self.assertNotIn("refresh-secret-never-export", repr(spec))
                auth_mount = next(item for item in mounts if "harness-account.json" in item)
                seed_path = Path(auth_mount.split("src=", 1)[1].split(",", 1)[0])
                self.assertEqual(seed_path.stat().st_mode & 0o777, 0o600)
                self.assertNotIn("refresh-secret-never-export", seed_path.read_text())
                self.assertNotIn("refresh_token", seed_path.read_text())
            self.assertFalse(seed_path.exists())
            self.assertEqual(run.call_args.args[0][1:3], ["rm", "-f"])

    def test_timeout_cleans_container_and_temporary_auth(self):
        with self.runtime() as run:
            with self.assertRaises(TimeoutError):
                with make_preparer(load_profile("tau"))(self.invocation) as spec:
                    argv = spec.argv
                    container_name = argv[argv.index("--name") + 1]
                    raise TimeoutError("test timeout")
            self.assertEqual(run.call_args.args[0], ["/usr/bin/docker", "rm", "-f", container_name])

    def test_escape_and_symlink_documents_rejected_before_launch(self):
        link = self.dataset / "inputs/leak.pdf"
        link.symlink_to(self.dataset / "ground_truth/expected.json")
        for document in ("../ground_truth/expected.json", "inputs/leak.pdf", "/etc/passwd"):
            invocation = HarnessInvocation(**{**self.invocation.__dict__, "documents": ({"path": document},)})
            with self.runtime() as run, self.assertRaises(ValueError):
                with make_preparer(load_profile("pi"))(invocation):
                    self.fail("Invalid document was accepted")
            run.assert_not_called()

    def test_only_assigned_mixed_format_inputs_are_mounted_readonly(self):
        paths = ["inputs/nested/document" + suffix for suffix in (".pdf", ".jpg", ".jpeg", ".png", ".json")]
        (self.dataset / "inputs/nested").mkdir()
        for name in paths:
            (self.dataset / name).write_bytes(b"input-fixture")
        (self.dataset / "inputs/unassigned.json").write_text('{"unassigned":true}')
        invocation = HarnessInvocation(**{**self.invocation.__dict__,
            "documents": tuple({"path": name} for name in paths)})
        profile = {**load_profile("pi"), "auth": "none"}
        with self.runtime(), make_preparer(profile)(invocation) as spec:
            mounts = [spec.argv[index + 1] for index, arg in enumerate(spec.argv) if arg == "--mount"]
        self.assertEqual(len(mounts), len(paths))
        for name, mount in zip(paths, mounts):
            self.assertEqual(mount, f"type=bind,src={(self.dataset / name).resolve()},dst=/workspace/{name},readonly")
        self.assertNotIn("unassigned.json", repr(mounts))
        self.assertNotIn("ground_truth", repr(mounts))
        self.assertNotIn("expected.json", repr(mounts))

    def test_new_formats_cannot_mount_references_symlinks_or_unsupported_files(self):
        link = self.dataset / "inputs/leak.json"
        link.symlink_to(self.dataset / "ground_truth/expected.json")
        (self.dataset / "inputs/script.py").write_text("print('not an input document')")
        for name in ("inputs/leak.json", "inputs/../ground_truth/expected.json",
                     "ground_truth/expected.json", "inputs/script.py", "inputs/nested,readonly.json"):
            with self.subTest(path=name), self.runtime() as run:
                invocation = HarnessInvocation(**{**self.invocation.__dict__, "documents": ({"path": name},)})
                with self.assertRaises(ValueError), make_preparer(load_profile("pi"))(invocation):
                    self.fail("Invalid input document was mounted")
                run.assert_not_called()

    def test_fresh_container_name_for_each_invocation(self):
        names = []
        with self.runtime():
            for _ in range(2):
                with make_preparer(load_profile("codex"))(self.invocation) as spec:
                    names.append(spec.argv[spec.argv.index("--name") + 1])
        self.assertNotEqual(names[0], names[1])

    def test_preflight_checks_version_and_auth_without_paid_call(self):
        with self.runtime() as run:
            metadata = preflight(load_profile("codex"))
        self.assertEqual(metadata["image"], DEFAULT_IMAGE)
        self.assertEqual(metadata["model_access"], "not_tested")
        self.assertFalse(metadata["auth_refresh_exported"])
        self.assertEqual(run.call_count, 2)
        self.assertNotIn(self.access, repr(metadata))

    def test_preflight_rejects_wrong_image_version(self):
        self.labels["org.doc-intell.pi.version"] = "999.0.0"
        with self.runtime(), self.assertRaisesRegex(ValueError, "version does not match"):
            preflight(load_profile("pi"))

    def test_expired_auth_error_never_contains_credentials(self):
        body = base64.urlsafe_b64encode(json.dumps({"exp": time.time() - 1}).encode()).decode().rstrip("=")
        self.auth.write_text(json.dumps({"tokens": {"access_token": f"h.{body}.secret", "account_id": "account-test"}}))
        with self.runtime(), self.assertRaisesRegex(ValueError, "refresh your Codex login") as raised:
            preflight(load_profile("tau"))
        self.assertNotIn("secret", str(raised.exception))

    def test_host_execution_requires_explicit_legacy_path(self):
        with self.assertRaisesRegex(ValueError, "legacy"):
            preflight(load_profile("codex"), execution="host")

    def test_entrypoint_native_schemas_do_not_need_refresh_secret(self):
        script = Path(__file__).resolve().parents[1] / "containers/entrypoint.py"
        spec = importlib.util.spec_from_file_location("harness_entrypoint_test", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.runtime():
            seed = _read_account_seed()
        module.seed_account(seed, "pi", self.root / "pi-home")
        pi_auth = json.loads((self.root / "pi-home/.pi/agent/auth.json").read_text())
        self.assertEqual(pi_auth["openai-codex"]["refresh"], "")
        self.assertEqual(pi_auth["openai-codex"]["accountId"], "account-test")
        with patch.dict(os.environ, {}, clear=True):
            module.seed_account(seed, "tau", self.root / "tau-home")
            self.assertEqual(os.environ["OPENAI_CODEX_ACCESS_TOKEN"], self.access)
        module.seed_account(seed, "codex", self.root / "codex-home")
        codex_auth = json.loads((self.root / "codex-home/.codex/auth.json").read_text())
        self.assertEqual(codex_auth["tokens"]["refresh_token"], "")
        self.assertEqual(codex_auth["auth_mode"], "chatgpt")


if __name__ == "__main__":
    unittest.main()

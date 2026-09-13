"""Machine checks must not invoke models or confuse transport with model access."""

from contextlib import contextmanager, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from evals import diagnostics
from evals.adapters.runtime import load_profile
from evals.contracts import ProcessSpec
import run


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'datasets/tax-mini-poc'


def arguments(**overrides):
    return SimpleNamespace(**{
        'harness': 'pi', 'profile': None, 'model': None, 'models': None,
        'thinking': None, 'image': None, 'dataset': DATASET, 'timeout': 30,
        'phoenix_url': 'http://localhost:6006', 'check_network': False, **overrides})


class DiagnosticTests(unittest.TestCase):
    @contextmanager
    def probes(self, *, network=False):
        worker = {'checks': {'documents_readable': True, 'references_hidden': True, 'pdf_tools': True},
                  'network': [], 'python': 'test-python'}
        if network:
            worker['checks'].update(provider_tls_routes=True, phoenix_otlp_transport=True)
        with patch.object(diagnostics, 'preflight', return_value={'image_id': 'sha256:test'}) as preflight, \
             patch.object(diagnostics, '_image_details', return_value={
                 'os': 'linux', 'architecture': 'arm64', 'version_verified_by_label': True}), \
             patch.object(diagnostics, '_worker_probe', return_value=worker) as probe, \
             patch.object(diagnostics, '_phoenix_ready', return_value=True) as ready, \
             patch('evals.adapters.native.NativeHarness.invoke') as invoke:
            yield preflight, probe, ready, invoke

    def test_local_checks_report_scope_and_never_invoke_harness(self):
        with self.probes() as (preflight, worker, ready, invoke):
            result = diagnostics.diagnose(arguments())
        self.assertTrue(result['ready'])
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['model_access'], 'not_tested')
        self.assertEqual(result['dataset']['tasks'], 6)
        self.assertEqual(result['dataset']['fields'], 54)
        self.assertEqual(len(worker.call_args.args[2]), 5)
        self.assertFalse(worker.call_args.args[-2])
        preflight.assert_called_once()
        ready.assert_not_called()
        invoke.assert_not_called()

    def test_invalid_dataset_fails_before_runtime_or_network(self):
        with self.probes() as (preflight, worker, ready, invoke):
            result = diagnostics.diagnose(arguments(dataset=DATASET / 'missing'))
        self.assertFalse(result['ready'])
        for call in (preflight, worker, ready, invoke):
            call.assert_not_called()

    def test_unfilled_corporate_profile_does_not_appear_ready(self):
        with self.probes() as (preflight, worker, _, invoke):
            result = diagnostics.diagnose(arguments(harness=None, profile=ROOT / 'harnesses/corporate.example.json'))
        self.assertFalse(result['ready'])
        self.assertIn('placeholders', result['harnesses'][0]['issue'])
        preflight.assert_not_called()
        worker.assert_not_called()
        invoke.assert_not_called()

    def test_network_failure_is_visible_without_model_call(self):
        with self.probes(network=True) as (_, worker, ready, invoke):
            ready.side_effect = OSError('private-proxy-diagnostic')
            worker.return_value['checks']['provider_tls_routes'] = False
            result = diagnostics.diagnose(arguments(check_network=True))
        self.assertFalse(result['ready'])
        self.assertFalse(result['checks']['phoenix_runner'])
        self.assertNotIn('private-proxy-diagnostic', json.dumps(result))
        self.assertTrue(worker.call_args.args[-2])
        invoke.assert_not_called()

    def test_worker_diagnostic_drops_provider_credentials(self):
        profile = {**load_profile('pi'), 'forward_env': ['CORPORATE_SECRET']}
        @contextmanager
        def prepare(invocation):
            yield ProcessSpec(('docker', 'run', '--rm', 'image', 'python3', '-c', 'probe'))
        with patch.object(diagnostics, 'make_preparer', return_value=prepare) as factory, \
             patch.object(diagnostics.subprocess, 'run', return_value=subprocess.CompletedProcess(
                 [], 0, '{"checks":{},"network":[],"python":"test"}')) as execute:
            diagnostics._worker_probe(profile, DATASET, [], 'image', 'http://localhost:6006', False, 20)
        sanitized = factory.call_args.args[0]
        self.assertEqual(sanitized['auth'], 'none')
        self.assertEqual(sanitized['forward_env'], [])
        self.assertEqual(sanitized['command'][0], 'python3')
        self.assertNotIn('CORPORATE_SECRET', execute.call_args.kwargs['input'])
        self.assertEqual(execute.call_args.args[0],
                         ['docker', 'run', '--rm', '--entrypoint', 'python3', 'image', '-c', 'probe'])

    def test_phoenix_readiness_does_not_follow_redirects_with_credentials(self):
        observed = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                observed.append(self.path)
                self.send_response(302)
                self.send_header('Location', '/redirected')
                self.end_headers()
            def log_message(self, *args):
                pass
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.dict('os.environ', {'PHOENIX_API_KEY': 'credential-sentinel'}):
                    self.assertFalse(diagnostics._phoenix_ready(f'http://127.0.0.1:{server.server_port}'))
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual(observed, ['/readyz'])

    def test_unverified_image_version_is_explicit(self):
        with self.probes(), patch.object(diagnostics, '_image_details', return_value={
                'os': 'linux', 'architecture': 'amd64', 'version_verified_by_label': False}):
            result = diagnostics.diagnose(arguments())
        self.assertTrue(result['ready'])
        self.assertIn('declared only', result['harnesses'][0]['warnings'][0])

    def test_check_entrypoint_stops_before_harness_or_phoenix_publication(self):
        for ready in (True, False):
            with self.subTest(ready=ready), patch('sys.argv', ['run.py', '--harness', 'pi', '--check']), \
                 patch.object(diagnostics, 'diagnose', return_value={'ready': ready}), \
                 patch.object(run, 'native_adapters') as native, \
                 patch.object(run, 'prepare_dataset') as dataset, \
                 redirect_stdout(StringIO()):
                code = run.main()
            self.assertEqual(code, 0 if ready else 1)
            native.assert_not_called()
            dataset.assert_not_called()


if __name__ == '__main__':
    unittest.main()

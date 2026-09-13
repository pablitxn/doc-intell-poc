"""Explicit Docker conformance checks; no model or provider request is made."""

import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from evals.adapters.native import NativeHarness
from evals.adapters.runtime import DEFAULT_IMAGE, make_preparer
from evals.contracts import HarnessInvocation
from evals.datasets.loader import load_examples

DATASET = Path(__file__).resolve().parents[1] / 'datasets/tax-mini-poc'


@unittest.skipUnless(os.environ.get('DOC_INTELL_DOCKER_TESTS') == '1', 'Opt-in real Docker conformance')
class DockerConformanceTests(unittest.TestCase):
    def test_native_model_catalogs_contain_exact_luna_sol_terra_with_medium(self):
        # Inspect the immutable installed catalogs: no login, network, or model
        # invocation is involved. Provider access is verified by actual runs.
        code = r'''
import json, pathlib, tomllib, tau_coding
models = ('gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra')
pi_path = pathlib.Path('/usr/local/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist/providers/data/openai-codex.json')
pi = json.loads(pi_path.read_text())['openai-codex-responses']
tau_path = pathlib.Path(tau_coding.__file__).parent / 'data/catalog.toml'
tau = next(item for item in tomllib.loads(tau_path.read_text())['providers'] if item['name'] == 'openai-codex')
checks = {}
for model in models:
    pi_model = pi.get(model, {})
    checks['pi/' + model] = (
        pi_model.get('id') == model and pi_model.get('provider') == 'openai-codex'
        and pi_model.get('reasoning') is True
        and pi_model.get('thinkingLevelMap', {}).get('medium', 'medium') == 'medium'
    )
    checks['tau/' + model] = (
        model in tau['models'] and model in tau['thinking_models']
        and 'medium' in tau['thinking_levels']
        and 'medium' not in tau['model_metadata'][model].get('unsupported_thinking_levels', [])
    )
print(json.dumps(checks))
'''
        result = subprocess.run(
            ['docker', 'run', '--rm', '--network', 'none', '--read-only',
             '--entrypoint', 'python3', DEFAULT_IMAGE, '-c', code],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, 'Could not inspect the pinned harness model catalogs')
        checks = json.loads(result.stdout)
        self.assertEqual(len(checks), 6)
        self.assertTrue(all(checks.values()), checks)

    def test_worker_has_assigned_pdf_but_no_ground_truth_or_evaluator_network(self):
        code = r'''
import json, pathlib, socket, urllib.request, urllib.error
checks = {'assigned_pdf': pathlib.Path('/workspace/inputs/01_w2.pdf').is_file(),
          'other_pdf_hidden': not pathlib.Path('/workspace/inputs/02_1099_int.pdf').exists(),
          'ground_truth_hidden': not pathlib.Path('/workspace/ground_truth').exists()}
try:
    with socket.create_connection(('host.docker.internal', 6006), timeout=2):
        checks['direct_evaluator_blocked'] = False
except OSError:
    checks['direct_evaluator_blocked'] = True
opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http':'http://egress:8080'}))
try:
    opener.open('http://host.docker.internal:6006/v1/datasets', timeout=5)
    checks['proxy_evaluator_read_blocked'] = False
except urllib.error.HTTPError as error:
    checks['proxy_evaluator_read_blocked'] = error.code == 403
print(json.dumps(checks))
'''
        examples, _ = load_examples(DATASET)
        profile = {'name': 'conformance-test', 'command': ['python3', '-c', code],
                   'output_mode': 'json', 'auth': 'none', 'telemetry': 'none'}
        with TemporaryDirectory() as temporary:
            invocation = HarnessInvocation('', 'check', 1, DATASET, examples[0].input.documents,
                                           Path(temporary), '1' * 32, '2' * 16)
            result = NativeHarness(profile, make_preparer(profile), 20).invoke(invocation)
        self.assertEqual(result.status, 'success', result.error)
        self.assertTrue(all(result.output.values()), result.output)


@unittest.skipUnless(os.environ.get('DOC_INTELL_PHOENIX_TESTS') == '1',
                     'Opt-in Docker and running Phoenix OTLP conformance')
class CorporateOtelConformanceTests(unittest.TestCase):
    def test_corporate_json_harness_exports_otel_directly_through_sidecar(self):
        # The two-byte protobuf is ExportTraceServiceRequest with one empty
        # resource_spans message (field 1, length 0). It is a valid OTLP request
        # containing zero spans, so this transport test creates no trace records.
        # The fixture uses only Python's standard library, not an OTel SDK.
        code = r'''
import json, os, sys, time, urllib.request, urllib.error
prompt = sys.stdin.read()
endpoint = os.environ['OTEL_EXPORTER_OTLP_TRACES_ENDPOINT']
request = urllib.request.Request(
    endpoint, data=b'\x0a\x00', method='POST',
    headers={'Content-Type': 'application/x-protobuf'},
)
for attempt in range(3):
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
            response.read()
        break
    except urllib.error.URLError:
        if attempt == 2:
            raise
        time.sleep(0.2)
print(json.dumps({
    'values': {
        'otlp_http_status': status,
        'prompt': prompt,
        'traceparent': os.environ['TRACEPARENT'],
        'run_id': os.environ['DOC_INTELL_RUN_ID'],
        'task_id': os.environ['DOC_INTELL_TASK_ID'],
        'repetition': os.environ['DOC_INTELL_REPETITION'],
        'endpoint': endpoint,
        'protocol': os.environ['OTEL_EXPORTER_OTLP_TRACES_PROTOCOL'],
        'resource_attributes': os.environ['OTEL_RESOURCE_ATTRIBUTES'],
        'provider_credentials_absent': not any(os.environ.get(name) for name in (
            'OPENAI_API_KEY', 'OPENAI_CODEX_ACCESS_TOKEN', 'PHOENIX_API_KEY')),
    },
    'evidence': {},
}))
'''
        profile = {
            'name': 'corporate-otel-conformance', 'command': ['python3', '-c', code],
            'output_mode': 'json', 'auth': 'none', 'telemetry': 'native-otel',
        }
        phoenix_url = os.environ.get('PHOENIX_ENDPOINT', 'http://127.0.0.1:6006')
        prompt = 'Check the native corporate OTLP transport without calling a model.'
        with TemporaryDirectory() as temporary:
            invocation = HarnessInvocation(
                input_text=prompt, task_id='native-otel-conformance', repetition=2,
                dataset=DATASET, documents=(), artifact_dir=Path(temporary),
                trace_id='a' * 32, parent_span_id='b' * 16,
                run_id='corporate-otel-conformance-run',
            )
            result = NativeHarness(
                profile, make_preparer(profile, phoenix_url=phoenix_url), 45,
            ).invoke(invocation)
        self.assertEqual(result.status, 'success', result.error)
        self.assertEqual(result.events, [], 'The corporate fixture emits JSON, not JSONL lifecycle events')
        values = result.output['values']
        self.assertEqual(values['otlp_http_status'], 200)
        self.assertEqual(values['prompt'], prompt)
        self.assertEqual(values['traceparent'], f'00-{invocation.trace_id}-{invocation.parent_span_id}-01')
        self.assertEqual(values['run_id'], invocation.run_id)
        self.assertEqual(values['task_id'], invocation.task_id)
        self.assertEqual(values['repetition'], str(invocation.repetition))
        self.assertEqual(values['endpoint'], 'http://egress:8080/v1/traces')
        self.assertEqual(values['protocol'], 'http/protobuf')
        attributes = dict(item.split('=', 1) for item in values['resource_attributes'].split(','))
        self.assertEqual(attributes['benchmark.run_id'], invocation.run_id)
        self.assertEqual(attributes['benchmark.task_id'], invocation.task_id)
        self.assertEqual(attributes['benchmark.repetition'], str(invocation.repetition))
        self.assertEqual(attributes['benchmark.harness'], profile['name'])
        self.assertEqual(attributes['openinference.project.name'], 'doc-intell-poc')
        self.assertTrue(values['provider_credentials_absent'])


if __name__ == '__main__':
    unittest.main()

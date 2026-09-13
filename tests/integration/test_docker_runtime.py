"""Opt-in Docker filesystem and installed model catalog checks; no model calls."""

import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from evals.adapters.native import NativeHarness
from evals.runtime.profiles import DEFAULT_IMAGE
from evals.runtime.docker import make_preparer
from evals.contracts import HarnessInvocation
from evals.datasets.loader import load_examples
from tests.support.paths import ROOT
DATASET = ROOT / 'datasets/tax-mini-poc'


@unittest.skipUnless(os.environ.get('DOC_INTELL_DOCKER_TESTS') == '1', 'Opt-in real Docker conformance')
class DockerConformanceTests(unittest.TestCase):
    def test_mixed_format_mounts_expose_only_assigned_inputs(self):
        code = r'''
import json, pathlib
base = pathlib.Path('/workspace')
checks = {'assigned_' + suffix: (base / ('inputs/nested/document.' + suffix)).read_bytes() == b'input-fixture'
          for suffix in ('pdf', 'jpg', 'jpeg', 'png', 'json')}
checks['unassigned_hidden'] = not (base / 'inputs/unassigned.json').exists()
checks['ground_truth_hidden'] = not (base / 'ground_truth').exists()
checks['source_kit_hidden'] = not (base / 'taxcalc').exists()
try:
    (base / 'inputs/nested/document.json').write_text('changed')
    checks['readonly'] = False
except OSError:
    checks['readonly'] = True
print(json.dumps(checks))
'''
        profile = {'name': 'asset-conformance', 'command': ['python3', '-c', code],
                   'output_mode': 'json', 'auth': 'none', 'telemetry': 'none'}
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'inputs/nested').mkdir(parents=True)
            (root / 'ground_truth').mkdir()
            (root / 'ground_truth/expected.json').write_text('{"hidden":true}')
            (root / 'inputs/unassigned.json').write_text('{"hidden":true}')
            (root / 'taxcalc').mkdir()
            paths = ['inputs/nested/document.' + suffix for suffix in ('pdf', 'jpg', 'jpeg', 'png', 'json')]
            for name in paths:
                (root / name).write_bytes(b'input-fixture')
            invocation = HarnessInvocation('', 'check', 1, root, tuple({'path': name} for name in paths),
                                           root / 'artifacts', '1' * 32, '2' * 16)
            result = NativeHarness(profile, make_preparer(profile), 20).invoke(invocation)
        self.assertEqual(result.status, 'success', result.error)
        self.assertTrue(all(result.output.values()), result.output)

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



if __name__ == '__main__':
    unittest.main()

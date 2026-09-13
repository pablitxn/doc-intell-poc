"""Opt-in corporate OpenTelemetry SDK checks against disposable Phoenix."""

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from evals.adapters.native import NativeHarness
from evals.runtime.profiles import DEFAULT_IMAGE
from evals.runtime.docker import make_preparer
from evals.contracts import HarnessInvocation
from evals.telemetry.spans import build_task_trace
from evals.telemetry.otlp import encode_otlp
from tests.support.phoenix import temporary_phoenix
from tests.support.paths import ROOT

DATASET = ROOT / 'datasets/tax-mini-poc'


@unittest.skipUnless(os.environ.get('DOC_INTELL_PHOENIX_TESTS') == '1',
                     'Opt-in Docker and disposable Phoenix SDK conformance')
class CorporateOtelConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = ExitStack()
        cls.addClassCleanup(cls.resources.close)
        cls.phoenix_url = cls.resources.enter_context(temporary_phoenix())
        cls.http = build_opener(ProxyHandler({}))
        # The exact same production base and current proxy source are exercised;
        # only this temporary derivative has a test SDK and corporate fixture.
        root = ROOT
        base = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', DEFAULT_IMAGE],
                              capture_output=True, text=True, check=True, timeout=15).stdout.strip()
        # Dockerfile FROM resolves names, not a local sha256 image identifier.
        # Keep an owned alias so a concurrent rebuild cannot change this base.
        base_alias = 'doc-intell-otel-base:' + uuid4().hex
        subprocess.run(['docker', 'image', 'tag', base, base_alias],
                       capture_output=True, check=True, timeout=15)
        cls.resources.callback(subprocess.run, ['docker', 'image', 'rm', base_alias],
                               capture_output=True, timeout=15, check=False)
        sources = [root / 'tests/fixtures/corporate_otel.Dockerfile',
                   root / 'tests/fixtures/corporate_otel.py', root / 'containers/egress_proxy.py']
        fingerprint = hashlib.sha256(base.encode() + b''.join(path.read_bytes() for path in sources)).hexdigest()[:16]
        cls.image = 'doc-intell-otel-conformance:' + fingerprint
        with TemporaryDirectory(prefix='doc-intell-otel-build-') as temporary:
            directory = Path(temporary)
            for source, destination in zip(sources, ('Dockerfile', 'corporate_otel.py', 'egress_proxy.py')):
                shutil.copyfile(source, directory / destination)
            result = subprocess.run([
                'docker', 'build', '--quiet', '--build-arg', 'HARNESS_IMAGE=' + base_alias,
                '--tag', cls.image, str(directory),
            ], capture_output=True, text=True, timeout=240)
        if result.returncode:
            raise RuntimeError('Could not build the test-only OpenTelemetry SDK image')

    def test_corporate_sdk_exports_connected_spans_with_and_without_gzip(self):
        for compression in ('none', 'gzip'):
            with self.subTest(compression=compression):
                self.check_sdk_trace(compression)

    def check_sdk_trace(self, compression):
        profile = {
            'name': 'corporate-otel-conformance',
            'command': ['python3', '/opt/doc-intell/corporate_otel.py', compression],
            'output_mode': 'json', 'auth': 'none', 'telemetry': 'native-otel',
        }
        prompt = 'Check the native corporate SDK without calling a model.'
        start_ns = time.time_ns()
        with TemporaryDirectory() as temporary:
            invocation = HarnessInvocation(
                input_text=prompt, task_id='native-otel-conformance', repetition=2,
                dataset=DATASET, documents=(), artifact_dir=Path(temporary),
                trace_id=uuid4().hex, parent_span_id=uuid4().hex[:16],
                run_id='corporate-conformance-' + uuid4().hex,
            )
            result = NativeHarness(
                profile, make_preparer(profile, image=self.image, phoenix_url=self.phoenix_url), 45,
            ).invoke(invocation)
        end_ns = time.time_ns()
        self.assertEqual(result.status, 'success', result.error)
        self.assertEqual(result.events, [], 'Corporate stdout is JSON; its SDK emits the internal spans')
        values = result.output['values']
        self.assertTrue(values['flushed'])
        self.assertEqual(values['trace_id'], invocation.trace_id)
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

        # Export the actual runner envelope as well. The SDK operation must join
        # its harness.execute parent, which in turn belongs to task.execute.
        root_span_id = uuid4().hex[:16]
        spans = build_task_trace(
            {'task_id': invocation.task_id, 'repetition': invocation.repetition,
             'execution_status': 'success', 'scores': {'task_pass': True}},
            trace_id=invocation.trace_id, root_span_id=root_span_id,
            harness_span_id=invocation.parent_span_id, harness_start_ns=start_ns,
            harness_end_ns=end_ns, task_end_ns=end_ns + 1, events=[], metadata={},
        )
        request = Request(self.phoenix_url + '/v1/traces', data=encode_otlp(spans, project_name='doc-intell-poc'),
                          headers={'Content-Type': 'application/x-protobuf'}, method='POST')
        with self.http.open(request, timeout=10) as response:
            self.assertEqual(response.status, 200)
        observed = self.wait_for_trace(invocation.trace_id, expected_spans=5)
        actual = {span['name']: span for span in observed['spans']}
        self.assertEqual(set(actual), {'task.execute', 'harness.execute', 'evaluate',
                                      'corporate.execute', 'corporate.read_document'})
        self.assertEqual(actual['task.execute']['span_id'], root_span_id)
        self.assertEqual(actual['harness.execute']['span_id'], invocation.parent_span_id)
        self.assertEqual(actual['harness.execute']['parent_id'], root_span_id)
        self.assertEqual(actual['corporate.execute']['span_id'], values['operation_span_id'])
        self.assertEqual(actual['corporate.execute']['parent_id'], invocation.parent_span_id)
        self.assertEqual(actual['corporate.read_document']['span_id'], values['child_span_id'])
        self.assertEqual(actual['corporate.read_document']['parent_id'], values['operation_span_id'])
        self.assertEqual(actual['evaluate']['parent_id'], root_span_id)

    def wait_for_trace(self, trace_id, expected_spans):
        deadline = time.monotonic() + 20
        endpoint = self.phoenix_url + '/v1/projects/doc-intell-poc/traces?limit=100&include_spans=true'
        while time.monotonic() < deadline:
            try:
                with self.http.open(endpoint, timeout=5) as response:
                    traces = json.load(response)['data']
                for item in traces:
                    if item['trace_id'] == trace_id and len(item['spans']) == expected_spans:
                        return item
            except HTTPError as error:
                if error.code != 404:
                    raise
            time.sleep(0.25)
        self.fail('The SDK trace did not reach isolated Phoenix with all expected span IDs')



if __name__ == '__main__':
    unittest.main()

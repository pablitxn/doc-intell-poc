"""Opt-in historical archive import against an empty disposable Phoenix."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from evals.reporting.importer import import_report, _missing_spans
from tests.support.reports import fixture


@unittest.skipUnless(os.environ.get('DOC_INTELL_PHOENIX_TESTS') == '1', 'Opt-in disposable real Phoenix import')
class PhoenixImportIntegrationTests(unittest.TestCase):
    def test_empty_phoenix_import_and_retry_verify_outputs_scores_and_spans(self):
        import httpx
        from phoenix.client import Client
        from tests.support.phoenix import temporary_phoenix
        with TemporaryDirectory() as folder, temporary_phoenix() as origin:
            root = Path(folder)
            source, report, spans = fixture(root)
            original = {path.name: path.read_bytes() for path in source.iterdir()}
            with httpx.Client(base_url=origin, timeout=30) as http:
                client = Client(http_client=http)
                first = import_report(client, http, source, root / 'receipts')
                second = import_report(client, http, source, root / 'receipts')
                self.assertEqual(first, second)
                self.assertTrue(first['complete'])
                dataset = client.datasets.get_dataset(dataset=first['dataset_name'])
                self.assertEqual(dataset.examples[0]['input']['text'], report['rows'][0]['input'])
                self.assertEqual(dataset.examples[0]['output'], {})
                runs = http.get(f"/v1/experiments/{first['experiment_id']}/json").json()
                self.assertEqual(len(runs), 1)
                self.assertEqual(runs[0]['output']['answer'], report['rows'][0]['output'])
                self.assertEqual(len(runs[0]['annotations']), 5)
                self.assertEqual(_missing_spans(http, spans, first['project_name']), [])
                self.assertEqual(original, {path.name: path.read_bytes() for path in source.iterdir()})
                self.assertEqual(len(client.experiments.list(dataset_id=dataset.id)), 1)
                registered = http.post('/graphql', json={'query': 'query { evaluators(first: 100) { edges { node { id } } } }'}).json()
                self.assertEqual(registered['data']['evaluators']['edges'], [])



if __name__ == '__main__':
    unittest.main()

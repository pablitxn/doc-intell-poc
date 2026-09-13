"""Opt-in real Phoenix round trip for the full dataset; model calls stay at zero.

Only this test injects a fixture answer into run_experiment. Production execution
continues to require a real installed harness.
"""
from copy import deepcopy
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import quote

from evals.contracts import HarnessResult
from evals.datasets.loader import load_examples, read_json
from evals.experiments.prompt import PROMPT_VERSION, build_prompt
from evals.experiments.runner import run_experiment
from evals.reporting.importer import import_report, _missing_spans
from evals.reporting.phoenix import prepare_dataset, publish_report
from evals.reporting.tracing import publish_traces

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "datasets/tax-document-eval-v1"
PROMPT_ROOT = Path("/workspace")
METRICS = {"schema_valid", "value_accuracy", "evidence_accuracy", "task_pass", "execution_status"}


@unittest.skipUnless(
    os.environ.get("DOC_INTELL_PHOENIX_TESTS") == "1",
    "Opt-in disposable Phoenix test for all 366 dataset tasks",
)
class FullDatasetPhoenixIntegrationTests(unittest.TestCase):
    def assert_five_success_scores(self, run):
        annotations = run["annotations"]
        self.assertEqual(len(annotations), 5)
        self.assertEqual({row["name"] for row in annotations}, METRICS)
        self.assertTrue(all(row["score"] == 1.0 for row in annotations))

    def test_complete_dataset_publication_and_fixture_archive_round_trip(self):
        import httpx
        from phoenix.client import Client
        from tests.phoenix_fixture import temporary_phoenix

        examples, version = load_examples(DATASET)
        self.assertEqual(len(examples), 366)
        self.assertEqual(len({row.input.case_id for row in examples}), 55)
        self.assertGreater(len(examples), 100)
        selected = examples[-1]  # Deliberately outside the first API page.
        calls = []

        def fixture_answer(input_text):
            calls.append(input_text)
            self.assertNotIn("ground_truth", input_text)
            self.assertNotIn(str(DATASET), input_text)
            return HarnessResult(
                output=deepcopy(selected.expected),
                usage={"input_tokens": 0, "output_tokens": 0},
                metadata={"test_fixture": True, "model_calls": 0},
            )

        with TemporaryDirectory() as temporary:
            work = Path(temporary)
            run_dir = run_experiment(
                DATASET, fixture_answer, work / "runs",
                adapter_name="tests-only-fixture", task_id=selected.input.task_id,
                prompt_root=PROMPT_ROOT,
                harness_metadata={"test_fixture": True, "model_calls": 0},
            )
            self.assertEqual(len(calls), 1)
            report = read_json(run_dir / "report.json")
            traces = read_json(run_dir / "traces.json")
            self.assertEqual(report["summary"]["tasks_evaluated"], 1)
            self.assertEqual(report["summary"]["tasks_passed"], 1)
            self.assertEqual(len({span["trace_id"] for span in traces}), 1)
            trace_id = report["rows"][0]["trace_id"]

            # Source Phoenix receives the entire dataset, even though the fixture
            # experiment only selected one task.
            with temporary_phoenix() as origin:
                with httpx.Client(base_url=origin, timeout=30, trust_env=False) as http:
                    client = Client(http_client=http)
                    dataset = prepare_dataset(client, DATASET, prompt_root=PROMPT_ROOT)
                    dataset_id, version_id = dataset.id, dataset.version_id
                    fresh = Client(http_client=http).datasets.get_dataset(dataset=dataset.name)
                    remote = {row["metadata"]["task_id"]: row for row in fresh.examples}
                    self.assertEqual(len(fresh.examples), 366)
                    self.assertEqual(set(remote), {example.input.task_id for example in examples})
                    self.assertEqual(len({row["metadata"]["case_id"] for row in remote.values()}), 55)
                    for example in examples:
                        with self.subTest(task_id=example.input.task_id):
                            row = remote[example.input.task_id]
                            self.assertEqual(row["output"], example.expected)
                            self.assertEqual(row["input"], {
                                "text": build_prompt(example.input, DATASET, document_root=PROMPT_ROOT),
                            })
                            self.assertEqual(row["metadata"], {
                                "task_id": example.input.task_id,
                                "case_id": example.input.case_id,
                                "group": example.group,
                                "field_types": example.input.fields,
                                "document_ids": [d["document_id"] for d in example.input.documents],
                                "dataset_version": version,
                                "prompt_version": PROMPT_VERSION,
                            })
                    again = prepare_dataset(client, DATASET, prompt_root=PROMPT_ROOT)
                    self.assertEqual((again.id, again.version_id), (dataset_id, version_id))
                    self.assertEqual(len(again.examples), 366)
                    published = publish_report(client, again, run_dir, http=http)
                    uploaded = publish_traces(http, run_dir, project_name="full-dataset-fixture-source")
                    self.assertTrue(published["complete"])
                    self.assertTrue(uploaded["complete"])
                    self.assertEqual(uploaded["spans"], len(traces))
                    response = http.get(f"/v1/experiments/{quote(published['experiment_id'], safe='')}/json")
                    response.raise_for_status()
                    runs = response.json()
                    self.assertEqual(len(runs), 1)
                    self.assertEqual(runs[0]["trace_id"], trace_id)
                    self.assertEqual(runs[0]["example_id"], remote[selected.input.task_id]["node_id"])
                    self.assertEqual(runs[0]["output"]["answer"], selected.expected)
                    self.assert_five_success_scores(runs[0])

            original = {str(p.relative_to(run_dir)): p.read_bytes() for p in run_dir.rglob("*") if p.is_file()}
            # A genuinely new Phoenix receives the complete saved dataset
            # snapshot and the one saved attempt with its scores and trace.
            with temporary_phoenix() as origin:
                with httpx.Client(base_url=origin, timeout=30, trust_env=False) as http:
                    client = Client(http_client=http)
                    with patch("evals.experiments.runner.run_experiment", side_effect=AssertionError("Import must not execute a task")), \
                         patch("evals.evaluators.tax_mini.evaluate", side_effect=AssertionError("Import must not regrade")):
                        first = import_report(client, http, run_dir, work / "imports",
                                              project_name="full-dataset-fixture-imported")
                        second = import_report(client, http, run_dir, work / "imports",
                                               project_name="full-dataset-fixture-imported")
                    self.assertEqual(first, second)
                    self.assertTrue(first["complete"])
                    self.assertEqual(first["reference_status"], "saved_snapshot")
                    imported = client.datasets.get_dataset(dataset=first["dataset_name"])
                    self.assertEqual(len(imported.examples), 366)
                    imported_rows = {row["metadata"]["task_id"]: row for row in imported.examples}
                    self.assertEqual(set(imported_rows), {example.input.task_id for example in examples})
                    self.assertEqual(len({row["metadata"]["case_id"] for row in imported_rows.values()}), 55)
                    for example in examples:
                        saved = imported_rows[example.input.task_id]
                        self.assertEqual(saved["output"], example.expected)
                        self.assertEqual(saved["metadata"]["field_types"], example.input.fields)
                        self.assertEqual(saved["metadata"]["reference_status"], "saved_snapshot")
                    self.assertEqual(imported_rows[selected.input.task_id]["input"]["text"], report["rows"][0]["input"])
                    response = http.get(f"/v1/experiments/{quote(first['experiment_id'], safe='')}/json")
                    response.raise_for_status()
                    runs = response.json()
                    self.assertEqual(len(runs), 1)
                    self.assertEqual(runs[0]["trace_id"], trace_id)
                    self.assertEqual(runs[0]["output"]["answer"], selected.expected)
                    self.assert_five_success_scores(runs[0])
                    self.assertEqual(_missing_spans(http, traces, first["project_name"]), [])
                    self.assertEqual(len(client.experiments.list(dataset_id=imported.id)), 1)
            self.assertEqual(original, {str(p.relative_to(run_dir)): p.read_bytes() for p in run_dir.rglob("*") if p.is_file()})
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10,<3.15"
# dependencies = ["arize-phoenix-client==3.5.0"]
# ///
"""Run the installed harness and publish datasets, runs and scores to Phoenix."""

import argparse
import os
from pathlib import Path
import shlex
import sys

from evals.adapters.command import command_harness
from evals.experiments.runner import run_experiment
from evals.evaluators.definitions import code_definitions
from evals.reporting.phoenix import prepare_dataset, publish_report
from evals.reporting.phoenix_evaluators import register_evaluators


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--harness-command", help="Installed executable and any fixed arguments")
    source.add_argument("--upload-only", type=Path, help="Retry publication of an existing run directory; never calls the harness")
    parser.add_argument("--dataset", type=Path, default=Path(__file__).resolve().parent / "datasets/tax-mini-poc")
    parser.add_argument("--task", help="One task_id; defaults to all six")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    parser.add_argument("--phoenix-url", default=os.environ.get("PHOENIX_ENDPOINT", "http://127.0.0.1:6006"))
    args = parser.parse_args()
    if args.upload_only and args.task:
        parser.error("--task cannot be combined with --upload-only")
    run_dir = args.upload_only
    try:
        from phoenix.client import Client
        import httpx

        if args.harness_command:
            command = shlex.split(args.harness_command)
            adapter = command_harness(command, timeout_seconds=args.timeout)
        api_key = os.environ.get("PHOENIX_API_KEY")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        with httpx.Client(base_url=args.phoenix_url, headers=headers, timeout=60) as http:
            client = Client(http_client=http)
            # Publish inputs and definitions before incurring any harness calls.
            dataset = prepare_dataset(client, args.dataset)
            registry = register_evaluators(http, code_definitions())
            print(f"Phoenix dataset: {dataset.name}; evaluators: {len(registry)}")
            if args.harness_command:
                run_dir = run_experiment(
                    args.dataset, adapter, args.output_dir,
                    adapter_name=command[0], task_id=args.task,
                )
            publication = publish_report(client, dataset, run_dir, evaluator_registry=registry)
    except Exception as exc:
        detail = str(exc) if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError)) else type(exc).__name__
        print(f"Evaluation/publication failed: {detail}", file=sys.stderr)
        if run_dir is not None:
            print(f"Local artifacts: {run_dir}. Retry with --upload-only {run_dir}", file=sys.stderr)
        return 1
    print(f"Local report: {run_dir / 'report.json'}")
    print(f"Phoenix: {args.phoenix_url.rstrip('/')} (experiment {publication['experiment_id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

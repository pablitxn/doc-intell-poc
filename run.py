#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10,<3.15"
# dependencies = ["arize-phoenix-client==3.5.0", "opentelemetry-proto==1.44.0"]
# ///
"""Run real harnesses and publish datasets, scores and traces to Phoenix."""

import argparse
import json
import os
from pathlib import Path
import shlex
import sys

from evals.cli import add_execution_options, add_run_options, validate_execution_options
from evals.application import prepare_selection, run_selection
from evals.datasets.loader import read_json
from evals.evaluators.definitions import code_definitions
from evals.reporting.phoenix import prepare_dataset, publish_report, validate_current_report
from evals.reporting.phoenix_evaluators import register_evaluators
from evals.reporting.trace_upload import publish_traces


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    add_execution_options(parser, source)
    source.add_argument('--upload-only', type=Path, help='Retry publication of local artifacts; never invokes a harness')
    source.add_argument('--import-run', type=Path, help='Import saved results into another Phoenix instance without running models or regrading')
    add_run_options(parser)
    args = parser.parse_args()
    validate_execution_options(parser, args)
    if (args.upload_only or args.import_run) and (args.task or args.check or args.repetitions != 1):
        parser.error('--task, --check and --repetitions cannot be combined with saved-result publication')
    run_dir = args.upload_only
    try:
        if args.check:
            from evals.diagnostics import diagnose
            diagnosis = diagnose(args)
            print(json.dumps(diagnosis, indent=2))
            return 0 if diagnosis['ready'] else 1
        if args.import_run:
            from phoenix.client import Client
            import httpx
            from evals.runtime.network import trace_endpoint
            from evals.reporting.importer import import_report
            trace_endpoint(args.phoenix_url)
            headers = {}
            if os.environ.get('PHOENIX_API_KEY'):
                headers['Authorization'] = 'Bearer ' + os.environ['PHOENIX_API_KEY']
            with httpx.Client(base_url=args.phoenix_url, headers=headers, timeout=60) as http:
                imported = import_report(Client(http_client=http), http, args.import_run,
                                         args.output_dir / 'imports')
            print(json.dumps(imported, indent=2))
            return 0
        prepared = [] if args.upload_only else prepare_selection(args)
        prompt_root = None
        if args.upload_only:
            saved = read_json(run_dir / 'report.json')
            validate_current_report(saved)
            if saved.get('prompt_root'):
                prompt_root = Path(saved['prompt_root'])
        elif not args.harness_command:
            prompt_root = Path('/workspace')
        from phoenix.client import Client
        import httpx
        api_key = os.environ.get('PHOENIX_API_KEY')
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
        with httpx.Client(base_url=args.phoenix_url, headers=headers, timeout=60) as http:
            client = Client(http_client=http)
            dataset_options = {'prompt_root': prompt_root} if prompt_root else {}
            dataset = prepare_dataset(client, args.dataset, **dataset_options)
            registry = register_evaluators(http, code_definitions())
            print(f'Phoenix dataset: {dataset.name}; evaluators: {len(registry)}', flush=True)
            publication_failed = False

            def publish_completed(name, completed_dir):
                nonlocal run_dir, publication_failed
                run_dir = completed_dir
                print(f"Local report: {run_dir / 'report.json'}", flush=True)
                try:
                    publish_traces(http, run_dir)
                    publication = publish_report(client, dataset, run_dir, evaluator_registry=registry, http=http)
                    print(f"Phoenix: {args.phoenix_url.rstrip('/')} (experiment {publication['experiment_id']})", flush=True)
                except Exception as exc:
                    publication_failed = True
                    retry = shlex.join(['./run.py', '--dataset', str(args.dataset),
                                        '--phoenix-url', args.phoenix_url,
                                        '--upload-only', str(run_dir)])
                    print(f'Publication failed ({type(exc).__name__}); retry with {retry}', file=sys.stderr, flush=True)

            if args.upload_only:
                publish_completed(None, args.upload_only)
            else:
                run_selection(args, prepared, on_completed=publish_completed)
            if publication_failed:
                return 1
    except Exception as exc:
        # Process/provider diagnostics never enter messages via arbitrary exception text.
        detail = str(exc) if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError)) else type(exc).__name__
        print(f'Evaluation/publication failed: {detail}', file=sys.stderr)
        if run_dir is not None:
            print(f'Local artifacts: {run_dir}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

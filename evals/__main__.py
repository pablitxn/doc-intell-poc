"""Run with python3 -m evals from the repository root."""

import argparse
import json
import os
from pathlib import Path
import shlex

from .adapters.command import command_harness
from .cli import add_execution_options, native_adapters, validate_execution_options
from .datasets.loader import read_json
from .experiments.runner import run_experiment
from .experiments.comparison import write_comparison


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    add_execution_options(parser, source)
    parser.add_argument('--dataset', type=Path, default=Path(__file__).resolve().parents[1] / 'datasets/tax-mini-poc')
    parser.add_argument('--task', help='One task_id; defaults to all six')
    parser.add_argument('--timeout', type=float, default=120.0, help='Seconds per harness invocation (default: 120)')
    parser.add_argument('--output-dir', type=Path, default=Path('runs'))
    parser.add_argument('--phoenix-url', default=os.environ.get('PHOENIX_ENDPOINT', 'http://127.0.0.1:6006'),
                        help='Native OTel and diagnostic endpoint; this entrypoint does not publish evaluation reports')
    args = parser.parse_args()
    validate_execution_options(parser, args)
    try:
        if args.check:
            from .diagnostics import diagnose
            diagnosis = diagnose(args)
            print(json.dumps(diagnosis, indent=2))
            if not diagnosis['ready']:
                raise SystemExit(1)
            return
        if args.harness_command:
            command = shlex.split(args.harness_command)
            prepared = [(command[0], command_harness(command, timeout_seconds=args.timeout), {})]
        else:
            prepared = native_adapters(args)
        run_dirs = []
        for name, adapter, metadata in prepared:
            options = {'adapter_name': name, 'task_id': args.task}
            if not args.harness_command or args.repetitions != 1:
                options.update(repetitions=args.repetitions, harness_metadata=metadata)
            if not args.harness_command:
                options['prompt_root'] = Path('/workspace')
            run_dir = run_experiment(args.dataset, adapter, args.output_dir, **options)
            run_dirs.append(run_dir)
            summary = read_json(run_dir / 'report.json')['summary']
            print(f"{name}: {summary['tasks_passed']}/{summary['tasks_evaluated']} tasks passed; {summary['fields_evaluated']} fields evaluated")
            print(run_dir / 'report.json')
        if len(run_dirs) > 1:
            print(f"Comparison: {write_comparison(run_dirs, args.output_dir)}")
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()

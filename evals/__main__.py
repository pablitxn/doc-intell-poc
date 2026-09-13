"""Run with python3 -m evals from the repository root."""

import argparse
import json

from .cli import add_execution_options, add_run_options, validate_execution_options
from .application import prepare_selection, run_selection
from .datasets.loader import read_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    add_execution_options(parser, source)
    add_run_options(parser)
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
        prepared = prepare_selection(args)

        def show_completed(name, run_dir):
            summary = read_json(run_dir / 'report.json')['summary']
            print(f"{name}: {summary['tasks_passed']}/{summary['tasks_evaluated']} tasks passed; {summary['fields_evaluated']} fields evaluated")
            print(run_dir / 'report.json')

        run_selection(args, prepared, on_completed=show_completed)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()

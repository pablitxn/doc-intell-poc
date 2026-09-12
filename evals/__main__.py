"""Run with python3 -m evals from the repository root."""

import argparse
from pathlib import Path
import shlex

from .adapters.command import command_harness
from .datasets.loader import read_json
from .experiments.runner import run_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harness-command", required=True, help="Installed executable and any fixed arguments")
    parser.add_argument("--dataset", type=Path, default=Path(__file__).resolve().parents[1] / "datasets/tax-mini-poc")
    parser.add_argument("--task", help="One task_id; defaults to all six")
    parser.add_argument("--timeout", type=float, default=120.0, help="Seconds per harness invocation (default: 120)")
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    try:
        command = shlex.split(args.harness_command)
        adapter = command_harness(command, timeout_seconds=args.timeout)
        run_dir = run_experiment(
            args.dataset,
            adapter,
            args.output_dir,
            adapter_name=command[0],
            task_id=args.task,
        )
    except ValueError as exc:
        parser.error(str(exc))
    summary = read_json(run_dir / "report.json")["summary"]
    print(f"{summary['tasks_passed']}/{summary['tasks_evaluated']} tasks passed; {summary['fields_evaluated']} fields evaluated")
    print(run_dir / "report.json")


if __name__ == "__main__":
    main()

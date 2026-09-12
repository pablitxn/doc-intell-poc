"""Run with python3 -m evals from the repository root."""

import argparse
from pathlib import Path

from .adapters.offline import empty_response, replay
from .datasets.loader import read_json
from .experiments.runner import run_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--smoke", action="store_true", help="Empty test responses; expected to fail quality checks")
    source.add_argument("--predictions", type=Path, help="Saved JSON in answers/TASK_ID format")
    parser.add_argument("--task", help="One task_id; defaults to all six")
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    adapter = empty_response
    if args.predictions:
        payload = read_json(args.predictions)
        if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
            parser.error("predictions must contain an answers object")
        adapter = replay(payload["answers"])
    try:
        run_dir = run_experiment(
            Path(__file__).resolve().parents[1] / "datasets/tax-mini-poc",
            adapter,
            args.output_dir,
            mode="smoke" if args.smoke else "replay",
            task_id=args.task,
        )
    except ValueError as exc:
        parser.error(str(exc))
    summary = read_json(run_dir / "report.json")["summary"]
    print(f"{summary['tasks_passed']}/{summary['tasks_evaluated']} tasks passed; {summary['fields_evaluated']} fields evaluated")
    print(run_dir / "report.json")


if __name__ == "__main__":
    main()

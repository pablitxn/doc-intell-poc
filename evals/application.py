"""Shared execution flow for local reports and Phoenix publication.

Entrypoints own presentation and publication. This module prepares the selected
harnesses, executes each experiment and compares the resulting local reports.
"""

from pathlib import Path
import shlex

from .adapters.command import command_harness
from .cli import native_adapters
from .experiments.comparison import write_comparison
from .experiments.runner import run_experiment


def prepare_selection(args):
    """Resolve every harness before any invocation or external publication."""
    if args.harness_command:
        command = shlex.split(args.harness_command)
        return [(command[0], command_harness(command, timeout_seconds=args.timeout), {})]
    return native_adapters(args)


def run_selection(args, prepared, *, on_completed):
    """Persist each experiment before handing its result to the entrypoint.

    The publication callback can record a failed upload and return normally so the
    remaining local experiments and their comparison still finish.
    """
    run_dirs = []
    for name, adapter, metadata in prepared:
        options = {'adapter_name': name, 'task_id': args.task}
        if not args.harness_command or args.repetitions != 1:
            options.update(repetitions=args.repetitions, harness_metadata=metadata)
        if not args.harness_command:
            options['prompt_root'] = Path('/workspace')
        run_dir = run_experiment(args.dataset, adapter, args.output_dir, **options)
        run_dirs.append(run_dir)
        on_completed(name, run_dir)
    if len(run_dirs) > 1:
        print(f"Comparison: {write_comparison(run_dirs, args.output_dir)}")
    return run_dirs

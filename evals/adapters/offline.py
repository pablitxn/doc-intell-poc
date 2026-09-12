"""Offline doubles only. Neither adapter extracts or invokes a model."""

from copy import deepcopy

from ..contracts import HarnessAdapter, TaskInput


def empty_response(task: TaskInput) -> dict:
    """Intentionally fails the quality checks; exercises all task rows for free."""
    return {"values": {}, "evidence": {}}


def replay(answers: dict) -> HarnessAdapter:
    """Bridge the original answers/TASK_ID format to one output per task."""
    def run(task: TaskInput) -> object:
        return deepcopy(answers.get(task.task_id, {}))

    return run

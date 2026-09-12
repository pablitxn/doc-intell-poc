"""The adapter sees TaskInput; only the evaluation process sees Example."""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class TaskInput:
    task_id: str
    case_id: str
    tax_year: int
    instruction: str
    fields: dict[str, str]
    documents: tuple[dict, ...]
    response_format: dict


@dataclass(frozen=True)
class Example:
    input: TaskInput
    expected: dict
    group: str


# One call represents one fresh task session. Return the row, not answers/TASK_ID.
# The runner owns evaluation; a future real adapter owns session isolation.
HarnessAdapter = Callable[[TaskInput], object]

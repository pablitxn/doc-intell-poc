"""TaskInput and Example stay local; the harness receives a rendered string."""

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


# One string in, one parsed JSON answer out. Each call starts a new process.
HarnessAdapter = Callable[[str], object]

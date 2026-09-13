"""TaskInput and Example stay local; the harness receives a rendered string."""

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
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


@dataclass(frozen=True)
class HarnessInvocation:
    """Local execution context; only input_text is sent to the agent as a prompt."""

    input_text: str
    task_id: str
    repetition: int
    dataset: Path
    documents: tuple[dict, ...]
    artifact_dir: Path
    trace_id: str
    parent_span_id: str
    run_id: str = ""


@dataclass
class HarnessResult:
    """An unmodified domain answer plus independently collected telemetry."""

    output: object = None
    status: str = "success"
    error: str | None = None
    events: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessSpec:
    """A prepared process inside the selected execution environment."""

    argv: tuple[str, ...]
    cwd: Path | None = None
    env: dict[str, str] | None = None
    metadata: dict = field(default_factory=dict)

"""Small text-stdin test doubles; never used by production harnesses."""

def empty_response(input_text):
    """A local test double; production runs always invoke the injected harness."""
    assert isinstance(input_text, str)
    return {"values": {}, "evidence": {}}

def task_id_from_text(input_text):
    return input_text.split("Task ID: ", 1)[1].splitlines()[0]

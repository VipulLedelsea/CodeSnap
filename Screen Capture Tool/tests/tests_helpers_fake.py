from types import SimpleNamespace


def counting_client():
    """A stand-in model that answers every call with one fact and counts the program-level calls."""
    class C:
        program_calls = 0

        def __init__(self):
            self.messages = self

        def create(self, **kw):
            name = (kw.get("tools") or [{}])[0].get("name", "record_program")
            if name == "record_program":
                C.program_calls += 1
                data = {"observations": []}
            elif name == "record_review":
                data = {"verdicts": []}
            else:
                data = {"purpose": "x", "facts": []}
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input=data)],
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=1), stop_reason="tool_use")
    return C()

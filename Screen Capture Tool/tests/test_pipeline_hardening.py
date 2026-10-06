"""Regression tests for the pipeline hardening pass: truncated fixes, thinking/temperature params, include leaks,
burst shutdown, verify merge/spacing mapping, thread-safe notes and non-dict model replies. All offline."""
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import anthropic

from core import analysis, deepdive, validate, verify
from core.usage import UsageTracker, cost, price_for

SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def _msg(text="", stop="end_turn", content=None):
    return SimpleNamespace(content=content if content is not None else [SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1), stop_reason=stop)


class OnceClient:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _bad_request():
    req = httpx.Request("POST", "http://x")
    return anthropic.BadRequestError("bad", response=httpx.Response(400, request=req), body=None)


# 1 ── fix_source never returns a truncated file ───────────────────────────────────────────────────────────────────

def test_fix_source_uses_large_budget_and_rejects_truncation():
    ok = OnceClient(_msg("print(1)"))
    assert analysis.fix_source(ok, "print(1", "Python", "err") == "print(1)"
    assert ok.calls[0]["max_tokens"] >= 32000
    with pytest.raises(analysis.FixRejected):
        analysis.fix_source(OnceClient(_msg("print(", stop="max_tokens")), "x", "Python", "err")
    with pytest.raises(analysis.FixRejected):
        analysis.fix_source(OnceClient(_msg("", stop="refusal")), "x", "Python", "err")


def test_fix_source_streams_when_the_client_can():
    class Stream:
        def __init__(self, msg):
            self.msg = msg

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return self.msg

    class C:
        def __init__(self):
            self.messages = self

        def stream(self, **kw):
            self.kw = kw
            return Stream(_msg("fixed"))

        def create(self, **kw):
            raise AssertionError("large output must stream")

    c = C()
    assert analysis.fix_source(c, "x", "Python", "e") == "fixed" and c.kw["max_tokens"] >= 32000


def test_fix_looks_complete_rejects_short_results():
    original = "\n".join(f"line {i}" for i in range(100))
    assert analysis.fix_looks_complete(original, "") is not None
    assert analysis.fix_looks_complete(original, "\n".join(original.splitlines()[:50])) is not None
    assert analysis.fix_looks_complete(original, original.replace("line 3", "line three")) is None


def test_decoder_keeps_the_capture_when_the_fix_is_truncated(monkeypatch):
    import team
    code = "\n".join(f"x{i} = {i}" for i in range(40)) + "\nprint(1))"
    monkeypatch.setattr(team.analysis, "fix_source", lambda *a, **k: "x0 = 0")   # compiles, but is tiny
    out = team.agent_decoder(object(), code, "py", "Python")
    assert out["code"] == code and out["resolved"] is False
    assert "discarded" in out["remaining"]

    def boom(*a, **k):
        raise analysis.FixRejected("cut off")
    monkeypatch.setattr(team.analysis, "fix_source", boom)
    out = team.agent_decoder(object(), code, "py", "Python")
    assert out["code"] == code and out["resolved"] is False


def test_hotkey_fix_writes_a_sibling_and_keeps_the_original(tmp_path, monkeypatch, capsys):
    hk = pytest.importorskip("hotkey_capture")
    original = "\n".join(f"x{i} = {i}" for i in range(30)) + "\nprint(1))"
    path = tmp_path / "report.py"
    path.write_text(original)
    monkeypatch.setattr(hk, "fix_source", lambda *a, **k: "x0 = 0")
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    app = hk.App(None)
    app._validate_and_fix(path, "Python")
    assert path.read_text() == original
    assert not path.with_name("report.fixed.py").exists()

    good = "\n".join(f"x{i} = {i}" for i in range(30)) + "\nprint(1)"
    monkeypatch.setattr(hk, "fix_source", lambda *a, **k: good)
    app._validate_and_fix(path, "Python")
    assert path.read_text() == original and path.with_name("report.fixed.py").read_text() == good


# 2 ── thinking / temperature parameters ───────────────────────────────────────────────────────────────────────────

TOOL = {"name": "record_x", "input_schema": {"type": "object"}}


def test_deepdive_uses_adaptive_thinking_without_forced_tool_choice():
    c = OnceClient(_msg())
    deepdive._call(c, "claude-opus-5-5", "sys", TOOL, "hi")
    kw = c.calls[0]
    assert kw["thinking"] == {"type": "adaptive"} and "budget_tokens" not in str(kw)
    assert kw["tool_choice"] == {"type": "auto"}


def test_deepdive_falls_back_only_on_bad_request_and_remembers_it():
    c = OnceClient(_bad_request(), _msg(), _msg())
    deepdive._call(c, "claude-opus-5-5", "sys", TOOL, "hi")
    assert "thinking" in c.calls[0] and "thinking" not in c.calls[1]
    deepdive._call(c, "claude-opus-5-5", "sys", TOOL, "hi")
    assert len(c.calls) == 3 and "thinking" not in c.calls[2]      # no second doomed request


def test_deepdive_does_not_swallow_other_errors_by_message_text():
    c = OnceClient(RuntimeError("thinking budget invalid tool_choice"))
    with pytest.raises(RuntimeError):
        deepdive._call(c, "claude-opus-5-5", "sys", TOOL, "hi")


def test_temperature_is_not_sent_to_opus(monkeypatch, tmp_path):
    monkeypatch.setenv("CODESNAP_EXTRACT_TEMPERATURE", "0")
    monkeypatch.setattr(analysis, "measured_frame", lambda c, p, raw, calibration=None: (raw, {}, 0))
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG....")
    c = OnceClient(_msg('{"raw_transcription": ["a = 1"], "corrections_applied": []}'))
    analysis.extract_structured(c, png)
    assert "temperature" not in c.calls[0]
    assert analysis._accepts_temperature("claude-sonnet-5-5") and not analysis._accepts_temperature("claude-opus-5-5")


# 3 ── models and prices ───────────────────────────────────────────────────────────────────────────────────────────

def test_text_model_default_and_prices():
    assert analysis.TEXT_MODEL == "claude-sonnet-5-5"
    assert price_for("claude-sonnet-5-5") == price_for("claude-sonnet-5") == (2.0, 10.0)
    assert price_for("claude-sonnet-5-5-20260101") == (2.0, 10.0)
    assert price_for("claude-sonnet-5-20251001") == (2.0, 10.0)
    assert cost("claude-sonnet-5-5", 1_000_000, 0) == pytest.approx(2.0)


def test_tracked_stream_records_usage():
    class Mgr:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return SimpleNamespace(model="claude-opus-5-5", usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                                   stop_reason="max_tokens", content=[])

    client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: Mgr()))
    tracker = UsageTracker()
    with tracker.wrap(client).messages.stream(model="claude-opus-5-5", system="x", max_tokens=5, messages=[]) as s:
        s.get_final_message()
    rec = tracker.take(everything=True)
    assert len(rec) == 1 and rec[0]["ok"] is False and rec[0]["output_tokens"] == 5


# 4 ── compiler include leak, key redaction, temp files ────────────────────────────────────────────────────────────

def test_redact_removes_keys():
    out = validate.redact("x sk-ant-api03-AbC_123-xyz y ANTHROPIC_API_KEY=sk-ant-zzz and ANTHROPIC_API_KEY: abc123")
    assert "sk-ant" not in out and "abc123" not in out and "ANTHROPIC_API_KEY" in out


@pytest.mark.parametrize("src", ['#include "/etc/passwd"', '#include "../../.env"', "#include </Users/me/.env>",
                                 "#  include \"a/../../b\"", "#include FILE_FROM_MACRO", "#import \"/x\""])
def test_unsafe_includes_are_refused(src):
    assert validate.unsafe_include(src + "\nint main(){}")


def test_ordinary_includes_pass():
    assert validate.unsafe_include('#include <stdio.h>\n#include "local.h"\n#include <sys/types.h>') is None


def test_check_source_never_compiles_an_escaping_include(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(validate, "_run", lambda *a, **k: called.append(a) or (1, ""))
    f = tmp_path / "a.c"
    f.write_text('#include "/etc/passwd"\nint main(void){return 0;}\n')
    res = validate.check_source(f)
    assert res["checked"] is False and "not compiled" in res["note"] and not called


def test_check_output_is_redacted(tmp_path, monkeypatch):
    monkeypatch.setitem(validate._CHECKERS, "zz", lambda p: validate._result(True, False, "t", errors="bad sk-ant-SECRET123 ANTHROPIC_API_KEY=hunter2"))
    f = tmp_path / "a.zz"
    f.write_text("x")
    res = validate.check_source(f)
    assert "SECRET123" not in res["errors"] and "hunter2" not in res["errors"]


def test_check_code_text_uses_and_removes_a_private_dir(monkeypatch):
    seen = {}

    def fake(path):
        seen["path"] = Path(path)
        seen["siblings"] = list(Path(path).parent.iterdir())
        return validate._result(True, True, "fake")
    monkeypatch.setitem(validate._CHECKERS, "qq", fake)
    validate.check_code_text("hello", "qq")
    assert seen["siblings"] == [seen["path"]] and not seen["path"].parent.exists()


def test_run_executes_in_an_empty_private_cwd(tmp_path):
    rc, out = validate._run([sys.executable, "-c", "import os;print(len(os.listdir('.')))"])
    assert rc == 0 and out == "0"


def test_no_mktemp_left():
    for name in ("tools.py", "team.py"):
        assert "mktemp(" not in (SRC_DIR / name).read_text()


# 5/6 ── burst shutdown and error path ──────────────────────────────────────────────────────────────────────────────

def test_shutdown_in_burst_mode_joins_the_loop_instead_of_double_analysing(tmp_path, monkeypatch):
    hk = pytest.importorskip("hotkey_capture")
    monkeypatch.setattr(hk, "CAPTURES_ROOT", tmp_path / "caps")
    monkeypatch.setattr(hk, "REPORTS_ROOT", tmp_path / "rep")
    app = hk.App(None)
    app.burst_mode = True
    session = tmp_path / "caps" / "session_1"
    session.mkdir(parents=True)
    app.sessions.append(session)
    finished, order = [], []
    monkeypatch.setattr(app, "_finish", lambda d: finished.append(d))

    def loop():
        while app.running:
            pass
        order.append("loop-exit")
        assert session.exists()          # folders must still exist while the loop analyses
        order.append("analysed")
    app.running = True
    app._spawn(loop)
    app._shutdown()
    assert finished == [] and order == ["loop-exit", "analysed"] and not session.exists()


def test_failed_classification_does_not_stop_a_running_capture(tmp_path, monkeypatch):
    hk = pytest.importorskip("hotkey_capture")
    app = hk.App(None)
    d = tmp_path / "s"
    d.mkdir()
    (d / "001.png").write_bytes(b"x")
    app.running = app.capture_enabled = True
    monkeypatch.setattr(app, "_resolve_kind", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(app, "_mark_failed", lambda *a, **k: None)
    app._analyse_burst(d, artifact_id=None, kind="auto")   # program is None, so it reaches classification
    assert app.running and app.capture_enabled


def test_inflight_and_threads_helpers_are_thread_safe():
    hk = pytest.importorskip("hotkey_capture")
    app = hk.App(None)
    ts = [threading.Thread(target=lambda i=i: (app._track(i), app._untrack(i))) for i in range(50)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert app._inflight == set()


# 7-9 ── verify ─────────────────────────────────────────────────────────────────────────────────────────────────────

LINES = [f"    value_{i} = compute_something({i}, 'a long enough argument text')" for i in range(1, 8)]


def test_spacing_conflicts_are_mapped_through_the_read_positions():
    read = "\n".join(["# header", "x = 1", "y = 2"])
    code = "\n".join(["x = 1", "y = 2"])        # the first read line was dropped by the fix
    notes = {"spacing_conflicts": [3]}          # 1-based position of "y = 2" in the READ text
    out = verify.summarize(code, {"x = 1": "verified", "y = 2": "verified"}, notes, read_code=read)
    assert [f["line"] for f in out["flags"]] == [2]
    notes = {"spacing_conflicts": [2]}          # the read position of "x = 1": final line 1
    out = verify.summarize(code, {"x = 1": "verified", "y = 2": "verified"}, notes, read_code=read)
    assert [f["line"] for f in out["flags"]] == [1]


def test_unnumbered_first_row_is_not_dropped():
    parts = ["orphan row\n" + "\n".join(LINES[:3])]
    assert verify.merge_by_numbers(parts, [{"numbers": [None, 1, 2, 3]}]) is None


def test_unnumbered_row_after_a_short_line_is_not_a_continuation():
    lines = [LINES[0], "x", "stray text"]
    meta = {"numbers": [1, 2, None]}
    assert verify.merge_by_numbers(["\n".join(lines)], [meta]) is None


def test_continuation_after_cut_off_or_full_width_row_is_joined():
    long_ = "a_much_longer_statement = compute(1, 2, 3)"
    out = verify.merge_by_numbers([long_ + "\nb = 2\nmore"], [{"numbers": [1, 2, None]}])
    assert out is None                             # "b = 2" is short and not cut: "more" cannot be placed
    out = verify.merge_by_numbers([long_ + "\nb = 2 [CUT OFF]\nmore"], [{"numbers": [1, 2, None]}])
    assert out is not None and out[0].split("\n")[1].endswith("more")
    out = verify.merge_by_numbers(["b = 2\n" + long_ + "\nmore"], [{"numbers": [1, 2, None]}])
    assert out is not None and out[0].split("\n")[1].endswith("more")


def _naive_sideways_views(frames):
    out = set()
    for i, f in enumerate(frames):
        long_ = [l for l in f if len(verify._stem(l).strip()) >= 8]
        if not long_:
            continue
        if sum(1 for l in long_ if l.lstrip().startswith("[CUT OFF]")) >= 0.5 * len(long_):
            out.add(i)
            continue
        others = [g for j, fr in enumerate(frames) if j != i for g in fr]
        if sum(1 for l in long_ if any(verify._piece_of(l, g) for g in others)) >= 0.5 * len(long_):
            out.add(i)
    return out


def test_sideways_views_matches_the_naive_scan():
    whole = [f"    result_{i} = some_function_name(argument_{i}, another_argument_{i}, third_argument_{i})" for i in range(8)]
    right = ["[CUT OFF]" + l[40:] for l in whole]
    pieces = [l[50:] for l in whole]
    unrelated = [f"completely different statement number {i} in a different file" for i in range(8)]
    for frames in ([whole, pieces], [whole, right], [whole, unrelated], [whole, whole[3:], pieces, unrelated],
                   [whole[:4], whole[4:], right]):
        assert verify.sideways_views(frames) == _naive_sideways_views(frames)


def test_sideways_views_does_not_scan_all_pairs():
    n = 400
    frames = [[f"row{f:03d}_{i:04d} = unique_function_{f}_{i}(x)" for i in range(60)] for f in range(n // 10)]
    calls = {"n": 0}
    real = verify._piece_of
    verify._piece_of = lambda l, g: (calls.__setitem__("n", calls["n"] + 1), real(l, g))[1]
    try:
        verify.sideways_views(frames)
    finally:
        verify._piece_of = real
    assert calls["n"] < 500            # unrelated screens are filtered before any exact comparison


# 10 ── thread safety ──────────────────────────────────────────────────────────────────────────────────────────────

def test_sideways_merge_returns_joined_instead_of_using_a_global():
    whole = [f"    result_{i} = some_function_name(argument_{i}, another_argument_{i}, third_argument_{i})" for i in range(6)]
    cut = [l[:60] + " [CUT OFF]" for l in whole]
    pieces = [l[50:] for l in whole]
    got = verify.sideways_merge_ex(cut, pieces, force=True)
    assert got is not None and len(got) == 3 and got[2] and not hasattr(verify.sideways_merge, "joined")
    assert len(verify.sideways_merge(cut, pieces, force=True)) == 2


def test_rejected_line_numbers_are_reported_per_call_not_via_a_module_global():
    bad = '{"raw_transcription": ["a = 1", "b = 2", "c = 3"], "line_numbers": [9, 3, 100]}'
    good = '{"raw_transcription": ["a = 1", "b = 2", "c = 3"], "line_numbers": [1, 2, 3]}'
    assert analysis._normalize_extract(bad)["numbers_rejected"] == 3
    assert analysis._normalize_extract(good)["numbers_rejected"] == 0
    assert not isinstance(getattr(analysis, "_numbers_note", None), dict)


# 11 ── fatal vs retryable ─────────────────────────────────────────────────────────────────────────────────────────

def _auth_error():
    req = httpx.Request("POST", "http://x")
    return anthropic.AuthenticationError("no", response=httpx.Response(401, request=req), body=None)


def test_fatal_errors_are_classified():
    assert analysis.is_fatal_api_error(_auth_error()) and analysis.is_fatal_api_error(_bad_request())
    assert not analysis.is_fatal_api_error(RuntimeError("x")) and not analysis.is_fatal_api_error(TimeoutError())


def test_detect_kind_surfaces_fatal_errors(tmp_path, capsys):
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG")
    assert analysis.detect_kind(OnceClient(_auth_error()), png) == "code"
    assert "AuthenticationError" in capsys.readouterr().err
    assert analysis.detect_kind(OnceClient(RuntimeError("blip")), png) == "code"
    assert capsys.readouterr().err == ""


def test_safe_extract_reports_fatal_errors(tmp_path, monkeypatch, capsys):
    hk = pytest.importorskip("hotkey_capture")
    app = hk.App(None)
    monkeypatch.setattr("core.analysis.extract_to_cache", lambda *a, **k: (_ for _ in ()).throw(_auth_error()))
    app._safe_extract(tmp_path / "a.png", tmp_path)
    assert "AuthenticationError" in capsys.readouterr().err


# 12 ── non-dict model replies ─────────────────────────────────────────────────────────────────────────────────────

def test_synthesize_final_tolerates_non_object_json():
    c = OnceClient(_msg('["a", "b"]'))
    out = analysis.synthesize_final(c, "some text")
    assert out["is_code"] is False and out["overview"] == '["a", "b"]'


def test_analyst_enrich_tolerates_non_object_json():
    import team
    base = {"is_code": True, "language": "Python", "extension": "py", "overview": "base"}
    out = team._analyst_enrich(OnceClient(_msg("[1, 2]")), "x = 1", base)
    assert out["overview"] == "base" and out["language"] == "Python"


def test_feedback_interpret_ignores_non_object_json():
    from core import feedback
    src = (SRC_DIR / "core" / "feedback.py").read_text()
    assert "isinstance(data, dict)" in src and "isinstance(ch, dict)" in src
    assert feedback.interpret


def test_team_does_not_present_a_truncated_coordinator_as_a_report():
    import team
    ctx = SimpleNamespace(images=[])
    c = OnceClient(_msg("partial thoughts", stop="max_tokens"))
    text, _ = team.run_team(c, ctx, verbose=False)
    assert "stopped without a report" in text and "partial thoughts" not in text


# 13 ── cleanups ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_cache_path_hashes_an_unchanged_file_once(tmp_path, monkeypatch):
    png = tmp_path / "a.png"
    png.write_bytes(b"first")
    reads = []
    real = analysis._robust.read_bytes
    monkeypatch.setattr(analysis._robust, "read_bytes", lambda p: (reads.append(p), real(p))[1])
    a = analysis.cache_path_for(png, tmp_path)
    b = analysis.cache_path_for(png, tmp_path)
    assert a == b and len(reads) == 1
    png.write_bytes(b"second, longer")        # new size/mtime: hashed again
    assert analysis.cache_path_for(png, tmp_path) != a and len(reads) == 2


def test_single_re_import_in_analysis():
    assert len(re.findall(r"^import re as _re$", (SRC_DIR / "core" / "analysis.py").read_text(), re.M)) == 1

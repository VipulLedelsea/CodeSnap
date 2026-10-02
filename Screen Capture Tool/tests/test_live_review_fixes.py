import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.model.ingest import validation_from_errors  # noqa: E402
from core.security.rules import pii_class  # noqa: E402
from core.uireview.screens import classify_observed  # noqa: E402


def test_unverified_language_is_not_a_failure():
    ok, text = validation_from_errors("Not verified: no HLASM compiler on this Mac; structure parsed, syntax left unverified")
    assert ok is None and text.startswith("Not verified")
    assert validation_from_errors("None") == (True, "")
    assert validation_from_errors("line 3: error")[0] is False


def test_pupil_counts_are_not_names():
    assert pii_class("ENT-PUPIL-UNITS") is None
    assert pii_class("PUPIL-COUNT") is None
    assert pii_class("PUPIL_NAME")[0] == "student / person name"


def test_observed_issues_map_to_wcag_and_security():
    rules = lambda s: {r[0] for r in classify_observed(s)}
    assert rules("Password field shows its value in plain text") == {"UIS-PWFIELD"}
    assert "ACC-CONTRAST" in rules("Hint text has very low contrast and can barely be read")
    assert "ACC-COLOR" in rules("Red text relies on color to show severity")
    assert rules("Vague link text 'click here'") == {"ACC-LINK"}
    assert rules("Header logo image is broken (placeholder shown)") == {"ACC-ALT"}
    assert rules("No required-field markers") == {"UIB-OBSERVED"}

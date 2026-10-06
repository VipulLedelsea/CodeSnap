"""Make the project modules importable from the tests/ folder, and keep the suite hermetic."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

@pytest.fixture(autouse=True)
def _no_pdf_conversion(monkeypatch, request):
    """Report packaging would otherwise launch LibreOffice / Word (up to 4 minutes) in every test that builds a
    package. Tests that need the real conversion can use @pytest.mark.real_pdf."""
    if request.node.get_closest_marker("real_pdf"):
        return
    import core.report as report
    monkeypatch.setattr(report, "pdf_from_docx", lambda docx: None)


def need_fixture(path, what=None):
    """Skip the running test when an untracked fixture is absent (tests/fixtures and tests/real are not in the
    repository). Does nothing but an existence check, so it is safe to call from fixtures."""
    p = Path(path)
    if not p.exists():
        pytest.skip(f"fixture {what or p.name} is not present in this checkout ({p})")
    return p


def pytest_configure(config):
    config.addinivalue_line("markers", "real_pdf: let the test run the real LibreOffice / Word PDF conversion")

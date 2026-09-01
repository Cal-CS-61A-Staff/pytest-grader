import subprocess
import sys


def test_first_failed_only_with_multiple_failures(tmp_path):
    """Test that --first-failed-only shows only the first failure's output."""
    # Create a test file with multiple failures in a temp directory
    (tmp_path / "test_fails.py").write_text('''
from pytest_grader import points

@points(1)
def test_pass():
    assert True

@points(2)
def test_first_fail():
    assert False, "First failure message"

@points(3)
def test_second_fail():
    assert False, "Second failure message"

@points(4)
def test_third_fail():
    assert False, "Third failure message"
''')

    # Run pytest with --first-failed-only, explicitly loading the plugin
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_fails.py", "-v", "--first-failed-only",
         "-p", "pytest_grader.plugins"],
        capture_output=True,
        text=True,
        cwd=tmp_path
    )

    output = result.stdout + result.stderr  # pytest sends output to stdout and stderr

    # Check that all tests were run (counts should be correct)
    assert "3 failed, 1 passed" in output

    # Check that subsequent failures don't show detailed output
    failure_sections = output.split("FAILURES")[1] if "FAILURES" in output else ""

    # Should have detailed output for first failure
    assert "assert False, \"First failure message\"" in failure_sections

    # Should NOT have detailed output for subsequent failures
    assert "assert False, \"Second failure message\"" not in failure_sections
    assert "assert False, \"Third failure message\"" not in failure_sections

import os
import subprocess
import sys


SLOW_TESTS = '''
from pytest_grader import points

@points(1)
def test_ok():
    assert 1 + 1 == 2

@points(2)
def test_spins():
    while True:
        pass

@points(1)
def spin():
    """
    >>> spin()
    """
    while True:
        pass

@points(1)
def test_still_runs():
    assert True
'''


def run_pytest(tmp_path, args, env=None):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "-p", "pytest_grader.plugins"] + args,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=60,  # Backstop so a broken timeout hangs this test, not the suite
    )
    return result.stdout + result.stderr  # pytest sends output to stdout and stderr


def check_timeout_run(tmp_path, env=None):
    (tmp_path / "test_slow.py").write_text(SLOW_TESTS)
    output = run_pytest(tmp_path, ["test_slow.py", "--score", "--timeout", "1",
                                   "--doctest-modules"], env=env)

    # The function test and the doctest both time out; later tests still run
    assert "2 failed, 2 passed" in output
    assert "timed out after 1 seconds" in output
    assert "Total Score: 2/5" in output


def test_infinite_loops_time_out(tmp_path):
    """An infinite loop fails with a timeout and the rest of the run continues."""
    check_timeout_run(tmp_path)


def test_infinite_loops_time_out_without_sigalrm(tmp_path):
    """The timer-thread fallback used on Windows also interrupts infinite loops."""
    env = dict(os.environ, PYTEST_GRADER_FORCE_THREAD_TIMEOUT="1")
    check_timeout_run(tmp_path, env=env)


def test_passing_tests_unaffected(tmp_path):
    """The default timeout does not interfere with tests that finish."""
    (tmp_path / "test_quick.py").write_text('''
from pytest_grader import points

@points(1)
def test_quick():
    assert True
''')
    output = run_pytest(tmp_path, ["test_quick.py", "--score"])
    assert "1 passed" in output
    assert "timed out" not in output

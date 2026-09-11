"""A doctest string below other code is not a docstring, so it runs no tests and
scores no points, with no error at all. pytest-grader turns that silence into a
failing test. See find_broken_doctests and DoctestPositionPlugin."""
import os
import subprocess
import sys

from pytest_grader.lock_tests import BrokenDoctest, find_broken_doctests


def find(source):
    return find_broken_doctests(source, "sol.py")


# --- What gets flagged --------------------------------------------------------

def test_string_below_other_code():
    """The reported case: one stray line above the string means the function
    has no __doc__ at all."""
    assert find('''
def square_doctest():
    y = square(3)
    """
    >>> square(3)
    9
    """
''') == [BrokenDoctest("square_doctest", 4)]


def test_string_below_a_real_docstring():
    """A second string is not a docstring either, even when the function has a
    proper one above it."""
    assert find('''
def f():
    """A real docstring."""
    x = 1
    """
    >>> f()
    """
''') == [BrokenDoctest("f", 5)]


def test_method_in_a_class():
    assert find('''
class Account:
    def deposit_doctest(self):
        x = 1
        """
        >>> Account().deposit_doctest()
        """
''') == [BrokenDoctest("deposit_doctest", 5)]


def test_string_in_a_class_body():
    """A class docstring runs doctests too, so a string below code in a class
    body is broken the same way."""
    assert find('''
class Account_doctest:
    balance = 0
    """
    >>> Account_doctest.balance
    0
    """
''') == [BrokenDoctest("Account_doctest", 4)]


def test_nested_function():
    assert find('''
def outer():
    def inner_doctest():
        x = 1
        """
        >>> inner_doctest()
        """
''') == [BrokenDoctest("inner_doctest", 5)]


# --- What stays quiet ---------------------------------------------------------
# A check that cries wolf gets switched off, so these matter as much as the ones
# above.

def test_a_real_docstring_is_not_flagged():
    assert find('''
def square_doctest():
    """
    >>> square(3)
    9
    """
''') == []


def test_a_docstring_without_prompts_is_not_flagged():
    assert find('''
def helper():
    """Describe the helper. No doctest here."""
    return 1
''') == []


def test_a_string_assigned_to_a_variable_is_not_flagged():
    """It is used, not silently dropped."""
    assert find('''
def f():
    x = 1
    example = """
    >>> f()
    """
    return example
''') == []


def test_a_comment_is_not_flagged():
    assert find('''
def f():
    x = 1
    # >>> f()
    return x
''') == []


# --- End to end through pytest ------------------------------------------------

BROKEN = '''from pytest_grader import points

def square(x):
    return x * x

@points(5)
def cube_doctest():
    """
    >>> square(2) ** 3 // 8
    8
    """

@points(3)
def square_doctest():
    y = square(3)
    """
    >>> square(3)
    9
    """
'''

WORKING = '''def cube(x):
    return x * x * x

def cube_doctest():
    """
    >>> cube(2)
    8
    """
'''


def run_pytest(tmp_path, *args):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--doctest-modules", "-q",
         "-p", "pytest_grader.plugins", *args],
        capture_output=True, cwd=tmp_path,
        # The score report contains emoji: both ends of the pipe must use UTF-8.
        encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return result.returncode, result.stdout + result.stderr


def test_broken_doctest_fails_the_run(tmp_path):
    """Without this the run reports success and the question is simply absent."""
    (tmp_path / "hw.py").write_text(BROKEN)
    returncode, output = run_pytest(tmp_path)
    assert returncode != 0, output
    # Reported like any other Python error: type, message, file and line.
    assert "BrokenDoctestError" in output, output
    assert "doctest string is not the first statement in 'square_doctest'" in output, output
    assert "hw.py:16" in output, output


def test_the_score_is_honest(tmp_path):
    """The lost question is worth what it was declared to be worth. Without
    that, the total reads 5/5 directly above the word FAILED."""
    (tmp_path / "hw.py").write_text(BROKEN)
    returncode, output = run_pytest(tmp_path, "--score")
    assert returncode != 0, output
    assert "square_doctest   0/3" in output, output
    assert "Total Score: 5/8" in output, output


def test_other_files_still_run(tmp_path):
    """The failure is per file, so one bad file does not abort the session the
    way an error during collection would."""
    (tmp_path / "hw.py").write_text(BROKEN)
    (tmp_path / "other.py").write_text(WORKING)
    returncode, output = run_pytest(tmp_path)
    assert returncode != 0, output
    assert "1 failed, 2 passed" in output, output


def test_k_still_finds_it(tmp_path):
    """The failing test carries the function's own name, so a student checking
    one question gets the error instead of "no tests ran"."""
    (tmp_path / "hw.py").write_text(BROKEN)
    returncode, output = run_pytest(tmp_path, "-k", "square_doctest")
    assert returncode != 0, output
    assert "1 failed" in output, output
    assert "no tests ran" not in output, output

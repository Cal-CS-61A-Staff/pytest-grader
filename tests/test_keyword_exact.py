"""`-k NAME` selects NAME exactly, plus companion tests named NAME_* in other files."""
import subprocess
import sys

MODULE = '''
def product(x):
    """
    >>> product(1)
    1
    """
    return x

def product_using_accumulate(x):
    """
    >>> product_using_accumulate(2)
    2
    """
    return x
'''

COMPANION = '''
def product_syntax_check():
    """
    >>> 1 + 1
    2
    """
'''

def run(tmp_path, *args):
    (tmp_path / "hw.py").write_text(MODULE)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "__init__.py").write_text("")
    (tmp_path / "tests" / "product_syntax_check.py").write_text(COMPANION)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--doctest-modules", "-v", "-p", "pytest_grader.plugins",
         "hw.py", "tests", *args],
        capture_output=True, text=True, cwd=tmp_path)
    return result.stdout + result.stderr


def test_bare_word_selects_exact_and_companion(tmp_path):
    out = run(tmp_path, "-k", "product")
    assert "hw.py::hw.product PASSED" in out
    assert "product_syntax_check PASSED" in out  # companion in another file
    assert "product_using_accumulate PASSED" not in out  # same file as exact match
    assert "2 passed, 1 deselected" in out


def test_full_name_still_selects(tmp_path):
    out = run(tmp_path, "-k", "product_using_accumulate")
    assert "hw.py::hw.product_using_accumulate PASSED" in out
    assert "1 passed, 2 deselected" in out


def test_companion_selectable_by_its_own_name(tmp_path):
    out = run(tmp_path, "-k", "product_syntax_check")
    assert "1 passed, 2 deselected" in out


def test_partial_word_falls_back_to_substring(tmp_path):
    out = run(tmp_path, "-k", "prod")
    assert "3 passed" in out


def test_expression_is_untouched(tmp_path):
    out = run(tmp_path, "-k", "product and not using")
    assert "2 passed, 1 deselected" in out

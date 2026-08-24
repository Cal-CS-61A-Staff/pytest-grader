import doctest
import subprocess
import sys
import pytest
from pathlib import Path
from pytest_grader.lock_tests import (OutputPosition, lock_doctests_for_file, locked_hash,
                                      substitute_sentinel_outputs)
from pytest_grader.plugins import UnlockPlugin

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


def test_lock_command_output(tmp_path):
    """Test that pytest-grader lock command generates expected output file."""
    src_file = tmp_path / "lock.py"
    dst_file = tmp_path / "locked.py"
    src_file.write_text((EXAMPLES_DIR / "lock.py").read_text())

    # Run the lock command
    result = subprocess.run([
        sys.executable, "-m", "pytest_grader", "lock",
        str(src_file), str(dst_file)
    ], capture_output=True, text=True, cwd=Path(__file__).parent.parent)

    # Check that the command succeeded
    assert result.returncode == 0, f"Lock command failed with error: {result.stderr}"

    # Check that the output file was created
    assert dst_file.exists(), "Output file was not created"

    # Compare the generated and expected content
    generated_content = dst_file.read_text()
    expected_content = (EXAMPLES_DIR / "locked_expected.py").read_text()
    assert generated_content == expected_content, f"Generated content does not match expected.\nGenerated:\n{generated_content}\nExpected:\n{expected_content}"


def test_lock_unlock_roundtrip(tmp_path):
    """Test that locking and unlocking works correctly in a round-trip."""
    func_name = "test_func"
    src_file = tmp_path / "src.py"
    dst_file = tmp_path / "locked.py"
    src_file.write_text('''# LOCK
def test_func():
    """
    >>> square(10)
    100
    >>> add(2, 3)
    5
    >>> print("hello")
    hello
    """
''')

    # Step 1: Lock the file
    count = lock_doctests_for_file(src_file, dst_file)
    assert count == 3, f"Expected 3 locked outputs, got {count}"

    # Step 2: Extract the locked hashes
    locked_hashes = [locked_hash(line) for line in dst_file.read_text().split('\n')
                     if locked_hash(line)]
    assert len(locked_hashes) == 3, f"Expected 3 locked hashes, got {len(locked_hashes)}"

    # Step 3: Test unlocking with correct answers
    test_cases = [
        (0, "100"),    # First output: square(10) -> 100
        (1, "5"),      # Second output: add(2, 3) -> 5
        (2, "hello"),  # Third output: print("hello") -> hello
    ]

    for output_number, correct_answer in test_cases:
        pos = OutputPosition(func_name, output_number)
        expected_hash = pos.encode(correct_answer)
        actual_hash = locked_hashes[output_number]

        assert expected_hash == actual_hash, f"Round-trip failed for output {output_number}: expected hash {expected_hash}, got {actual_hash} for answer '{correct_answer}'"

    # Step 4: Test that wrong answers don't match
    wrong_hash = OutputPosition(func_name, 0).encode("999")  # Wrong answer for square(10)
    assert wrong_hash != locked_hashes[0], "Wrong answer should not match the locked hash"


def test_lock_decorated_function(tmp_path):
    """Test that `# LOCK` locks a decorated function, above or below the decorator."""
    src_file = tmp_path / "src.py"
    dst_file = tmp_path / "locked.py"
    src_file.write_text('''from pytest_grader import points

# LOCK
@points(1)
def marker_above_decorator():
    """
    >>> 1 + 1
    2
    """

@points(2)
# LOCK
def marker_below_decorator():
    """
    >>> 2 + 2
    4
    """
''')

    assert lock_doctests_for_file(src_file, dst_file) == 2
    locked_content = dst_file.read_text()
    assert locked_content.count("LOCKED:") == 2, "Both decorated functions should be locked"
    assert "# LOCK" not in locked_content, "LOCK comments should be removed"


def test_lock_preserves_blank_lines(tmp_path):
    """Test that locking removes only `# LOCK` lines and does not reformat the file."""
    source = '''def helper(x):
    return x + 1


# LOCK
def q1():
    """
    >>> helper(1)
    2
    """


def other():
    pass
'''
    src_file = tmp_path / "src.py"
    dst_file = tmp_path / "locked.py"
    src_file.write_text(source)

    lock_doctests_for_file(src_file, dst_file)

    hash_code = OutputPosition("q1", 0).encode("2")
    expected = source.replace("# LOCK\n", "").replace("    2\n", f"    LOCKED: {hash_code}\n")
    assert dst_file.read_text() == expected


def test_stray_lock_marker_raises(tmp_path):
    """Test that a `# LOCK` that does not precede a function fails loudly."""
    src_file = tmp_path / "src.py"
    dst_file = tmp_path / "locked.py"
    src_file.write_text('x = 1\n# LOCK\ny = 2\n')

    with pytest.raises(ValueError, match="does not precede a function"):
        lock_doctests_for_file(src_file, dst_file)
    assert not dst_file.exists(), "No output file should be written on failure"


def test_substitute_sentinel_outputs():
    """Test that FUNCTION output lines match any function value via ellipsis."""
    example = doctest.Example(source="make_adder(2)\n", want="    FUNCTION\n")
    substitute_sentinel_outputs(example)
    assert example.want == "    <function ...>\n"
    assert example.options[doctest.ELLIPSIS] is True

    # Other outputs are untouched
    example2 = doctest.Example(source="square(2)\n", want="4\n")
    substitute_sentinel_outputs(example2)
    assert example2.want == "4\n"
    assert doctest.ELLIPSIS not in example2.options

    # ERROR matches any exception message, and fails on ordinary output
    example3 = doctest.Example(source="1 / 0\n", want="    ERROR\n")
    substitute_sentinel_outputs(example3)
    assert example3.want == "    ERROR\n", "want is kept so non-error output fails"
    assert example3.exc_msg == "...\n"
    assert example3.options[doctest.ELLIPSIS] is True

    # NOTHING matches no displayed output
    example4 = doctest.Example(source="lst.append(2)\n", want="    NOTHING\n")
    substitute_sentinel_outputs(example4)
    assert example4.want == ""
    assert example4.exc_msg is None


def test_function_output_lock_unlock_roundtrip(tmp_path):
    """Test that FUNCTION outputs pass when unlocked, and unlock by typing FUNCTION."""
    src_file = tmp_path / "hof.py"
    src_file.write_text('''def make_adder(n):
    def adder(x):
        return x + n
    return adder

# LOCK
def adder_doctest():
    """
    >>> make_adder(2)
    FUNCTION
    >>> make_adder(2)(3)
    5
    """
''')
    (tmp_path / "grader.yaml").write_text('included_files:\n  - hof.py\n')
    pytest_cmd = [sys.executable, "-m", "pytest", "--doctest-modules", "-q",
                  "-p", "pytest_grader.plugins"]

    # The author's unlocked file passes: FUNCTION matches the returned adder
    result = subprocess.run(pytest_cmd + ["hof.py"], capture_output=True, text=True, cwd=tmp_path)
    assert "1 passed" in result.stdout, result.stdout

    # Lock the file; the locked tests are skipped
    locked_file = tmp_path / "hof_locked.py"
    lock_doctests_for_file(src_file, locked_file)
    result = subprocess.run(pytest_cmd + ["hof_locked.py"], capture_output=True, text=True, cwd=tmp_path)
    assert "1 skipped" in result.stdout, result.stdout

    # Typing FUNCTION unlocks the function-valued output
    result = subprocess.run(pytest_cmd + ["hof_locked.py", "--unlock"],
                            input="FUNCTION\n5\n", capture_output=True, text=True, cwd=tmp_path)
    assert "All tests unlocked" in result.stdout, result.stdout
    assert "1 passed" in result.stdout, result.stdout

    # The unlocked file keeps passing on later runs
    result = subprocess.run(pytest_cmd + ["hof_locked.py"], capture_output=True, text=True, cwd=tmp_path)
    assert "1 passed" in result.stdout, result.stdout


def test_sentinel_output_lock_unlock_roundtrip(tmp_path):
    """Test that ERROR and NOTHING outputs pass when unlocked, and unlock in any case."""
    src_file = tmp_path / "sentinels.py"
    src_file.write_text('''# LOCK
def sentinel_doctest():
    """
    >>> lst = [1]
    >>> lst.append(2)
    NOTHING
    >>> lst[5]
    ERROR
    >>> lst
    [1, 2]
    """
''')
    (tmp_path / "grader.yaml").write_text('included_files:\n  - sentinels.py\n')
    pytest_cmd = [sys.executable, "-m", "pytest", "--doctest-modules", "-q",
                  "-p", "pytest_grader.plugins"]

    # The author's unlocked file passes: NOTHING matches no output, ERROR the IndexError
    result = subprocess.run(pytest_cmd + ["sentinels.py"], capture_output=True, text=True, cwd=tmp_path)
    assert "1 passed" in result.stdout, result.stdout

    # Lock the file; the locked tests are skipped
    locked_file = tmp_path / "sentinels_locked.py"
    lock_doctests_for_file(src_file, locked_file)
    result = subprocess.run(pytest_cmd + ["sentinels_locked.py"], capture_output=True, text=True, cwd=tmp_path)
    assert "1 skipped" in result.stdout, result.stdout

    # Sentinel answers unlock in any case (lowercase here)
    result = subprocess.run(pytest_cmd + ["sentinels_locked.py", "--unlock"],
                            input="nothing\nerror\n[1, 2]\n", capture_output=True, text=True, cwd=tmp_path)
    assert "All tests unlocked" in result.stdout, result.stdout
    assert "1 passed" in result.stdout, result.stdout

    # The unlocked file keeps passing on later runs
    result = subprocess.run(pytest_cmd + ["sentinels_locked.py"], capture_output=True, text=True, cwd=tmp_path)
    assert "1 passed" in result.stdout, result.stdout


def test_error_sentinel_requires_exception(tmp_path):
    """Test that an example expecting ERROR fails when no exception is raised."""
    src_file = tmp_path / "no_error.py"
    src_file.write_text('''def no_error_doctest():
    """
    >>> 1 + 1
    ERROR
    """
''')
    (tmp_path / "grader.yaml").write_text('included_files:\n  - no_error.py\n')
    result = subprocess.run([sys.executable, "-m", "pytest", "--doctest-modules", "-q",
                             "-p", "pytest_grader.plugins", "no_error.py"],
                            capture_output=True, text=True, cwd=tmp_path)
    assert "1 failed" in result.stdout, result.stdout


def test_unlock_plugin_substitution():
    """Test that UnlockPlugin correctly substitutes locked outputs with unlocked values."""
    func_name = "test_func"
    correct_answer = "42"
    output_number = 0

    # Generate the expected hash
    pos = OutputPosition(func_name, output_number)
    expected_hash = pos.encode(correct_answer)

    # Create a mock doctest example with locked output
    example1 = doctest.Example(
        source="calculate()",
        want=f"LOCKED: {expected_hash}\n"
    )

    # Create keys dict with the hash and correct answer
    keys = {expected_hash: correct_answer}
    plugin = UnlockPlugin(keys)
    all_unlocked = plugin._unlock_doctest_output(example1)
    assert all_unlocked, "Examples are not all unlocked but should be."
    assert example1.want == f"{correct_answer}\n", f"Expected '{correct_answer}\\n', got '{example1.want}'"


def test_unlock_plugin_skipping_locked_test():
    """Test that UnlockPlugin correctly skips locked doctests with no keys."""
    unknown_hash = "unknown_hash_123"

    # Create a mock doctest example with unknown locked output
    example2 = doctest.Example(
        source="unknown_function()",
        want=f"LOCKED: {unknown_hash}\n"
    )

    # Test with a plugin that has no keys.
    plugin = UnlockPlugin({})
    all_unlocked = plugin._unlock_doctest_output(example2)
    assert not all_unlocked, "Examples are all unlocked but should not be."
    assert example2.want == f"LOCKED: {unknown_hash}\n", f"Expected 'LOCKED: {unknown_hash}\\n', got '{example2.want}'"


def test_lock_validation_functions_without_doctests(tmp_path):
    """Test that lock_doctests_for_file validates functions have doctests."""
    src_file = tmp_path / "test_validation.py"
    dst_file = tmp_path / "test_validation_locked.py"

    # Create a file with a locked function that has no doctests
    src_file.write_text('''# LOCK
def function_without_doctests():
    """This function has no doctests."""
    return 42
''')

    # Should raise ValueError for function without doctests
    with pytest.raises(ValueError, match="Locked function 'function_without_doctests' must have at least one doctest in its docstring"):
        lock_doctests_for_file(src_file, dst_file)


def test_lock_validation_functions_without_docstring(tmp_path):
    """Test that lock_doctests_for_file validates functions have docstrings."""
    src_file = tmp_path / "test_validation.py"
    dst_file = tmp_path / "test_validation_locked.py"

    # Create a file with a locked function that has no docstring
    src_file.write_text('''# LOCK
def function_without_docstring():
    return 42
''')

    # Should raise ValueError for function without docstring
    with pytest.raises(ValueError, match="Locked function 'function_without_docstring' must have a docstring with at least one doctest"):
        lock_doctests_for_file(src_file, dst_file)


def test_lock_validation_success_with_valid_doctests(tmp_path):
    """Test that lock_doctests_for_file succeeds with valid doctests."""
    src_file = tmp_path / "test_validation.py"
    dst_file = tmp_path / "test_validation_locked.py"

    # Create a file with valid locked functions that have doctests
    src_file.write_text('''# LOCK
def function_with_doctests():
    """This function has doctests.

    >>> function_with_doctests()
    42
    """
    return 42

# LOCK
def another_function_with_doctests():
    """Another function with doctests.

    >>> another_function_with_doctests()
    123
    >>> print("test")
    test
    """
    return 123
''')

    # Should succeed without raising any exceptions
    lock_doctests_for_file(src_file, dst_file)

    # Check that the output file was created
    assert dst_file.exists(), "Output file was not created"

    # Verify the locked content contains LOCKED hashes
    locked_content = dst_file.read_text()
    assert "LOCKED:" in locked_content, "Locked content should contain LOCKED hashes"
    assert "# LOCK" not in locked_content, "LOCK comments should be removed"


def test_selective_function_locking(tmp_path):
    """Test that only functions with # LOCK annotation are locked, not all functions."""
    src_file = tmp_path / "test_selective.py"
    dst_file = tmp_path / "test_selective_locked.py"

    # Create a file with one locked function and one unlocked function
    src_file.write_text('''# LOCK
def locked_function():
    """This function should be locked.

    >>> locked_function()
    42
    """
    return 42

def unlocked_function():
    """This function should NOT be locked.

    >>> unlocked_function()
    123
    """
    return 123
''')

    # Lock the file
    lock_doctests_for_file(src_file, dst_file)
    locked_content = dst_file.read_text()
    lines = locked_content.split('\n')

    assert 'def locked_function():' in locked_content, "locked_function should be found in output"
    assert 'def unlocked_function():' in locked_content, "unlocked_function should be found in output"
    assert locked_content.count("LOCKED:") == 1, "Exactly one output should be locked"

    # The locked function's output is replaced; the unlocked function's is preserved
    assert not any(line.strip() == '42' for line in lines), "Original output '42' should be replaced with LOCKED:"
    assert any(line.strip() == '123' for line in lines), "Original output '123' should be preserved in unlocked function"
import pytest
import tempfile
import os
from pytest_grader.logger import SQLLogger


@pytest.fixture
def temp_db():
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    os.unlink(db_path)


@pytest.fixture
def temp_file():
    """Create a temporary file for testing snapshot functionality."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write("def test_function():\n    return 42\n")
        file_path = f.name
    yield file_path
    os.unlink(file_path)


@pytest.fixture
def logger(temp_db, temp_file):
    """Create a SQLLogger instance with a temporary database and test file."""
    assignment_info = {'included_files': [temp_file]}
    return SQLLogger(temp_db, assignment_info)


def test_start_session(logger):
    """Test that start_session records the command with a timestamp."""
    logger.start_session("pytest -k test_example --score")

    logger.cursor.execute("SELECT id, command, timestamp FROM sessions")
    session_id, command, timestamp = logger.cursor.fetchone()
    assert command == "pytest -k test_example --score"
    assert timestamp is not None
    assert logger.current_session == session_id


def test_snapshot(logger, temp_file):
    """Test the snapshot method stores file contents linked to the session."""
    logger.start_session("pytest")
    logger.snapshot()

    # Check that the file content was stored
    logger.cursor.execute("SELECT COUNT(*) FROM files")
    assert logger.cursor.fetchone()[0] == 1

    # Check that the file is linked to the session
    logger.cursor.execute("SELECT session_id, filename FROM snapshot_files")
    assert logger.cursor.fetchone() == (logger.current_session, temp_file)


def test_snapshot_deduplicates_content(logger):
    """Test that identical file contents are stored only once across sessions."""
    logger.start_session("pytest")
    logger.snapshot()
    logger.start_session("pytest --score")
    logger.snapshot()

    logger.cursor.execute("SELECT COUNT(*) FROM files")
    assert logger.cursor.fetchone()[0] == 1

    logger.cursor.execute("SELECT COUNT(*) FROM snapshot_files")
    assert logger.cursor.fetchone()[0] == 2


def test_test_case(logger):
    """Test the test_case method stores test case results."""
    logger.start_session("pytest")

    logger.test_case("test_example", True, "AI response here")

    logger.cursor.execute("SELECT session_id, name, passed, response FROM test_cases")
    result = logger.cursor.fetchone()
    assert result == (logger.current_session, "test_example", True, "AI response here")


def test_unlock_attempt(logger):
    """Test the unlock_attempt method stores unlock attempts."""
    logger.start_session("pytest --unlock")

    logger.unlock_attempt("test_unlock", 0, "my guess", False, "AI response")

    logger.cursor.execute("SELECT session_id, name, guess, success, response FROM unlock_attempts")
    result = logger.cursor.fetchone()
    assert result == (logger.current_session, "test_unlock[0]", "my guess", False, "AI response")

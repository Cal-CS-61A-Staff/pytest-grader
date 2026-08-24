import importlib
import shlex
import sys

import pytest
import yaml

from .lock_tests import (LOCKED_PREFIX, locked_hash, replace_output,
                         run_unlock_interactive, substitute_sentinel_outputs)
from .logger import SQLLogger
from sqlitedict import SqliteDict


def get_points(item: pytest.Item) -> int:
    """The point value of a test item (0 unless assigned with @points)."""
    if isinstance(item, pytest.Function):
        return getattr(item.function, 'points', 0)
    elif isinstance(item, pytest.DoctestItem):
        # For doctests, points are assigned to the enclosing function
        func_name = item.dtest.name.split('.')[-1]
        func = item.dtest.globs.get(func_name)
        return getattr(func, 'points', 0)
    return 0


class ScorerPlugin:
    def __init__(self):
        self.points = {}
        self.test_results = []

    def pytest_collection_modifyitems(self, session, config, items):
        # Store points for all items during collection, before any can be skipped
        for item in items:
            points = get_points(item)
            if points > 0:
                self.points[item.nodeid] = points

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or (report.when == "setup" and report.outcome == "skipped"):
            self.test_results.append(report)

    def pytest_terminal_summary(self, terminalreporter, exitstatus, config):
        if config.getoption("--score"):
            self.write_score_report(terminalreporter.write_line)

    def write_score_report(self, write_line):
        total_earned = 0
        total_points = 0

        rows = []
        for report in self.test_results:
            if report.nodeid in self.points:
                points = self.points[report.nodeid]
                earned = points if report.outcome == 'passed' else 0
                total_points += points
                total_earned += earned
                test_name = report.nodeid.split("::")[-1]
                emoji = {'passed': '✅', 'skipped': '⏭️'}.get(report.outcome, '❌')
                rows.append((emoji, test_name, str(earned), str(points)))

        # Pad each column to its widest entry so that all the / marks line up.
        name_width = max((len(row[1]) for row in rows), default=0)
        earned_width = max((len(row[2]) for row in rows), default=0)
        points_width = max((len(row[3]) for row in rows), default=0)
        # Two leading spaces, a double-width emoji, and a space precede the name.
        rule_width = max(40, 5 + name_width + 2 + earned_width + 1 + points_width)

        write_line('═' * rule_width)
        for emoji, test_name, earned, points in rows:
            write_line(f"  {emoji} {test_name:<{name_width}}  "
                       f"{earned:>{earned_width}}/{points:<{points_width}}")

        # The total covers only the tests that ran, so a subset run (e.g. -k)
        # still shows a total for the selected tests.
        percentage = 0.0 if total_points == 0 else round(100.0 * total_earned / total_points, 1)
        decoration = ""
        if total_earned == total_points and total_points > 0:
            percentage = "💯"
            decoration = "✨"

        write_line('─' * rule_width)
        write_line(f"  {decoration}Total Score: {total_earned}/{total_points}"
                   f" ({percentage}%){decoration}")


class UnlockPlugin:
    def __init__(self, keys: dict[str, str], logger: SQLLogger | None = None):
        self.unlock_mode = False
        self.keys = keys
        self.logger = logger

    def pytest_configure(self, config):
        self.unlock_mode = config.getoption("--unlock")

    # trylast so that this runs after the hooks that deselect items for -k, -m,
    # and --deselect; otherwise items still holds every collected test.
    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, session, config, items):
        if self.unlock_mode:
            # Temporarily disable pytest's output capturing for interactive input
            capmanager = config.pluginmanager.getplugin('capturemanager')
            if capmanager:
                capmanager.suspend_global_capture(in_=True)
            try:
                run_unlock_interactive(items, self.keys, self.logger)
            finally:
                if capmanager:
                    capmanager.resume_global_capture()

    def pytest_runtest_setup(self, item):
        if isinstance(item, pytest.DoctestItem):
            all_unlocked = True
            for example in item.dtest.examples:
                if LOCKED_PREFIX in example.want:
                    all_unlocked = self._unlock_doctest_output(example) and all_unlocked
                substitute_sentinel_outputs(example)

            if not all_unlocked:
                test_name = item.dtest.name.split('.')[-1]
                lock_warning = f"{test_name} still has locked examples. To unlock them, run pytest with --unlock."
                print(lock_warning)
                pytest.skip(lock_warning)

    def _unlock_doctest_output(self, example):
        """Substitute known unlocked outputs into an example's expected output.

        Return whether every locked line was unlocked."""
        lines = example.want.split('\n')
        all_unlocked = True

        for i, line in enumerate(lines):
            hash_code = locked_hash(line)
            if hash_code is None:
                continue
            if hash_code in self.keys:
                lines[i] = replace_output(line, self.keys[hash_code])
            else:
                all_unlocked = False

        example.want = '\n'.join(lines)
        return all_unlocked


class LoggerPlugin:
    def __init__(self, logger: SQLLogger):
        self.logger = logger

    def pytest_configure(self, config):
        # invocation_params.args holds the arguments pytest actually received,
        # even when pytest is launched programmatically (e.g. VS Code's test pane),
        # where sys.argv belongs to the wrapper script instead.
        command = shlex.join(["pytest", *config.invocation_params.args])
        self.logger.start_session(command)
        # Take a snapshot of the code early, before any unlocking happens
        self.logger.snapshot()

    def pytest_runtest_logreport(self, report):
        # Log test cases when they complete (call phase)
        if report.when == "call":
            test_name = report.nodeid.split("::")[-1]
            passed = report.outcome == "passed"
            response = None  # Could be enhanced to capture output/errors
            self.logger.test_case(test_name, passed, response)


class IsolationPlugin:
    """Isolate tests from each other's side effects."""

    def __init__(self, reload_modules: list[str]):
        self.reload_modules = reload_modules

    def pytest_runtest_setup(self, item):
        # Reload the modules listed under reload_modules in grader.yaml so that
        # changes made by one test (e.g. monkeypatching) don't leak into later tests.
        for name in self.reload_modules:
            module = sys.modules.get(name)
            if module is not None:
                importlib.reload(module)
                # A doctest's globals were copied from the module at collection
                # time, so after a reload they still hold the old objects. Mixing
                # old and new definitions breaks class identity (e.g. a reloaded
                # Link's isinstance check rejects a pre-reload Link instance), so
                # rebuild the globals from the reloaded module.
                if (isinstance(item, pytest.DoctestItem)
                        and item.dtest.globs.get('__name__') == module.__name__):
                    item.dtest.globs = dict(module.__dict__)

        # Remove globals injected by pytest's assertion rewriting (@py_builtins,
        # @pytest_ar) so doctests that introspect their namespace don't see them.
        if isinstance(item, pytest.DoctestItem):
            for name in [n for n in item.dtest.globs if n.startswith('@')]:
                del item.dtest.globs[name]


class FirstFailedOnlyPlugin:
    def __init__(self):
        self.first_failed_only = False
        self.failure_shown = False

    def pytest_configure(self, config):
        self.first_failed_only = config.getoption("--first-failed-only")

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(self, item, call):
        report = yield
        if self.first_failed_only and report.when == "call" and report.failed:
            if self.failure_shown:
                # Suppress the traceback and captured output of later failures
                report.longrepr = None
                report.sections = []
            else:
                self.failure_shown = True
        return report

    def pytest_terminal_summary(self, terminalreporter, exitstatus, config):
        # Add custom summary when first-failed-only is used
        failed = len(terminalreporter.stats.get('failed', []))
        if self.first_failed_only and failed > 1:
            passed = len(terminalreporter.stats.get('passed', []))
            skipped = len(terminalreporter.stats.get('skipped', []))
            terminalreporter.write_line("")
            terminalreporter.write_line("=" * 70)
            terminalreporter.write_line("NOTE: --first-failed-only was used. Only the first failed test output was shown.")
            terminalreporter.write_line(f"Total: {passed} passed, {failed} failed"
                                        + (f", {skipped} skipped" if skipped > 0 else ""))


def pytest_addoption(parser):
    parser.addoption(
        "--score", "-S", action="store_true", default=False,
        help="Show score report after running tests"
    )
    parser.addoption(
        "--unlock", "-U", action="store_true", default=False,
        help="Unlock locked doctests interactively"
    )
    parser.addoption(
        "--grader-db", action="store", default="grader.sqlite",
        help="Grader database file (default: grader.sqlite)"
    )
    parser.addoption(
        "--assignment", action="store", default="grader.yaml",
        help="Assignment configuration file (default: grader.yaml)"
    )
    parser.addoption(
        "--first-failed-only", action="store_true", default=False,
        help="Run all tests but only show output for the first failed test"
    )


def pytest_configure(config):
    # Ensure that skipped tests display a reason
    if 's' not in (config.option.reportchars or ''):
        config.option.reportchars = (config.option.reportchars or '') + 's'

    if config.getoption("--collect-only"):
        return  # Nothing runs, so don't create or update the grader database

    # Read assignment configuration
    assignment_file = config.getoption("--assignment")
    try:
        with open(assignment_file, 'r') as f:
            assignment_conf = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise pytest.UsageError(
            f"pytest-grader could not find the assignment configuration file '{assignment_file}'. "
            "Run pytest from the assignment directory or pass --assignment.")
    grader_db = config.getoption("--grader-db")

    # Store configuration in grader_db
    conf = SqliteDict(grader_db, tablename="conf", autocommit=True)
    for k, v in assignment_conf.items():
        conf[k] = v

    # Create shared services
    logger = SQLLogger(grader_db, conf)
    unlock_keys = SqliteDict(grader_db, tablename="unlock_keys", autocommit=True)

    # Register plugins
    config.pluginmanager.register(ScorerPlugin(), "pytest-grader-scorer")
    config.pluginmanager.register(UnlockPlugin(unlock_keys, logger), "pytest-grader-unlock")
    config.pluginmanager.register(LoggerPlugin(logger), "pytest-grader-logger")
    config.pluginmanager.register(IsolationPlugin(assignment_conf.get('reload_modules', [])),
                                  "pytest-grader-isolation")
    config.pluginmanager.register(FirstFailedOnlyPlugin(), "pytest-grader-first-failed-only")

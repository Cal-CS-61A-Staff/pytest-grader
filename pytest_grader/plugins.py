import importlib
import json
import os
import signal
import sys
import threading
import _thread

import pytest

from .lock_tests import (LOCKED_PREFIX, UnlockKeys, locked_hash, replace_output,
                         run_unlock_interactive, substitute_sentinel_outputs)


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
    def __init__(self, keys: dict[str, str]):
        self.unlock_mode = False
        self.keys = keys

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
                run_unlock_interactive(items, self.keys)
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


class IsolationPlugin:
    """Isolate tests from each other's side effects."""

    def __init__(self, reload_modules: list[str]):
        self.reload_modules = reload_modules

    def pytest_runtest_setup(self, item):
        # Reload the modules listed under reload_modules in grader.json so that
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


class TestTimeout(BaseException):
    """Raised when a test exceeds its time limit.

    A BaseException so that student code catching Exception cannot swallow it.
    """


class TimeoutPlugin:
    """Fail any test whose call phase runs longer than the --timeout limit.

    On Unix, a SIGALRM interrupts the test. Elsewhere (e.g. Windows), a timer
    thread interrupts the main thread with a simulated Ctrl-C instead. Either
    way only the hung test fails; the rest of the run continues. Code that
    never returns to the Python interpreter loop (a blocked C call such as
    input()) cannot be interrupted by either mechanism.
    """

    def __init__(self):
        self.limit = 0

    def pytest_configure(self, config):
        # A timeout would kill an interactive debugging session mid-test.
        if not config.getoption("usepdb"):
            self.limit = config.getoption("--timeout")

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(self, item):
        limit = self.limit
        if not limit or limit <= 0:
            return (yield)

        timed_out = False
        use_sigalrm = (hasattr(signal, "SIGALRM")
                       and threading.current_thread() is threading.main_thread()
                       and not os.environ.get("PYTEST_GRADER_FORCE_THREAD_TIMEOUT"))

        if use_sigalrm:
            def handler(signum, frame):
                nonlocal timed_out
                timed_out = True
                raise TestTimeout()
            old_handler = signal.signal(signal.SIGALRM, handler)
            signal.setitimer(signal.ITIMER_REAL, limit)
        else:
            finished = threading.Event()
            def fire():
                nonlocal timed_out
                if not finished.is_set():
                    timed_out = True
                    _thread.interrupt_main()
            timer = threading.Timer(limit, fire)
            timer.daemon = True
            timer.start()

        try:
            result = yield
        except (TestTimeout, KeyboardInterrupt):
            if not timed_out:
                raise  # A real Ctrl-C still aborts the whole run.
            pytest.fail(f"Test timed out after {limit:g} seconds -- "
                        "check for an infinite loop.", pytrace=False)
        finally:
            if use_sigalrm:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old_handler)
            else:
                finished.set()
                timer.cancel()
        return result


def pytest_collection_modifyitems(config, items):
    """Narrow `-k NAME` from a substring match to an exact match when NAME is a
    bare identifier. Since a doctest item is named `<module>.<function>`, NAME
    is compared to the function name.

    An item named `NAME_<suffix>` (e.g. `a_plus_abs_b_syntax_check`) is also
    selected when it lives in a different file from the exact match.

    If nothing matches exactly, pytest's usual substring behavior applies.
    """
    name = config.option.keyword
    if not name or not name.isidentifier():
        return

    def base_name(item):
        return getattr(item, "originalname", None) or item.name.rsplit(".", 1)[-1]

    exact = [item for item in items if base_name(item) == name]
    if not exact:
        return
    exact_files = {item.path for item in exact}
    selected = [item for item in items if item in exact or
                (item.path not in exact_files and base_name(item).startswith(name + "_"))]
    if len(selected) < len(items):
        config.hook.pytest_deselected(items=[item for item in items if item not in selected])
        items[:] = selected


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
        "--unlock-file", action="store", default=".unlocked.json",
        help="File storing unlocked doctest outputs (default: .unlocked.json)"
    )
    parser.addoption(
        "--assignment", action="store", default="grader.json",
        help="Assignment configuration file (default: grader.json)"
    )
    parser.addoption(
        "--first-failed-only", action="store_true", default=False,
        help="Run all tests but only show output for the first failed test"
    )
    parser.addoption(
        "--timeout", action="store", type=float, default=10,
        help="Per-test timeout in seconds; 0 disables (default: 10)"
    )


def pytest_configure(config):
    # Ensure that skipped tests display a reason
    if 's' not in (config.option.reportchars or ''):
        config.option.reportchars = (config.option.reportchars or '') + 's'

    if config.getoption("--collect-only"):
        return  # Nothing runs (e.g. IDE test discovery)

    # Read the assignment configuration, if any
    try:
        with open(config.getoption("--assignment"), 'r') as f:
            assignment_conf = json.load(f)
    except FileNotFoundError:
        assignment_conf = {}

    unlock_keys = UnlockKeys(config.getoption("--unlock-file"))

    # Register plugins
    config.pluginmanager.register(ScorerPlugin(), "pytest-grader-scorer")
    config.pluginmanager.register(UnlockPlugin(unlock_keys), "pytest-grader-unlock")
    config.pluginmanager.register(IsolationPlugin(assignment_conf.get('reload_modules', [])),
                                  "pytest-grader-isolation")
    config.pluginmanager.register(FirstFailedOnlyPlugin(), "pytest-grader-first-failed-only")
    config.pluginmanager.register(TimeoutPlugin(), "pytest-grader-timeout")

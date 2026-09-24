# pytest-grader

A pytest plugin for testing and scoring programming assignments.

## Features

- **Assignment Scoring**
  - Add point values to test functions using the `@points(n)` decorator
  - Show a score summary when running `pytest --score`
- **Test Locking** as described in Basu et al., *Automated Problem Clarification at Scale* ([abstract](https://dl.acm.org/doi/10.1145/2724660.2724679), [pdf](http://denero.org/content/pubs/las15_basu_unlocking.pdf))
  - Lock doctests using the `# LOCK` comment before the function.
  - `pytest-grader lock [src] [dst]` will generate a copy of src with doctests locked.
  - `pytest --unlock` provides an interactive interface for unlocking locked doctests.
    Unlocking does not run any tests: a student unlocks before writing the code, so
    running the tests then would only show failures. Instead, every test is reported as
    skipped, and `--score` shows no score report. Run `pytest` again to test the code.
  - Doctests are ordinary doctests that pass under `python3 -m doctest`: an expected
    exception is written as its traceback, and a function value as its repr with
    ellipsis matching for the address, e.g.
    `>>> make_adder(2)  # doctest: +ELLIPSIS` / `<function make_adder.<locals>.adder at 0x...>`.
  - Locking asks for what a student can predict: a traceback of any length is one
    answer, `ERROR`, and each function value is `FUNCTION`. When unlocking, type those
    (in any case). Directive comments are not shown. `expected_outputs(example)` gives
    the answers a locked example asks for, so tooling can show one blank per answer.
  - When unlocking, a string answer may be quoted with either single or double quotes
    (e.g. `"hello"` unlocks an expected `'hello'`); the canonical form Python displays
    is recorded. An answer wrong only in its presence or absence of quotes is not
    accepted, but earns a hint saying so.
  - Unlocked outputs are saved in `.unlocked.json` (see `--unlock-file`) so that
    tests stay unlocked across pytest runs.
- **Test Isolation**
  - Modules listed under `reload_modules` in `grader.json` are reloaded before each
    test, so a test that mutates a module (e.g. by monkeypatching one of its
    functions) does not affect later tests.
  - Globals injected by pytest's assertion rewriting (`@py_builtins`, `@pytest_ar`)
    are removed from doctest namespaces.
- **Test Timeouts**
  - Each test (including each doctest) is limited to 10 seconds, so an infinite
    loop fails that test with a clear message instead of hanging the run. The
    remaining tests still run and are scored.
  - Adjust the limit with `--timeout SECONDS`; `--timeout 0` disables it. The
    timeout is also disabled under `--pdb`.
  - Code blocked outside the Python interpreter (e.g. waiting on `input()` or a
    hung C call) cannot be interrupted; pure-Python loops always time out.

## Usage

Include a `conftest.py` file in the distribution of your assignment that contains `pytest_plugins = ["pytest_grader"]`.

Optionally describe the assignment in a `grader.json` file next to it:

```json
{
  "reload_modules": ["hog"]
}
```

`reload_modules` lists modules reloaded before each test for isolation.

See the `examples` directory for more usage info.

## License

[MIT](LICENSE)

## Updating versions

- Change version in `pyproject.toml`
- `uv build`
- `uv publish`
If your pypi credentials are in `~/.pypirc`, then instead run `uvx uv-publish`.
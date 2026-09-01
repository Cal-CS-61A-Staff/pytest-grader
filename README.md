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
  - A doctest whose output is a function should give `FUNCTION` as the expected output,
    which matches any function value. When unlocking, type `FUNCTION` for such outputs.
  - A doctest that raises an exception should give `ERROR` as its entire expected
    output, which matches any raised exception (and fails if none is raised).
  - A doctest statement that displays nothing (e.g. `lst.append(2)`) may give `NOTHING`
    as its expected output, so that unlocking still asks about it.
  - When unlocking, sentinel answers (`FUNCTION`, `ERROR`, `NOTHING`) may be typed in
    any case.
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
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
- **Test Isolation**
  - Modules listed under `reload_modules` in `grader.yaml` are reloaded before each
    test, so a test that mutates a module (e.g. by monkeypatching one of its
    functions) does not affect later tests.
  - Globals injected by pytest's assertion rewriting (`@py_builtins`, `@pytest_ar`)
    are removed from doctest namespaces.
- **Progress Logging**
  - Each pytest session is recorded in a `grader.sqlite` database: the pytest command (`pytest` plus the arguments pytest received, however it was launched), a timestamp, and snapshots of the assignment files at that time.
  - Test case results and unlocking attempts are stored there as well, linked to their session's snapshot.
  - This file is designed to be submitted along with the assignment as a record of how the assignment was completed.

## Usage

Include a `conftest.py` file in the distribution of your assignment that contains `pytest_plugins = ["pytest_grader"]`.

Describe the assignment in a `grader.yaml` file next to it:

```yaml
included_files:   # Files snapshotted into grader.sqlite when tests run
  - hog.py
reload_modules:   # Modules reloaded before each test for isolation
  - hog
```

See the `examples` directory for more usage info.

## License

[MIT](LICENSE)

## Updating versions

- Change version in `pyproject.toml`
- `uv build`
- `uv publish`
If your pypi credentials are in `~/.pypirc`, then instead run `uvx uv-publish`.
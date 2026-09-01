# Examples

## Score Reports

Run these commands to try out the score reporting feature:

- `pytest --score partial_credit.py`
- `pytest --score full_credit.py`

## Locked Doctests

Run these commands to try out the test locking feature:

(1) Confirm that tests in `lock.py` pass

`pytest --doctest-modules lock.py`

(2) Generate a locked test file.

`pytest-grader lock lock.py locked.py`

(3) Confirm that tests in `locked.py` are skipped because they are locked.

`pytest --doctest-modules locked.py`

(4) Interactively unlock the tests and then confirm that they pass.

`pytest --doctest-modules --unlock locked.py`

Unlocking progress is saved in `.unlocked.json`. Remove that file to start again.

## Full assignments

(Coming soon) See the `cs61a` directory for example assignments that use `pytest-grader`.
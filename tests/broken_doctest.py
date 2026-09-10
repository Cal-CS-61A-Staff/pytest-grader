"""A doctest string only counts as a docstring when it is the function's first
statement. This file shows what happens when it isn't. It is a demo to run by
hand, not part of the test suite, so a normal pytest run ignores it.

    pytest --doctest-modules --score tests/broken_doctest.py -p pytest_grader.plugins

square_doctest is worth 3 points and never runs, so without this check the
score would read 5/5. Add -p no:pytest-grader-doctest-position to see that
old behavior. Delete the `y = square(3)` line and run again: the failure
disappears on its own and the score becomes 8/8.
"""
from pytest_grader import points

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
    y = square(3)          # this line hides the doctest below it
    """
    >>> square(3)
    9
    """

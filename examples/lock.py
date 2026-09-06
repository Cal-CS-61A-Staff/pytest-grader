from pytest_grader import points

def square(x):
    return x*x

def make_adder(n):
    def adder(x):
        return x + n
    return adder

# LOCK
@points(1)
def adder_doctest():
    """
    >>> make_adder(2)  # doctest: +ELLIPSIS
    <function make_adder.<locals>.adder at 0x...>
    >>> make_adder(2)(3)
    5
    """

# LOCK
@points(1)
def times_doctest():
    """
    >>> x = 10
    >>> x * 2
    20
    """

# LOCK
@points(1)
def square_doctest():
    """
    >>> x = 10
    >>> square(x)
    100
    >>> print(print(10),
    ...       square(10))
    10
    None 100
    """

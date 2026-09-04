"""A pytest plugin for testing and scoring programming assignments."""

from .decorators import points
from .plugins import pytest_addoption, pytest_collection_modifyitems, pytest_configure

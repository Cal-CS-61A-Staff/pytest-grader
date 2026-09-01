"""
Module for locking (and unlocking) doctests by replacing their outputs with secure hash codes.
"""

from dataclasses import dataclass
from pathlib import Path

import ast
import doctest
import hashlib
import json
import pytest


LOCK_MARKER = '# LOCK'
LOCKED_PREFIX = 'LOCKED:'
FUNCTION_OUTPUT = 'FUNCTION'
ERROR_OUTPUT = 'ERROR'
NOTHING_OUTPUT = 'NOTHING'
SENTINEL_OUTPUTS = (FUNCTION_OUTPUT, ERROR_OUTPUT, NOTHING_OUTPUT)

UNLOCK_PREAMBLE = """
=== Unlocking Tests ===

At each "? ", type what you would expect the output to be.
Type FUNCTION for any function value, ERROR if an error occurs,
and NOTHING if nothing is displayed.

Type exit() to stop unlocking tests.
"""


def locked_hash(line: str) -> str | None:
    """Return the hash code of a locked output line, or None if the line is not locked."""
    text = line.strip()
    if text.startswith(LOCKED_PREFIX):
        return text[len(LOCKED_PREFIX):].strip()
    return None


def replace_output(line: str, text: str) -> str:
    """Replace the content of an output line, preserving its indentation."""
    indent = len(line) - len(line.lstrip())
    return ' ' * indent + text


def substitute_sentinel_outputs(example: doctest.Example) -> None:
    """Rewrite sentinel expected outputs into forms that doctest can match.

    ERROR (as the entire expected output) matches any raised exception: doctest
    checks only exc_msg when an exception is raised, and '...' with ellipsis
    matching enabled matches any message. If no exception is raised, the output
    is compared to the unchanged want (ERROR) and fails, as it should.

    NOTHING (as the entire expected output) matches no displayed output.

    FUNCTION (per output line) matches any function value, since a function's
    repr includes its memory address. Each FUNCTION line is rewritten to
    `<function ...>` with ellipsis matching enabled."""
    if example.want.strip() == ERROR_OUTPUT:
        example.exc_msg = '...\n'
        example.options[doctest.ELLIPSIS] = True
        return
    if example.want.strip() == NOTHING_OUTPUT:
        example.want = ''
        return
    lines = example.want.split('\n')
    changed = False
    for i, line in enumerate(lines):
        if line.strip() == FUNCTION_OUTPUT:
            lines[i] = replace_output(line, '<function ...>')
            changed = True
    if changed:
        example.want = '\n'.join(lines)
        example.options[doctest.ELLIPSIS] = True


def lock_doctests_for_file(src: Path, dst: Path) -> int:
    """
    Write the contents of src to dst with one change: the outputs of doctests
    in functions marked with a `# LOCK` comment are replaced by cryptographic
    hash codes so that the tests cannot be run until the user unlocks them.

    Return the number of outputs that were locked.
    """
    lines = src.read_text().split('\n')
    marker_indices = set()
    locked_outputs = 0

    for node in ast.walk(ast.parse('\n'.join(lines), str(src))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            markers = _find_lock_markers(node, lines)
            if markers:
                marker_indices.update(markers)
                locked_outputs += _lock_docstring_outputs(node, lines)

    # Fail loudly on markers that did not attach to any function, rather than
    # silently writing a file with answers in the clear.
    strays = [i for i, line in enumerate(lines)
              if line.strip() == LOCK_MARKER and i not in marker_indices]
    if strays:
        raise ValueError(f"{LOCK_MARKER} on line {strays[0] + 1} does not precede a function definition")

    dst.write_text('\n'.join(line for i, line in enumerate(lines) if i not in marker_indices))
    return locked_outputs


def _find_lock_markers(node, lines: list[str]) -> list[int]:
    """Return the indices of `# LOCK` comment lines attached to a function:
    the line just above its definition (including any decorators), or a
    comment line between the decorators and the `def`."""
    first_line = min([d.lineno for d in node.decorator_list] + [node.lineno])
    start = max(first_line - 2, 0)  # index of the line above the first decorator
    return [i for i in range(start, node.lineno - 1) if lines[i].strip() == LOCK_MARKER]


def _lock_docstring_outputs(node, lines: list[str]) -> int:
    """Replace the doctest outputs in a function's docstring with hash codes,
    editing lines in place. Return the number of outputs locked."""
    docstring = ast.get_docstring(node, clean=False)
    if docstring is None:
        raise ValueError(f"Locked function '{node.name}' must have a docstring with at least one doctest")
    examples = doctest.DocTestParser().get_examples(docstring)
    if not examples:
        raise ValueError(f"Locked function '{node.name}' must have at least one doctest in its docstring")

    # Line i of the docstring appears on line docstring_start + i of the file (1-indexed).
    docstring_start = node.body[0].lineno
    output_number = 0
    for example in examples:
        first_want = docstring_start + example.lineno + example.source.count('\n')
        for file_line in range(first_want, first_want + example.want.count('\n')):
            line = lines[file_line - 1]
            hash_code = OutputPosition(node.name, output_number).encode(line.strip())
            lines[file_line - 1] = replace_output(line, f'{LOCKED_PREFIX} {hash_code}')
            output_number += 1
    return output_number


@dataclass
class OutputPosition:
    """The position of a doctest output."""
    testname: str
    output_number: int

    def encode(self, output):
        """Encode an output as a cryptographic hash value."""
        hash_input = f"{self.testname}:{self.output_number}:{output}"
        return hashlib.sha256(bytes(hash_input, 'UTF-8')).hexdigest()[:16]


class UnlockKeys(dict):
    """Unlocked outputs ({locked hash: output}), persisted to a JSON file.

    The file is written on each addition and created only then, so runs that
    unlock nothing create no file."""

    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists():
            super().__init__(json.loads(self.path.read_text()))

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.path.write_text(json.dumps(self, indent=2, sort_keys=True) + '\n')


def run_unlock_interactive(items: list[pytest.Item], keys: dict[str, str]):
    """Interactively unlock all LOCKED outputs of doctests among Pytest test items."""
    locked_items = [item for item in items if isinstance(item, pytest.DoctestItem)
                    and any(LOCKED_PREFIX in example.want for example in item.dtest.examples)]
    if not locked_items:
        print("No locked tests found.")
        return
    print(UNLOCK_PREAMBLE)
    for item in locked_items:
        if not unlock_doctest(item.dtest, keys):
            return
    print("=== 🎉 All tests unlocked! 🎉 ===")


def unlock_doctest(dtest: doctest.DocTest, keys: dict[str, str]):
    """Unlock all locked outputs of a doctest interactively."""
    output_number = 0  # Global counter across all examples in this doctest
    testname = dtest.name.split('.')[-1]
    print(f'--- {testname} ---')
    for example in dtest.examples:
        print(">>>", example.source, end="")
        output_lines = [s for s in example.want.split('\n') if s.strip()]
        for k, line in enumerate(output_lines):
            expected_hash = locked_hash(line)
            if expected_hash:
                if output := keys.get(expected_hash):
                    print(output)
                else:
                    position = OutputPosition(testname, output_number)
                    prompt = "?"
                    if len(output_lines) > 1:
                        prompt = f"(line {k+1} of {len(output_lines)}) ?"
                    output_str = unlock_output(example, position, expected_hash, prompt)
                    if output_str is None:  # User chose to exit
                        return False
                    keys[expected_hash] = output_str
            output_number += 1
    return True


def unlock_output(example, output_pos, expected_hash, prompt):
    """Interactively unlock a single output. Return the output, or None to exit."""
    while True:
        try:
            user_input = input(f"{prompt} ").strip()

            if user_input == "exit()":
                print("Exiting unlock mode.")
                return None

            # Sentinel answers may be typed in any case
            if user_input.upper() in SENTINEL_OUTPUTS:
                user_input = user_input.upper()

            # Check if the input matches the hash
            input_hash = output_pos.encode(user_input)
            if input_hash == expected_hash:
                return user_input
            else:
                respond_to_incorrect_input(example, output_pos, user_input)
                print()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting unlock mode.")
            return None


def respond_to_incorrect_input(example, output_pos, user_input):
    print("-- Not quite. Try again! --")

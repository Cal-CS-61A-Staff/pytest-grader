"""
Module for locking (and unlocking) doctests by replacing their outputs with secure hash codes.

A doctest is written to pass as a plain doctest (`python3 -m doctest`): an
expected exception is its traceback and a function value is its repr, with
ellipsis matching for the address (`<function f at 0x...>  # doctest: +ELLIPSIS`).
Locking asks for what a student can predict instead: the whole traceback is one
ERROR answer, and each function value is FUNCTION (see expected_outputs).
"""

from dataclasses import dataclass
from pathlib import Path

import ast
import doctest
import hashlib
import json
import re
import pytest


LOCK_MARKER = '# LOCK'
LOCKED_PREFIX = 'LOCKED:'
FUNCTION_OUTPUT = 'FUNCTION'
ERROR_OUTPUT = 'ERROR'
NOTHING_OUTPUT = 'NOTHING'
SENTINEL_OUTPUTS = (FUNCTION_OUTPUT, ERROR_OUTPUT, NOTHING_OUTPUT)

# The repr of a function value, e.g. `<function make_adder.<locals>.adder at 0x...>`.
FUNCTION_REPR = re.compile(r'<function .*>')
# A doctest option directive comment (`# doctest: +ELLIPSIS`), not shown to students.
DIRECTIVE_COMMENT = re.compile(r'[ \t]*#\s*doctest:[^\n]*')

UNLOCK_PREAMBLE = """
=== Unlocking Tests ===

At each "? ", type what you would expect the output to be.
Type FUNCTION for any function value and ERROR if an error occurs.

Type exit() to stop unlocking tests.
"""


def expected_outputs(example: doctest.Example) -> list[str]:
    """The answers a locked example asks for, one per prompt, in order.

    An expected exception (a traceback of any length) is one ERROR; each
    function value (a `<function ...>` line) is FUNCTION; every other expected
    line is asked for as written. An example with no output asks nothing."""
    if example.exc_msg is not None:
        return [ERROR_OUTPUT]
    outputs = []
    for line in example.want.split('\n'):
        text = line.strip()
        if text:
            outputs.append(FUNCTION_OUTPUT if FUNCTION_REPR.fullmatch(text) else text)
    return outputs


def display_source(source: str) -> str:
    """An example's source as shown to a student: without doctest directives."""
    return DIRECTIVE_COMMENT.sub('', source)


def prompt_lines(source: str) -> list[str]:
    """An example's source as console prompts: `>>> ` then `... ` lines."""
    lines = display_source(source).rstrip('\n').split('\n')
    return ['>>> ' + lines[0]] + [('... ' + line).rstrip() for line in lines[1:]]


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


def string_literal_value(text: str) -> str | None:
    """Return the string that text evaluates to if it is a Python string
    literal, or None if it is not."""
    try:
        value = ast.literal_eval(text)
    except Exception:
        return None
    return value if isinstance(value, str) else None


INTEGER_ANSWER = re.compile(r'-?\d+')
WHOLE_FLOAT_ANSWER = re.compile(r'-?\d+\.0')


def answer_variants(user_input: str) -> list[str]:
    """Return equivalent forms of an answer: the answer as typed, then any
    equivalent spellings, so that "hello" unlocks an expected 'hello', 6
    unlocks an expected 6.0, and 6.0 unlocks an expected 6. Only strings and
    whole numbers are canonicalized; other alternate spellings (e.g. 0x10 for
    16) are not accepted."""
    variants = [user_input]
    value = string_literal_value(user_input)
    if value is not None and repr(value) != user_input:
        variants.append(repr(value))
    if INTEGER_ANSWER.fullmatch(user_input):
        variants.append(user_input + '.0')
    elif WHOLE_FLOAT_ANSWER.fullmatch(user_input):
        variants.append(user_input[:-2])
    return variants


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
    # Line replacements (start, end, replacement lines) in original line
    # indices, applied bottom-up at the end: a locked traceback shrinks to one
    # line, which would shift every position after it if applied in place.
    edits = []
    locked_outputs = 0

    for node in ast.walk(ast.parse('\n'.join(lines), str(src))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            markers = _find_lock_markers(node, lines)
            if markers:
                marker_indices.update(markers)
                edits.extend((i, i + 1, []) for i in markers)
                for edit in _lock_docstring_outputs(node, lines):
                    edits.append(edit)
                    locked_outputs += len(edit[2])

    # Fail loudly on markers that did not attach to any function, rather than
    # silently writing a file with answers in the clear.
    strays = [i for i, line in enumerate(lines)
              if line.strip() == LOCK_MARKER and i not in marker_indices]
    if strays:
        raise ValueError(f"{LOCK_MARKER} on line {strays[0] + 1} does not precede a function definition")

    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = replacement
    dst.write_text('\n'.join(lines))
    return locked_outputs


def _find_lock_markers(node, lines: list[str]) -> list[int]:
    """Return the indices of `# LOCK` comment lines attached to a function:
    the line just above its definition (including any decorators), or a
    comment line between the decorators and the `def`."""
    first_line = min([d.lineno for d in node.decorator_list] + [node.lineno])
    start = max(first_line - 2, 0)  # index of the line above the first decorator
    return [i for i in range(start, node.lineno - 1) if lines[i].strip() == LOCK_MARKER]


def _lock_docstring_outputs(node, lines: list[str]) -> list:
    """The edits (start, end, replacement lines) that replace the doctest
    outputs in a function's docstring with hash codes: one LOCKED line per
    expected output (see expected_outputs), in place of the lines it came from."""
    docstring = ast.get_docstring(node, clean=False)
    if docstring is None:
        raise ValueError(f"Locked function '{node.name}' must have a docstring with at least one doctest")
    examples = doctest.DocTestParser().get_examples(docstring)
    if not examples:
        raise ValueError(f"Locked function '{node.name}' must have at least one doctest in its docstring")

    # Line i of the docstring appears on line docstring_start + i of the file (1-indexed).
    docstring_start = node.body[0].lineno
    output_number = 0
    edits = []
    for example in examples:
        outputs = expected_outputs(example)
        if not outputs:
            continue
        first_want = docstring_start + example.lineno + example.source.count('\n')
        start = first_want - 1  # 0-indexed
        replacement = []
        for output in outputs:
            hash_code = OutputPosition(node.name, output_number).encode(output)
            replacement.append(replace_output(lines[start], f'{LOCKED_PREFIX} {hash_code}'))
            output_number += 1
        edits.append((start, start + example.want.count('\n'), replacement))
    return edits


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
        print('\n'.join(prompt_lines(example.source)))
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

            # Check if the input (or its canonical string form) matches the hash
            for variant in answer_variants(user_input):
                if output_pos.encode(variant) == expected_hash:
                    if variant != user_input:
                        print(f"(Python displays this value as {variant})")
                    return variant
            respond_to_incorrect_input(example, output_pos, user_input, expected_hash)
            print()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting unlock mode.")
            return None


def respond_to_incorrect_input(example, output_pos, user_input, expected_hash):
    # An answer wrong only in its presence/absence of quotes (a string value
    # vs. printed text) earns a hint, not credit.
    if output_pos.encode(repr(user_input)) == expected_hash:
        print("-- Not quite, but your answer would be correct with quotes: "
              "the expected output is a string value. --")
        return
    value = string_literal_value(user_input)
    if value is not None and output_pos.encode(value) == expected_hash:
        print("-- Not quite, but your answer would be correct without quotes: "
              "the output is printed text, not a string value. --")
        return
    print("-- Not quite. Try again! --")

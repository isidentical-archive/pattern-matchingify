import textwrap

import pytest

import pattern_matchingify

TRUE_POSITIVES = [
    (
        "simple_isinstance_1",
        """
        if isinstance(a, B):
           type_str = 'B'
        elif isinstance(a, C):
            type_str = 'C'
        """,
        """
        match a:
            case B():
                type_str = 'B'
            case C():
                type_str = 'C'
        """,
    ),
    (
        "simple_isinstance_with_else",
        """
        if isinstance(a, B):
           type_str = 'B'
        elif isinstance(a, C):
            type_str = 'C'
        else:
            type_str = 'unknown'
        """,
        """
        match a:
            case B():
                type_str = 'B'
            case C():
                type_str = 'C'
            case _:
                type_str = 'unknown'
        """,
    ),
]

FALSE_NEGATIVES = [
    (
        "simple_isinstance_different_subject",
        """
        if isinstance(a, B):
           type_str = 'B'
        elif isinstance(b, C):
            type_str = 'C'
        """,
        """
        if isinstance(a, B):
           type_str = 'B'
        elif isinstance(b, C):
            type_str = 'C'
        """,
    )
]


@pytest.mark.parametrize(
    "key, source, expected",
    [
        *TRUE_POSITIVES,
        *FALSE_NEGATIVES,
    ],
)
def test_pattern_matchingify(key, source, expected):
    source, expected = textwrap.dedent(source), textwrap.dedent(expected)
    refactored = pattern_matchingify.pattern_matchingify(source)
    assert refactored == expected

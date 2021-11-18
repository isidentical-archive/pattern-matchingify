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
    (
        "complex_isinstance_1",
        """
        if isinstance(a, B.X):
           type_str = 'B'
        elif isinstance(a, (C, D)):
            type_str = 'C'
        """,
        """
        match a:
            case B.X():
                type_str = 'B'
            case C() | D():
                type_str = 'C'
        """,
    ),
    (
        "complex_isinstance_2",
        """
        if isinstance(a, (C, D.E, D.E.F)):
           type_str = 'B'
        elif isinstance(a, G):
            type_str = 'C'
        elif isinstance(a, (G.F,)):
            type_str = 'C'
        """,
        """
        match a:
            case C() | D.E() | D.E.F():
                type_str = 'B'
            case G():
                type_str = 'C'
            case G.F():
                type_str = 'C'
        """,
    ),
    (
        "attribute_chained_isinstance_1",
        """
        if (
            isinstance(a, B)
            and a.attr_1 == 1
            and a.attr_2 == 3
        ):
            print(a.attr_3)
        elif (
            isinstance(a, C)
            and a.bla_bla == 'xyz'
        ):
            print(a.bla_bla)
        elif isinstance(a, Q):
            print('Q')
        else:
            pass
        """,
        """
        match a:
            case B(attr_1=1, attr_2=3):
                print(a.attr_3)
            case C(bla_bla='xyz'):
                print(a.bla_bla)
            case Q():
                print('Q')
            case _:
                pass
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

ALL_CASES = [*TRUE_POSITIVES, *FALSE_NEGATIVES]
TEST_IDS, TESTS = zip(*[(test[0], test[1:]) for test in ALL_CASES])


@pytest.mark.parametrize("source, expected", TESTS, ids=TEST_IDS)
def test_pattern_matchingify(source, expected):
    source, expected = textwrap.dedent(source), textwrap.dedent(expected)
    refactored = pattern_matchingify.pattern_matchingify(source)
    assert refactored == expected

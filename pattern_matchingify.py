from __future__ import annotations

import ast
import functools
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    List,
    NamedTuple,
    Optional,
    ParamSpec,
    TypeVar,
)

import refactor
from refactor import ReplacementAction, Rule

T = TypeVar("T")
P = ParamSpec("P")


def iter_ifs(node: ast.If) -> IfGroup:
    yield node
    match node.orelse:
        case [ast.If() as node]:
            yield from iter_ifs(node)


def is_dotted_name(node: ast.expr) -> bool:
    match node:
        case ast.Name():
            return True
        case ast.Attribute(value):
            return is_dotted_name(value)
        case _:
            return False


@functools.lru_cache
def iter_defaults(source: str) -> Dict[str, Callable[[], Any]]:
    # If you hated this code, show your support to:
    # https://github.com/python/cpython/pull/21417
    declarations = source[source.find("(") + 1 : source.rfind(")")]

    result = {}
    for declaration in declarations.split(", "):
        decl_type, field = declaration.split()
        if decl_type.endswith("*"):
            result[field] = list
    return result


def ast_post_init(node: T, *args, **kwargs) -> None:
    """
    Even if you don't use some fields of an AST node, you
    have to pass them since there are not any defaults (beside
    the optional ones). This code simply hacks around it, and
    automatically initializes empty list fields by looking at
    the ASDL.
    """
    ast_init(node, *args, **kwargs)

    asdl = type(node).__doc__
    for field, factory in iter_defaults(asdl).items():
        if not hasattr(node, field):
            setattr(node, field, factory())


ast_init = ast.AST.__init__
ast.AST.__init__ = ast_post_init


@dataclass
class IfGroup:
    stmts: List[ast.If]
    orelse: List[ast.stmt]

    @classmethod
    def from_single(cls, node: ast.If) -> IfGroup:
        stmts = list(iter_ifs(node))
        return cls(stmts, stmts[-1].orelse)


class SubjectfulCase(NamedTuple):
    subject: ast.expr
    stmt: ast.match_case


class PatternMatchingifier(Rule):
    """
    Convert if/else statements to match/case
    if it is applicable.
    """

    MINIMUM_CASE_THRESHOLD = 2

    transformers = []

    @classmethod
    def register(cls, func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except AssertionError:
                return None

        cls.transformers.append(wrapper)
        return wrapper

    def match(self, node: ast.AST) -> Optional[Action]:
        assert isinstance(node, ast.If)

        cases = []
        subjects = []
        group = IfGroup.from_single(node)

        for statement in group.stmts:
            for transformer in self.transformers:
                if case := transformer(self, statement):
                    cases.append(case.stmt)
                    subjects.append(case.subject)
                    break

        assert len(set(ast.dump(subject) for subject in subjects)) == 1
        assert len(cases) >= self.MINIMUM_CASE_THRESHOLD

        if group.orelse:
            else_case = ast.match_case(ast.MatchAs(), body=group.orelse)
            cases.append(else_case)

        subject = subjects[0]
        return ReplacementAction(node, ast.Match(subject, cases))


@PatternMatchingifier.register
def handle_single_isinstance(
    manager: PatternMatchingifier, node: ast.If
) -> Optional[SubjectfulCase]:
    assert isinstance(test := node.test, ast.Call)
    assert isinstance(test.func, ast.Name)
    assert test.func.id == "isinstance"
    assert len(test.args) == 2
    assert len(test.keywords) == 0

    subject, type_name = test.args
    assert is_dotted_name(type_name)

    pattern = ast.MatchClass(type_name)
    return SubjectfulCase(subject, ast.match_case(pattern, body=node.body))


@PatternMatchingifier.register
def handle_complex_isinstance(
    manager: PatternMatchingifier, node: ast.If
) -> Optional[SubjectfulCase]:
    test = node.test
    assert isinstance(test := node.test, ast.Call)
    assert isinstance(test.func, ast.Name)
    assert test.func.id == "isinstance"
    assert len(test.args) == 2
    assert len(test.keywords) == 0

    subject, type_names_tuple = test.args
    assert isinstance(type_names_tuple, ast.Tuple)
    assert all(map(is_dotted_name, type_names := type_names_tuple.elts))

    pattern = ast.MatchOr(
        [ast.MatchClass(type_name) for type_name in type_names]
    )
    return SubjectfulCase(subject, ast.match_case(pattern, body=node.body))


def pattern_matchingify(source: str) -> str:
    session = refactor.Session(rules=[PatternMatchingifier])
    return session.run(source)


if __name__ == "__main__":
    refactor.run(rules=[PatternMatchingifier])

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
from refactor import ReplacementAction, Rule, common

T = TypeVar("T")
P = ParamSpec("P")


def matcher(func: Callable[P, T]) -> Callable[P, T]:
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AssertionError:
            return None

    return wrapper


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
    declarations = source[source.find("(") + 1 : source.rfind(")")]

    result = {}
    for declaration in declarations.split(", "):
        decl_type, field = declaration.split()
        if decl_type.endswith("*"):
            result[field] = list
    return result


def ast_post_init(node: T, *args, **kwargs) -> None:
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


class Pattern(NamedTuple):
    subject: ast.expr
    node: ast.pattern

    @classmethod
    def pack(cls, subject: ast.expr, patterns: List[ast.pattern]) -> Pattern:
        if len(patterns) >= 2:
            pattern = ast.MatchOr(patterns)
        else:
            [pattern] = patterns

        return cls(subject, pattern)

    def unpack(self) -> Tuple[ast.expr, List[ast.pattern]]:
        if isinstance(self.node, ast.MatchOr):
            patterns = self.node.patterns
        else:
            patterns = [self.node]

        return self.subject, patterns


class Case(NamedTuple):
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
        wrapper = matcher(func)
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


@matcher
def match_isinstance(node: ast.expr) -> Optional[Pattern]:
    assert isinstance(node, ast.Call)
    assert isinstance(node.func, ast.Name)
    assert node.func.id == "isinstance"
    assert len(node.args) == 2
    assert len(node.keywords) == 0

    subject, maybe_type = node.args
    if is_dotted_name(maybe_type):
        pattern = ast.MatchClass(maybe_type)
    elif isinstance(maybe_type, ast.Tuple):
        assert len(maybe_type.elts) >= 1
        assert all(map(is_dotted_name, type_names := maybe_type.elts))
        pattern = ast.MatchOr(
            [ast.MatchClass(type_name) for type_name in type_names]
        )
    else:
        return None

    return Pattern(subject, pattern)


@matcher
def match_constant(node: ast.expr) -> Optional[Pattern]:
    def is_number_pattern(node: ast.expr) -> bool:
        # Normally more complicated than this, due to handling of
        # complex numbers.
        match node:
            case ast.BinOp(
                ast.Constant(), ast.Add() | ast.Sub(), ast.Constant()
            ):
                return True
            case ast.UnaryOp(ast.USub(), ast.Constant()):
                return True
        return False

    match node:
        case ast.Constant(str() | bytes() | int() | float() | complex()):
            return ast.MatchValue(node)
        case ast.Constant((True | False | None) as value):
            return ast.MatchSingleton(value)
        case ast.Attribute(value) if is_dotted_name(value):
            return ast.MatchValue(node)
        case ast.UnaryOp() | ast.BinOp() if is_number_pattern(node):
            return ast.MatchValue(node)


@PatternMatchingifier.register
def compile_isinstance(
    manager: PatternMatchingifier, node: ast.If
) -> Optional[SubjectfulCase]:
    """
    Convert a simple isinstance() call to a case statement.

    Rules:
        - isinstance(X, Y) => case Y(): <subject: X>
        - isinstance(X, Y.Z) => case Y.Z(): <subject: X>
        - isinstance(X, (Q, T)) => case Q() | T(): <subject: X>
    """

    assert (pattern := match_isinstance(node.test))
    return Case(pattern.subject, ast.match_case(pattern.node, body=node.body))


@PatternMatchingifier.register
def compile_isinstance_attributes(manager: PatternMatchingifier, node: ast.If):
    """
    Convert a complex logical expression into a case statement.

    Rules:
        - isinstance($SUBJECT, $TYPE_NAME) ($OPERATOR $SUBJECT.$ATTR == $VALUE)*
            =>
          case $TYPE_NAME($ATTR=$VALUE): <subject: $SUBJECT>
    """

    assert isinstance(test := node.test, ast.BoolOp)
    assert isinstance(test.op, ast.And)

    isinstance_call, *attribute_checks = test.values
    assert (pattern := match_isinstance(isinstance_call))

    subject, patterns = pattern.unpack()

    data = {}
    for attribute_check in attribute_checks:
        assert isinstance(attribute_check, ast.Compare)
        assert isinstance(lhs := attribute_check.left, ast.Attribute)
        assert common.compare_ast(lhs.value, subject)

        assert len(attribute_check.ops) == 1
        assert isinstance(attribute_check.ops[0], ast.Eq)
        assert (rhs := match_constant(attribute_check.comparators[0]))

        data[lhs.attr] = rhs

    for pattern in patterns:
        pattern.kwd_attrs = list(data.keys())
        pattern.kwd_patterns = list(data.values())

    pattern = Pattern.pack(subject, patterns)
    return Case(pattern.subject, ast.match_case(pattern.node, body=node.body))


def pattern_matchingify(source: str) -> str:
    session = refactor.Session(rules=[PatternMatchingifier])
    return session.run(source)


if __name__ == "__main__":
    refactor.run(rules=[PatternMatchingifier])

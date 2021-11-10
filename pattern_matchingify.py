from __future__ import annotations

import ast
from dataclasses import dataclass
from functools import lru_cache
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


@lru_cache
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
    transformers = []

    MINIMUM_CASE_THRESHOLD = 2

    @classmethod
    def register(cls, func: Callable[P, T]) -> Callable[P, T]:
        cls.transformers.append(func)
        return func

    def match(self, node: ast.AST) -> Optional[Action]:
        assert isinstance(node, ast.If)

        cases = []
        subjects = []
        group = IfGroup.from_single(node)

        statements = group.stmts.copy()
        for transformer in self.transformers:
            for statement in statements.copy():
                if case := transformer(self, statement):
                    cases.append(case.stmt)
                    subjects.append(case.subject)
                    statements.remove(statement)

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
    match node.test:
        case ast.Call(
            ast.Name("isinstance"), args=[subject, type_name], keywords=[]
        ) if is_dotted_name(type_name):
            pattern = ast.MatchClass(type_name)
            return SubjectfulCase(
                subject, ast.match_case(pattern, body=node.body)
            )


def pattern_matchingify(source: str) -> str:
    session = refactor.Session(rules=[PatternMatchingifier])
    return session.run(source)


if __name__ == "__main__":
    refactor.run(rules=[PatternMatchingifier])

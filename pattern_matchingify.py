from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Callable, List, NamedTuple, Optional, ParamSpec, TypeVar

import refactor
from refactor import ReplacementAction, Rule

P = ParamSpec("P")
R = TypeVar("R")


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
    def register(cls, func: Callable[P, R]) -> Callable[P, R]:
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
            pattern = ast.MatchClass(
                type_name, patterns=[], kwd_attrs=[], kwd_patterns=[]
            )
            return SubjectfulCase(
                subject, ast.match_case(pattern, body=node.body)
            )


def pattern_matchingify(source: str) -> str:
    session = refactor.Session(rules=[PatternMatchingifier])
    return session.run(source)


if __name__ == "__main__":
    refactor.run(rules=[PatternMatchingifier])

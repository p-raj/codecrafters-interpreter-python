from enum import StrEnum
from pathlib import Path

"""
expression     → literal | unary | binary | grouping ;
literal        → NUMBER | STRING | "true" | "false" | "nil" ;
grouping       → "(" expression ")" ;
unary          → ( "-" | "!" ) expression ;
binary         → expression operator expression ;
operator       → "==" | "!=" | "<" | "<=" | ">" | ">=" | "+"  | "-"  | "*" | "/"
"""

STAB = " " * 4
BR = "\n"
GTYPE = "R"


class BaseClass(StrEnum):
    EXPR = "Expr"
    STMT = "Stmt"


def _tab(file, count=1):
    file.write(STAB * count)


def _breakline(file, count=1):
    file.write(BR * count)


def _write_visitor_protocol(file, base_class: BaseClass, expr_map):
    """
    interface Visitor<R> {
        R visitAssignExpr(Assign expr);
        R visitBinaryExpr(Binary expr);
        R visitCallExpr(Call expr);
        R visitGetExpr(Get expr);
        R visitGroupingExpr(Grouping expr);
        R visitLiteralExpr(Literal expr);
        R visitLogicalExpr(Logical expr);
        R visitSetExpr(Set expr);
        R visitSuperExpr(Super expr);
        R visitThisExpr(This expr);
        R visitUnaryExpr(Unary expr);
        R visitVariableExpr(Variable expr);
    }
    """
    file.write(f'{GTYPE} = TypeVar("{GTYPE}")')
    _breakline(file, 3)
    file.write("class Visitor(Protocol[R]):")
    for cls_name in expr_map:
        _breakline(file)
        _tab(file)
        file.write(
            f"def visit_{cls_name.lower()}_{base_class.value.lower()}(self, {base_class.value.lower()}: {cls_name}) -> {GTYPE}: ..."
        )
    _breakline(file, 2)


def _write_base_class(file, base_class: BaseClass):
    file.writelines(
        [
            f"class {base_class.value}(ABC):",
            BR,
            STAB,
            "",
            "@abstractmethod",
            BR,
            STAB,
            "def accept(): ...",
            BR,
        ]
    )
    _breakline(file, 2)


def _write_imports(file):
    file.writelines(
        [
            "from __future__ import annotations",
            BR,
            "from abc import ABC, abstractmethod",
            BR,
            "from dataclasses import dataclass",
            BR,
            "from .token import Token",
            BR,
            "from typing import Protocol, TypeVar, List, TYPE_CHECKING",
            BR,
        ]
    )
    _breakline(file, 2)


def _write_expr_subclass(file, base_class: BaseClass, map_):
    for cls_name, params in map_.items():
        file.write("@dataclass(frozen=True)")
        _breakline(file)
        file.write(f"class {cls_name}({base_class.value}):")
        _breakline(file)
        for param in params:
            _tab(file)
            p_ = param.strip().split()
            file.write(f"{p_[1]}: {p_[0]}")
            _breakline(file)

        _breakline(file)
        _tab(file)
        file.write(f"def accept(self, visitor: Visitor[{GTYPE}]) -> {GTYPE}:")
        _breakline(file)
        _tab(file, 2)
        file.write(
            f"return visitor.visit_{cls_name.lower()}_{base_class.value.lower()}(self)"
        )
        _breakline(file, 3)


def _write_expr_subclass_property(file, base_class: BaseClass, expr_map):
    for cls_name in expr_map:
        _breakline(file)
        file.write(f"{base_class.value}.{cls_name} = {cls_name}")
    _breakline(file, 2)


def generate_common(file_path: Path):
    with open(file_path, "w") as file:
        _write_imports(file)


def generate_expr(file_path: Path):
    map_ = {
        "Comma": ["Expr left", "Expr right"],
        "Logical": ["Expr left", "Token operator", "Expr right"],
        "Ternary": ["Expr condition", "Expr then_branch", "Expr else_branch"],
        "Binary": ["Expr left", "Token operator", "Expr right"],
        "Grouping": ["Expr expression"],
        "Literal": ["object value"],
        "Unary": ["Token operator", "Expr right"],
        "Variable": ["Token name"],
        "Assign": ["Token name", "Expr value"],
        "Call": ["Expr callee", "Token paren", "List[Expr] arguments"],
        "Lambda": ["List[Token] params", "List[Stmt] body"],
        "Get": ["Expr objekt", "Token name"],
        "Set": ["Expr objekt", "Token name", "Expr value"],
        "Super": ["Token keyword", "Token method"],
        "This": ["Token keyword"],
    }

    with open(file_path, "a") as file:
        file.writelines(
            [
                "if TYPE_CHECKING:",
                BR,
                STAB,
                "from app.stmt import Stmt",
            ]
        )
        _breakline(file, 3)
        _write_base_class(file, BaseClass.EXPR)
        _write_expr_subclass(file, BaseClass.EXPR, map_)
        _write_expr_subclass_property(file, BaseClass.EXPR, map_)
        _write_visitor_protocol(file, BaseClass.EXPR, map_)


def generate_stms(file_path: Path):
    map_ = {
        "Expression": ["Expr expression"],
        "Print": ["Expr expression"],
        "Var": ["Token name", "Expr initializer"],
        "Block": ["List[Stmt] statements"],
        "If": ["Expr condition", "Stmt then_branch", "Stmt else_branch"],
        "While": ["Expr condition", "Stmt body"],
        "Break": [],
        "Function": ["Token name", "List[Token] params", "List[Stmt] body"],
        "Return": ["Token keyword", "Expr value"],
        "Class": [
            "Token name",
            "Expr.Variable superclass",
            "List[Stmt.Function] methods",
        ],
    }

    with open(file_path, "a") as file:
        file.writelines(
            [
                "if TYPE_CHECKING:",
                BR,
                STAB,
                "from .expr import Expr",
            ]
        )
        _breakline(file, 3)
        _write_base_class(file, BaseClass.STMT)
        _write_expr_subclass(file, BaseClass.STMT, map_)
        _write_expr_subclass_property(file, BaseClass.STMT, map_)
        _write_visitor_protocol(file, BaseClass.STMT, map_)


if __name__ == "__main__":
    expr_file_path = Path(__file__).resolve().parent.parent / "expr.py"
    stmt_file_path = Path(__file__).resolve().parent.parent / "stmt.py"
    generate_common(expr_file_path)
    generate_common(stmt_file_path)
    generate_expr(expr_file_path)
    generate_stms(stmt_file_path)

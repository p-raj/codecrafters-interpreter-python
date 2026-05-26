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


def _tab(file, count=1):
    file.write(STAB * count)


def _breakline(file, count=1):
    file.write(BR * count)


def _write_visitor_protocol(file, expr_map):
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
            f"def visit_{cls_name.lower()}_expr(self, expr: {cls_name}) -> {GTYPE}: ..."
        )
    _breakline(file, 2)


def _write_expr_base(file):
    file.writelines(
        [
            "class Expr(ABC):",
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
            "from abc import ABC, abstractmethod",
            BR,
            "from dataclasses import dataclass",
            BR,
            "from .token import Token",
            BR,
            "from typing import Protocol, TypeVar",
            BR,
        ]
    )
    _breakline(file, 2)


def _write_docstring(file):
    file.write('"""')
    _breakline(file)
    file.writelines(
        [
            "expression     → literal | unary | binary | grouping ;",
            BR,
            'literal        → NUMBER | STRING | "true" | "false" | "nil" ;',
            BR,
            'grouping       → "(" expression ")" ;',
            BR,
            'unary          → ( "-" | "!" ) expression ;',
            BR,
            "binary         → expression operator expression ;",
            BR,
            'operator       → "==" | "!=" | "<" | "<=" | ">" | ">=" | "+"  | "-"  | "*" | "/"',
            BR,
        ]
    )
    _breakline(file)
    file.write('"""')
    _breakline(file, 3)


def _write_expr_subclass(file, map_):
    for cls_name, params in map_.items():
        file.write("@dataclass(frozen=True)")
        _breakline(file)
        file.write(f"class {cls_name}(Expr):")
        _breakline(file)
        for param in params:
            _tab(file)
            p_ = param.strip().split()
            file.write(f"{p_[1]}: {p_[0]}")
            # def accept(self, visitor: Visitor[R]) -> R:
            #     return visitor.visit_binary_expr(self)
            _breakline(file)

        _breakline(file)
        _tab(file)
        file.write(f"def accept(self, visitor: Visitor[{GTYPE}]) -> {GTYPE}:")
        _breakline(file)
        _tab(file, 2)
        file.write(f"return visitor.visit_{cls_name.lower()}_expr(self)")
        _breakline(file, 3)


def _write_expr_subclass_property(file, expr_map):
    for cls_name in expr_map:
        _breakline(file)
        file.write(f"Expr.{cls_name} = {cls_name}")
    _breakline(file, 2)


def generate_expr():
    file_path = Path(__file__).resolve().parent.parent / "expr.py"
    map_ = {
        "Binary": ["Expr left", "Token operator", "Expr right"],
        "Grouping": ["Expr expression"],
        "Literal": ["object value"],
        "Unary": ["Token operator", "Expr right"],
    }

    with open(file_path, "w") as file:
        _write_imports(file)
        _write_docstring(file)
        _write_expr_base(file)
        _write_expr_subclass(file, map_)
        _write_expr_subclass_property(file, map_)
        _write_visitor_protocol(file, map_)


if __name__ == "__main__":
    generate_expr()

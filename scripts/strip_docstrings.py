from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _is_docstring_stmt(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Expr):
        return False
    v = stmt.value
    return isinstance(v, ast.Constant) and isinstance(v.value, str)


def _iter_docstring_expr_nodes(tree: ast.AST) -> list[ast.Expr]:
    found: list[ast.Expr] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and _is_docstring_stmt(body[0]):
                found.append(body[0])
    return found


def strip_docstrings(source: str, *, filename: str) -> str | None:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return None
    nodes = _iter_docstring_expr_nodes(tree)
    if not nodes:
        return source
    lines = source.splitlines(keepends=True)
    offs: list[int] = [0]
    for line in lines:
        offs.append(offs[-1] + len(line))

    def span(node: ast.AST) -> tuple[int, int] | None:
        el = getattr(node, "end_lineno", None)
        ec = getattr(node, "end_col_offset", None)
        if el is None or ec is None:
            return None
        try:
            start = offs[node.lineno - 1] + node.col_offset
            end = offs[el - 1] + ec
        except (IndexError, TypeError):
            return None
        return start, end

    spans = []
    for node in nodes:
        s = span(node)
        if s is not None:
            spans.append(s)
    spans.sort(key=lambda t: t[0], reverse=True)
    out = source
    for start, end in spans:
        out = out[:start] + out[end:]
    if spans:
        out = out.lstrip("\n")
    return out


def main() -> int:
    changed = 0
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if "venv" in rel.parts or ".venv" in rel.parts:
            continue
        raw = path.read_text(encoding="utf-8")
        nxt = strip_docstrings(raw, filename=str(path))
        if nxt is None:
            print("skip (syntax):", rel, file=sys.stderr)
            continue
        if nxt != raw:
            path.write_text(nxt, encoding="utf-8", newline="")
            changed += 1
    print(f"updated {changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

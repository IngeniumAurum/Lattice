"""Reference Extractor: Python via the stdlib `ast` module.

Pure-stdlib so the scaffold runs with zero dependencies. A tree-sitter adapter
for other languages plugs into the exact same `Extractor` port — this file is
the template, not a special case.

Extracts module / class / function nodes and CONTAINS + CALLS + IMPORTS edges.
"""

from __future__ import annotations

import ast

from ...domain.models import Confidence, Edge, Fragment, Node, SourceFile


class PythonAstExtractor:
    name = "python-ast"

    def supports(self, file: SourceFile) -> bool:
        return file.language == "python"

    def extract(self, file: SourceFile) -> Fragment:
        fragment = Fragment(path=file.path, fingerprint=file.fingerprint)
        try:
            with open(file.path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=file.path)
        except (OSError, SyntaxError, ValueError):
            return fragment  # unreadable / invalid → empty, never crash a worker

        module_id = file.path
        fragment.nodes.append(
            Node(id=module_id, label=file.path, kind="module", path=file.path)
        )
        self._visit(tree, module_id, file, fragment)
        return fragment

    def _visit(self, scope: ast.AST, parent_id: str,
               file: SourceFile, frag: Fragment) -> None:
        for child in ast.iter_child_nodes(scope):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                kind = "class" if isinstance(child, ast.ClassDef) else "function"
                node_id = f"{parent_id}::{child.name}"
                frag.nodes.append(Node(id=node_id, label=child.name, kind=kind,
                                       path=file.path, line=child.lineno))
                frag.edges.append(Edge(parent_id, node_id, "contains"))
                self._collect_calls(child, node_id, frag)
                self._visit(child, node_id, file, frag)  # nested defs
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                self._collect_imports(child, parent_id, frag)

    def _collect_calls(self, fn: ast.AST, owner_id: str, frag: Fragment) -> None:
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name:
                    frag.edges.append(
                        Edge(owner_id, name, "calls",
                             confidence=Confidence.INFERRED)
                    )

    def _collect_imports(self, node: ast.AST, owner_id: str,
                         frag: Fragment) -> None:
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            frag.edges.append(
                Edge(owner_id, name, "imports", confidence=Confidence.EXTRACTED)
            )


def _call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None

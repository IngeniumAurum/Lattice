"""Multi-language Extractor backed by tree-sitter.

One adapter covers many languages via a small, declarative per-language config
(which AST node types are definitions, and which are calls). Adding a language is
a dict entry — no new parsing code (Open/Closed, even within the adapter).

Dependencies are optional and lazily loaded. Two grammar sources are tried, in
order: the individual `tree-sitter-<lang>` packages (compiled, offline), then
`tree-sitter-language-pack`. If neither can supply a grammar, the extractor
reports `supports() == False` for that file and the pipeline silently falls back
to other registered extractors. Importing this module never fails, so it is
always safe to register.
"""

from __future__ import annotations

from ...domain.models import Confidence, Edge, Fragment, Node, SourceFile

# type -> kind for "definition" nodes; "calls" = call-like node types whose
# `function`/`name` field names the callee.
_LANG_CONFIG: dict[str, dict] = {
    "javascript": {
        "defs": {"function_declaration": "function",
                 "method_definition": "method",
                 "class_declaration": "class",
                 "generator_function_declaration": "function"},
        "calls": {"call_expression": "function"},
    },
    "typescript": {
        "defs": {"function_declaration": "function",
                 "method_definition": "method",
                 "class_declaration": "class",
                 "interface_declaration": "interface",
                 "enum_declaration": "enum"},
        "calls": {"call_expression": "function"},
    },
    "go": {
        "defs": {"function_declaration": "function",
                 "method_declaration": "method",
                 "type_declaration": "type"},
        "calls": {"call_expression": "function"},
    },
    "rust": {
        "defs": {"function_item": "function",
                 "struct_item": "struct",
                 "enum_item": "enum",
                 "trait_item": "trait",
                 "impl_item": "impl"},
        "calls": {"call_expression": "function",
                  "macro_invocation": "macro"},
    },
    "java": {
        "defs": {"method_declaration": "method",
                 "class_declaration": "class",
                 "interface_declaration": "interface"},
        "calls": {"method_invocation": "name"},
    },
}


# language -> (module name, factory attribute) for the individual grammar packages.
_GRAMMAR_MODULES = {
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
    "java": ("tree_sitter_java", "language"),
}


class TreeSitterExtractor:
    name = "tree-sitter"

    def __init__(self) -> None:
        self._parsers: dict[str, object] = {}

    def _parser(self, language: str):
        if language not in self._parsers:
            self._parsers[language] = (self._from_grammar_module(language)
                                       or self._from_language_pack(language))
        return self._parsers[language]

    @staticmethod
    def _from_grammar_module(language: str):
        """Build a parser from a compiled tree-sitter-<lang> package (offline)."""
        spec = _GRAMMAR_MODULES.get(language)
        if spec is None:
            return None
        module_name, attr = spec
        try:
            import importlib

            import tree_sitter as ts
            grammar = importlib.import_module(module_name)
            lang = ts.Language(getattr(grammar, attr)())
            return ts.Parser(lang)
        except Exception:
            return None

    @staticmethod
    def _from_language_pack(language: str):
        """Fall back to tree-sitter-language-pack (may fetch grammars)."""
        try:
            from tree_sitter_language_pack import get_parser  # type: ignore
            return get_parser(language)
        except Exception:
            return None

    def supports(self, file: SourceFile) -> bool:
        return (file.language in _LANG_CONFIG
                and self._parser(file.language) is not None)

    def extract(self, file: SourceFile) -> Fragment:
        frag = Fragment(path=file.path, fingerprint=file.fingerprint)
        parser = self._parser(file.language)
        if parser is None:
            return frag
        try:
            with open(file.path, "rb") as fh:
                source = fh.read()
            tree = parser.parse(source)
        except Exception:
            return frag

        config = _LANG_CONFIG[file.language]
        module_id = file.path
        frag.nodes.append(
            Node(id=module_id, label=file.path, kind="module", path=file.path)
        )
        self._walk(tree.root_node, source, module_id, file, config, frag)
        return frag

    def _walk(self, node, source: bytes, parent_id: str, file: SourceFile,
              config: dict, frag: Fragment) -> None:
        defs, calls = config["defs"], config["calls"]
        for child in node.children:
            if child.type in defs:
                name = self._field_text(child, "name", source) or child.type
                node_id = f"{parent_id}::{name}"
                frag.nodes.append(Node(id=node_id, label=name,
                                       kind=defs[child.type], path=file.path,
                                       line=child.start_point[0] + 1))
                frag.edges.append(Edge(parent_id, node_id, "contains"))
                self._walk(child, source, node_id, file, config, frag)
            elif child.type in calls:
                callee = self._field_text(child, calls[child.type], source)
                if callee:
                    frag.edges.append(
                        Edge(parent_id, _last_segment(callee), "calls",
                             confidence=Confidence.INFERRED)
                    )
                self._walk(child, source, parent_id, file, config, frag)
            else:
                self._walk(child, source, parent_id, file, config, frag)

    @staticmethod
    def _field_text(node, field: str, source: bytes) -> str | None:
        child = node.child_by_field_name(field)
        if child is None:
            return None
        return source[child.start_byte:child.end_byte].decode("utf-8", "replace")


def _last_segment(callee: str) -> str:
    """`foo.bar.baz` / `a::b` -> `baz` so calls resolve to a bare name."""
    for sep in (".", "::"):
        if sep in callee:
            callee = callee.split(sep)[-1]
    return callee.strip("()") or callee

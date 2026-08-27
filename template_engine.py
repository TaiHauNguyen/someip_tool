"""A tiny XML template engine.

The ARXML structure - which AUTOSAR elements exist, how they nest, which
attributes they carry - lives in a template file, not in Python.  Python only
computes the *values* (header ids, lengths, short names) and hands them over as
a context; the template decides what the XML looks like.

Directives are plain attributes on any template element and never reach the
output:

    t-def="name"            register this element as a reusable macro (not emitted here)
    t-call="name"           expand the macro `name` in place (recursion allowed)
    t-foreach="expr as var" repeat this element once per item of `expr`
    t-if="expr"             emit this element only when `expr` is truthy
    t-with="expr as var"    bind an extra variable for this element and its children
    t-text="expr"           take the element text from `expr`
    t-strip="1"             emit the children only, drop this wrapper element
    t-attr-NAME="value"     emit an attribute literally named NAME; `__` in NAME
                            becomes `:`, which is how the template writes the
                            namespace declarations that ElementTree would
                            otherwise swallow (t-attr-xmlns__xsi -> xmlns:xsi)

Inside element text and attribute values, `${expr}` is replaced by the value of
`expr`.  Expressions are ordinary Python evaluated against the context plus the
helper functions the caller provides.

Loop variables `<var>_index` (0 based) and `<var>_number` (1 based) are added
automatically inside a t-foreach.
"""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

DIRECTIVES = ("t-def", "t-call", "t-foreach", "t-if", "t-with", "t-text", "t-strip")
_INTERP = re.compile(r"\$\{([^{}]*)\}")
_AS = re.compile(r"^\s*(.+?)\s+as\s+([A-Za-z_]\w*)\s*$")


class TemplateError(Exception):
    pass


class AttrDict(dict):
    """Lets a template write `event.pdu_path` instead of `event['pdu_path']`."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None


def wrap(value):
    """Deep-wrap plain containers so attribute access works in expressions."""
    if isinstance(value, AttrDict):
        return value
    if isinstance(value, dict):
        return AttrDict({k: wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [wrap(v) for v in value]
    if isinstance(value, tuple):
        return tuple(wrap(v) for v in value)
    return value


def fmt(value: Any) -> str:
    """Render a value the way AUTOSAR expects it (no trailing .0 on floats)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


class Renderer:
    def __init__(self, helpers: Optional[Dict[str, Any]] = None):
        self.helpers: Dict[str, Any] = {"fmt": fmt}
        self.helpers.update(helpers or {})
        self.macros: Dict[str, ET.Element] = {}

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def render_file(self, template_path: str, context: Dict[str, Any]) -> str:
        with open(template_path, "r", encoding="utf-8") as fh:
            text = fh.read()
        return self.render_string(text, context)

    def render_string(self, template_text: str, context: Dict[str, Any]) -> str:
        prolog = self._prolog(template_text)
        root = ET.fromstring(template_text)
        self.macros = {}
        self._collect_macros(root)

        out_root = self._render_element(root, wrap(dict(context)))
        if out_root is None:
            raise TemplateError("the template root element was suppressed")
        if isinstance(out_root, list):
            if len(out_root) != 1:
                raise TemplateError("the template root must produce exactly one element")
            out_root = out_root[0]
        ET.indent(out_root, space="  ")
        return prolog + ET.tostring(out_root, encoding="unicode") + "\n"

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    @staticmethod
    def _prolog(text: str) -> str:
        """Keep the XML declaration and the comments that precede the root."""
        out: List[str] = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n']
        for m in re.finditer(r"<!--(.*?)-->", text, re.S):
            if text[:m.start()].count("<") - text[:m.start()].count("<!--") - \
                    text[:m.start()].count("<?") > 0:
                break
            out.append("<!--%s-->\n" % m.group(1))
        return "".join(out)

    def _collect_macros(self, elem: ET.Element) -> None:
        for child in list(elem):
            name = child.get("t-def")
            if name:
                self.macros[name] = child
                elem.remove(child)
            self._collect_macros(child)

    def _eval(self, expr: str, ctx: Dict[str, Any]) -> Any:
        scope = dict(self.helpers)
        scope.update(ctx)
        try:
            return eval(expr, {"__builtins__": _SAFE_BUILTINS}, scope)  # noqa: S307
        except Exception as exc:  # noqa: BLE001 - reported with the expression
            raise TemplateError("cannot evaluate %r: %s: %s"
                                % (expr, type(exc).__name__, exc)) from exc

    def _interpolate(self, text: str, ctx: Dict[str, Any]) -> str:
        return _INTERP.sub(lambda m: fmt(self._eval(m.group(1), ctx)), text)

    def _split_as(self, raw: str, what: str) -> tuple:
        m = _AS.match(raw)
        if not m:
            raise TemplateError("%s needs the form '<expression> as <name>', got %r" % (what, raw))
        return m.group(1), m.group(2)

    def _render_element(self, elem: ET.Element, ctx: Dict[str, Any]):
        """Return an Element, a list of Elements, or None."""
        foreach = elem.get("t-foreach")
        if foreach is not None:
            expr, var = self._split_as(foreach, "t-foreach")
            items = self._eval(expr, ctx) or []
            produced: List[ET.Element] = []
            for i, item in enumerate(items):
                sub_ctx = dict(ctx)
                sub_ctx[var] = item
                sub_ctx[var + "_index"] = i
                sub_ctx[var + "_number"] = i + 1
                clone = copy.deepcopy(elem)
                del clone.attrib["t-foreach"]
                got = self._render_element(clone, sub_ctx)
                _extend(produced, got)
            return produced

        cond = elem.get("t-if")
        if cond is not None and not self._eval(cond, ctx):
            return None

        with_ = elem.get("t-with")
        if with_ is not None:
            expr, var = self._split_as(with_, "t-with")
            ctx = dict(ctx)
            ctx[var] = self._eval(expr, ctx)

        call = elem.get("t-call")
        if call is not None:
            name = self._interpolate(call, ctx) if "${" in call else call
            macro = self.macros.get(name)
            if macro is None:
                raise TemplateError("undefined macro %r" % name)
            return self._render_element(copy.deepcopy(macro), ctx)

        children: List[ET.Element] = []
        for child in list(elem):
            _extend(children, self._render_element(child, ctx))

        if elem.get("t-strip"):
            return children

        out = ET.Element(elem.tag)
        for key, value in elem.attrib.items():
            if key in DIRECTIVES:
                continue
            rendered = self._interpolate(value, ctx) if "${" in value else value
            if key.startswith("t-attr-"):
                out.set(key[len("t-attr-"):].replace("__", ":"), rendered)
            else:
                out.set(key, rendered)

        text_expr = elem.get("t-text")
        if text_expr is not None:
            out.text = fmt(self._eval(text_expr, ctx))
        elif elem.text and elem.text.strip():
            out.text = self._interpolate(elem.text.strip(), ctx)

        for c in children:
            out.append(c)
        return out


def _extend(target: List[ET.Element], produced) -> None:
    if produced is None:
        return
    if isinstance(produced, list):
        target.extend(produced)
    else:
        target.append(produced)


_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict, "enumerate": enumerate,
    "float": float, "getattr": getattr, "hasattr": hasattr, "hex": hex, "int": int,
    "len": len, "list": list, "max": max, "min": min, "range": range, "reversed": reversed,
    "round": round, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple, "zip": zip,
    "True": True, "False": False, "None": None,
}

"""Colours and ttk styling for the GUI.

Everything visual lives here so the widgets in gui.py stay plain: they ask for
a named style ("Accent.TButton", "Section.TLabel") and this module decides what
it looks like.  Switching the palette therefore re-skins the whole tool without
touching a single widget.

    palette = theme.apply(root, "light")     # or "dark"

`clam` is used as the base ttk theme because it is the only built-in one that
actually honours colour options for Treeview and Notebook on Windows; the
native `vista` theme draws those from the OS and ignores what it is told.
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk
from typing import Dict

BASE_FONT = ("Segoe UI", 9)
BOLD_FONT = ("Segoe UI", 9, "bold")
HEAD_FONT = ("Segoe UI", 10, "bold")
MONO_FONT = ("Consolas", 9)


class Palette(dict):
    """A colour set; attribute access keeps the call sites readable."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None


LIGHT = Palette(
    name="light",
    bg="#eef1f5",            # window / tab strip
    surface="#ffffff",       # panels, entries, trees
    raised="#f7f9fb",        # toolbar, headings, stripes
    border="#ccd4dd",
    text="#1c242e",
    muted="#63707f",
    accent="#2563eb",
    accent_hi="#1d4ed8",
    accent_fg="#ffffff",
    sel="#d8e6fd",
    sel_text="#10233f",
    error="#b3261e",
    warn="#8a5a00",
    info="#5a6673",
    ok="#166534",
    # ARXML preview
    xml_tag="#0b62c4",
    xml_attr="#8a5a00",
    xml_value="#166534",
    xml_comment="#7b8794",
)

DARK = Palette(
    name="dark",
    bg="#1a1e24",
    surface="#232830",
    raised="#2b313a",
    border="#3a424d",
    text="#e4eaf1",
    muted="#98a4b3",
    accent="#4d8dfd",
    accent_hi="#6ba0ff",
    accent_fg="#0e1116",
    sel="#31496f",
    sel_text="#eaf1fb",
    error="#ff7b72",
    warn="#e3b341",
    info="#98a4b3",
    ok="#57d38c",
    xml_tag="#79b8ff",
    xml_attr="#e3b341",
    xml_value="#7ee787",
    xml_comment="#7d8792",
)
PALETTES: Dict[str, Palette] = {"light": LIGHT, "dark": DARK}

_CURRENT: Palette = LIGHT


def current() -> Palette:
    """The palette last applied - for widgets built outside the main window."""
    return _CURRENT


def apply(root: tk.Misc, mode: str = "light") -> Palette:
    """Style every ttk widget class and return the palette in use."""
    global _CURRENT
    p = _CURRENT = PALETTES.get(mode, LIGHT)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:                      # pragma: no cover - exotic build
        pass

    root.configure(background=p.bg)
    root.option_add("*Font", BASE_FONT)

    # -- containers and text ------------------------------------------------
    style.configure(".", background=p.bg, foreground=p.text,
                    fieldbackground=p.surface, bordercolor=p.border,
                    lightcolor=p.bg, darkcolor=p.bg, font=BASE_FONT)
    style.configure("TFrame", background=p.bg)
    style.configure("TLabel", background=p.bg, foreground=p.text)
    style.configure("TLabelframe", background=p.bg, bordercolor=p.border)
    style.configure("TLabelframe.Label", background=p.bg, foreground=p.muted)
    style.configure("TPanedwindow", background=p.bg)
    style.configure("Sash", sashthickness=6, gripcount=0, background=p.border)

    # a section heading inside a form, and the small grey caption above a tree
    style.configure("Section.TLabel", background=p.bg, foreground=p.accent,
                    font=BOLD_FONT)
    style.configure("Caption.TLabel", background=p.bg, foreground=p.muted,
                    font=BOLD_FONT)
    style.configure("Muted.TLabel", background=p.bg, foreground=p.muted)
    style.configure("Status.TLabel", background=p.raised, foreground=p.muted,
                    padding=(8, 4))
    style.configure("Toolbar.TFrame", background=p.raised)
    style.configure("Toolbar.TLabel", background=p.raised, foreground=p.muted)

    # -- buttons ------------------------------------------------------------
    style.configure("TButton", background=p.surface, foreground=p.text,
                    bordercolor=p.border, focuscolor=p.accent,
                    padding=(10, 5), relief="flat")
    style.map("TButton",
              background=[("pressed", p.sel), ("active", p.raised),
                          ("disabled", p.bg)],
              foreground=[("disabled", p.muted)],
              bordercolor=[("active", p.accent)])

    style.configure("Accent.TButton", background=p.accent, foreground=p.accent_fg,
                    bordercolor=p.accent, padding=(12, 5), relief="flat",
                    font=BOLD_FONT)
    style.map("Accent.TButton",
              background=[("pressed", p.accent_hi), ("active", p.accent_hi),
                          ("disabled", p.border)],
              foreground=[("disabled", p.muted)])

    # -- entries ------------------------------------------------------------
    for cls in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(cls, fieldbackground=p.surface, background=p.surface,
                        foreground=p.text, bordercolor=p.border,
                        insertcolor=p.text, arrowcolor=p.muted, padding=3)
        style.map(cls,
                  bordercolor=[("focus", p.accent)],
                  fieldbackground=[("readonly", p.raised), ("disabled", p.bg)],
                  foreground=[("readonly", p.muted), ("disabled", p.muted)],
                  arrowcolor=[("active", p.accent)])

    # -- notebook -----------------------------------------------------------
    style.configure("TNotebook", background=p.bg, bordercolor=p.border,
                    tabmargins=(4, 4, 0, 0))
    style.configure("TNotebook.Tab", background=p.bg, foreground=p.muted,
                    bordercolor=p.border, padding=(14, 7), font=BASE_FONT)
    style.map("TNotebook.Tab",
              background=[("selected", p.surface), ("active", p.raised)],
              foreground=[("selected", p.accent), ("active", p.text)],
              font=[("selected", BOLD_FONT)])

    # -- trees --------------------------------------------------------------
    style.configure("Treeview", background=p.surface, fieldbackground=p.surface,
                    foreground=p.text, bordercolor=p.border, rowheight=23,
                    relief="flat")
    style.map("Treeview",
              background=[("selected", p.sel)],
              foreground=[("selected", p.sel_text)])
    style.configure("Treeview.Heading", background=p.raised, foreground=p.muted,
                    bordercolor=p.border, relief="flat", padding=(6, 5),
                    font=BOLD_FONT)
    style.map("Treeview.Heading",
              background=[("active", p.sel)],
              foreground=[("active", p.accent)])

    # -- scrollbars ---------------------------------------------------------
    for cls in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(cls, background=p.raised, troughcolor=p.bg,
                        bordercolor=p.bg, arrowcolor=p.muted,
                        gripcount=0, relief="flat")
        style.map(cls,
                  background=[("pressed", p.accent), ("active", p.border)],
                  arrowcolor=[("active", p.accent)])

    return p


def style_menu(menu: tk.Menu, p: Palette) -> None:
    """tk.Menu is a classic widget: it takes plain colour options."""
    menu.configure(background=p.surface, foreground=p.text,
                   activebackground=p.accent, activeforeground=p.accent_fg,
                   borderwidth=0, activeborderwidth=0)


def style_listbox(box: tk.Listbox, p: Palette) -> None:
    box.configure(background=p.surface, foreground=p.text,
                  selectbackground=p.sel, selectforeground=p.sel_text,
                  highlightthickness=1, highlightbackground=p.border,
                  highlightcolor=p.accent, borderwidth=0, activestyle="none",
                  font=BASE_FONT)


def style_text(text: tk.Text, p: Palette) -> None:
    text.configure(background=p.surface, foreground=p.text,
                   insertbackground=p.text,
                   selectbackground=p.sel, selectforeground=p.sel_text,
                   highlightthickness=1, highlightbackground=p.border,
                   highlightcolor=p.border, borderwidth=0,
                   font=MONO_FONT, padx=8, pady=6)


def tag_tree_severity(tree: ttk.Treeview, p: Palette) -> None:
    tree.tag_configure("ERROR", foreground=p.error)
    tree.tag_configure("WARNING", foreground=p.warn)
    tree.tag_configure("INFO", foreground=p.info)


def stripe(tree: ttk.Treeview, p: Palette) -> None:
    """Register the alternating row tags; rows opt in with tags=("odd",)."""
    tree.tag_configure("even", background=p.surface)
    tree.tag_configure("odd", background=p.raised)


# --------------------------------------------------------------------------
# ARXML preview highlighting
# --------------------------------------------------------------------------
_XML = re.compile(
    r"(?P<comment><!--.*?-->)"
    r"|(?P<tag></?[A-Za-z_][\w.-]*)"
    r"|(?P<attr>\s[A-Za-z_][\w.-]*)(?==\")"
    r"|(?P<value>\"[^\"]*\")",
    re.S)

# a file this big is being scrolled, not read - skip the colouring rather than
# freeze the window for several seconds
MAX_HIGHLIGHT_CHARS = 600_000


def highlight_xml(widget: tk.Text, p: Palette, source: str) -> bool:
    """Colour tags, attributes, values and comments.  True when it ran."""
    for tag in ("xtag", "xattr", "xvalue", "xcomment"):
        widget.tag_remove(tag, "1.0", "end")
    if len(source) > MAX_HIGHLIGHT_CHARS:
        return False

    widget.tag_configure("xtag", foreground=p.xml_tag)
    widget.tag_configure("xattr", foreground=p.xml_attr)
    widget.tag_configure("xvalue", foreground=p.xml_value)
    widget.tag_configure("xcomment", foreground=p.xml_comment)

    # one pass over the text; offsets are turned into line.column by bisecting
    # the line start table, which beats calling Text.search per match
    starts = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            starts.append(i + 1)
    import bisect

    def index(offset: int) -> str:
        line = bisect.bisect_right(starts, offset) - 1
        return "%d.%d" % (line + 1, offset - starts[line])

    tag_of = {"comment": "xcomment", "tag": "xtag",
              "attr": "xattr", "value": "xvalue"}
    ranges: Dict[str, list] = {t: [] for t in tag_of.values()}
    for m in _XML.finditer(source):
        kind = m.lastgroup
        ranges[tag_of[kind]] += [index(m.start(kind)), index(m.end(kind))]
    for tag, pairs in ranges.items():
        if pairs:
            widget.tag_add(tag, *pairs)
    return True

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

# Windows ships the icon font its own shell draws with, which beats any glyph
# that can be typed - but only where it exists, so nothing may depend on it.
ICON_FAMILY = "Segoe MDL2 Assets"
# private-use code points, written as numbers so the source stays ASCII
ICONS = {
    "excel":    chr(0xE9F9),   # sheet with a chart on it
    "open":     chr(0xED25),   # open folder
    "save":     chr(0xE74E),   # floppy disk
    "check":    chr(0xE930),   # tick in a circle
    "generate": chr(0xE896),   # arrow into a tray
    "add":      chr(0xE710),   # plus
    "delete":   chr(0xE74D),   # waste basket
    "error":    chr(0xEA39),   # cross in a circle
    "warn":     chr(0xE7BA),   # triangle
    "info":     chr(0xE946),   # i in a circle
}
_HAVE_ICONS: Dict[str, bool] = {}


def icon_font(size: int = 12):
    return (ICON_FAMILY, size)


def has_icons(root: tk.Misc) -> bool:
    """False on a machine without the font, so callers fall back to text."""
    if "ok" not in _HAVE_ICONS:
        try:
            import tkinter.font as tkfont
            _HAVE_ICONS["ok"] = ICON_FAMILY in set(tkfont.families(root))
        except Exception:                    # pragma: no cover - exotic build
            _HAVE_ICONS["ok"] = False
    return _HAVE_ICONS["ok"]


def icon(name: str, root: tk.Misc = None) -> str:
    """The glyph, or an empty string where the font is missing."""
    if root is not None and not has_icons(root):
        return ""
    return ICONS.get(name, "")


class Palette(dict):
    """A colour set; attribute access keeps the call sites readable."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None


LIGHT = Palette(
    name="light",
    bg="#e4eaf2",            # window / tab strip
    surface="#ffffff",       # panels, entries, trees
    raised="#f1f5fa",        # toolbar, status bar
    stripe="#e7eef7",        # every other tree row
    head="#dae3ef",          # tree column headings
    border="#7a8ea8",
    text="#121922",
    muted="#47566a",
    accent="#1d4ed8",
    accent_hi="#1e40af",
    accent_fg="#ffffff",
    sel="#bfd7fb",
    sel_text="#0a1c36",
    error="#a3160f",
    warn="#7a4e00",
    info="#3c4a5c",
    ok="#0f5c2e",
    error_bg="#fbe4e2",      # the row behind a finding, not just its text
    warn_bg="#fbefda",
    info_bg="#e9eff8",
    # ARXML preview
    xml_tag="#0a56ae",
    xml_attr="#7a4e00",
    xml_value="#0f5c2e",
    xml_comment="#6b7887",
    # toolbar and grouping
    card="#f7fafd",          # the panel a form section sits on
    rule="#c3d0e0",          # hairline under a section heading
    hover="#dce7f6",         # toolbar button under the pointer
    press="#c6d9f2",
)

DARK = Palette(
    name="dark",
    bg="#151920",
    surface="#1f242c",
    raised="#2a313c",
    stripe="#2b323d",
    head="#333c49",
    border="#697787",
    text="#eff4fa",
    muted="#adbaca",
    accent="#69a6ff",
    accent_hi="#8dbcff",
    accent_fg="#0b0f14",
    sel="#2f5390",
    sel_text="#f2f7fd",
    error="#ff8b82",
    warn="#f0c355",
    info="#adbaca",
    ok="#6fe0a0",
    error_bg="#3d211f",
    warn_bg="#3a3220",
    info_bg="#252d38",
    xml_tag="#8cc2ff",
    xml_attr="#f0c355",
    xml_value="#8ef2a6",
    xml_comment="#8b96a3",
    card="#232932",
    rule="#3c4653",
    hover="#333d4b",
    press="#3d4959",
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
    style.configure("TLabelframe.Label", background=p.bg, foreground=p.text,
                    font=BOLD_FONT)
    style.configure("TPanedwindow", background=p.bg)
    style.configure("Sash", sashthickness=6, gripcount=0, background=p.border)

    # a section heading inside a form, and the small grey caption above a tree
    style.configure("Section.TLabel", background=p.bg, foreground=p.accent,
                    font=BOLD_FONT)
    style.configure("Caption.TLabel", background=p.bg, foreground=p.text,
                    font=BOLD_FONT)
    style.configure("Muted.TLabel", background=p.bg, foreground=p.muted)
    style.configure("Status.TLabel", background=p.raised, foreground=p.text,
                    padding=(8, 4))
    style.configure("Toolbar.TFrame", background=p.raised)
    style.configure("Toolbar.TLabel", background=p.raised, foreground=p.text)
    style.configure("ToolbarMuted.TLabel", background=p.raised, foreground=p.muted)

    # a hairline: a 1px Frame is the only separator clam draws predictably
    style.configure("Rule.TFrame", background=p.rule)
    style.configure("ToolRule.TFrame", background=p.border)

    # a form section: heading strip plus the panel its fields sit on
    style.configure("Card.TFrame", background=p.card)
    style.configure("Card.TLabel", background=p.card, foreground=p.text)
    style.configure("CardMuted.TLabel", background=p.card, foreground=p.muted)
    style.configure("CardTitle.TLabel", background=p.card, foreground=p.accent,
                    font=HEAD_FONT)

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
    style.configure("Treeview.Heading", background=p.head, foreground=p.text,
                    bordercolor=p.border, relief="flat", padding=(6, 5),
                    font=BOLD_FONT)
    style.map("Treeview.Heading",
              background=[("active", p.sel)],
              foreground=[("active", p.accent_hi)])

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
    tree.tag_configure("ERROR", foreground=p.error, background=p.error_bg)
    tree.tag_configure("WARNING", foreground=p.warn, background=p.warn_bg)
    tree.tag_configure("INFO", foreground=p.info, background=p.info_bg)


def stripe(tree: ttk.Treeview, p: Palette) -> None:
    """Register the alternating row tags; rows opt in with tags=("odd",)."""
    tree.tag_configure("even", background=p.surface)
    tree.tag_configure("odd", background=p.stripe)


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

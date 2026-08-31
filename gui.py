"""Tkinter front end for the SOME/IP configuration database.

    python gui.py [file.arxml | file.someip.json]

Import the customer workbooks, review every configuration item, fix what the
workbook got wrong, and regenerate the DaVinci Classic ARXML.
"""

from __future__ import annotations

import datetime
import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import arxml_gen
import arxml_io
import licensing
import theme
import validate as validator
from someip_model import (
    BASE_TYPES, ArrayType, EnumLiteral, EnumType, Event, EventGroup, Project,
    Service, StructMember, StructType, default_array_name, parse_int,
)

APP_TITLE = "SOME/IP Config Tool - ZAFL"
BASE_TYPE_CHOICES = sorted({k for k in BASE_TYPES})


# --------------------------------------------------------------------------
# attribute path helpers
# --------------------------------------------------------------------------
def get_path(obj: Any, path: str) -> Any:
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def set_path(obj: Any, path: str, value: Any) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        obj = getattr(obj, part)
    setattr(obj, parts[-1], value)


# --------------------------------------------------------------------------
# a label/entry form driven by a field spec
# --------------------------------------------------------------------------
# spec entry: (label, attribute path, kind, options)
#   kind: "str" | "int" | "float" | "hex" | "choice" | "ro"
class Form(ttk.Frame):
    def __init__(self, master, spec: List[Tuple], columns: int = 1, **kw):
        super().__init__(master, **kw)
        self.spec = spec
        self.vars: Dict[str, tk.StringVar] = {}
        self.widgets: Dict[str, tk.Widget] = {}
        self.target: Any = None

        per_col = (len(spec) + columns - 1) // columns
        for i, item in enumerate(spec):
            label, path, kind = item[0], item[1], item[2]
            opts = item[3] if len(item) > 3 else None
            col, row = divmod(i, per_col)
            c0 = col * 3                      # label | field | slack
            if label.startswith("--"):
                # a heading plus a hairline running to the edge of its column:
                # thirty identical rows need something to break them up, and a
                # line does it where a colour change alone did not
                head = ttk.Frame(self)
                head.grid(row=row, column=c0, columnspan=3, sticky="ew",
                          pady=(14, 4), padx=(6, 12))
                ttk.Label(head, text=label[2:], style="Section.TLabel").pack(side="left")
                ttk.Frame(head, style="Rule.TFrame", height=1).pack(
                    side="left", fill="x", expand=True, padx=(8, 0), pady=(7, 0))
                continue
            ttk.Label(self, text=label).grid(row=row, column=c0, sticky="w", padx=(8, 4), pady=2)
            var = tk.StringVar()
            self.vars[path] = var
            if kind == "choice":
                w = ttk.Combobox(self, textvariable=var, values=list(opts or []), width=30)
            else:
                w = ttk.Entry(self, textvariable=var, width=32,
                              state="readonly" if kind == "ro" else "normal")
            w.grid(row=row, column=c0 + 1, sticky="ew", padx=(0, 12), pady=2)
            self.widgets[path] = w
        # On a wide two-column tab the fields keep the width they asked for and
        # a spacer takes the slack, rather than every entry stretching to the
        # window edge.  A dialog is only as wide as its content, so there is no
        # slack to give away and the field takes it all.
        for c in range(columns):
            self.columnconfigure(c * 3 + 1, weight=0 if columns > 1 else 1,
                                 minsize=210)
            self.columnconfigure(c * 3 + 2, weight=1 if columns > 1 else 0)

    def load(self, target: Any) -> None:
        self.target = target
        for item in self.spec:
            path, kind = item[1], item[2]
            if path not in self.vars:
                continue
            try:
                self.vars[path].set("" if target is None else str(get_path(target, path)))
            except AttributeError:
                self.vars[path].set("")

    def apply(self) -> None:
        if self.target is None:
            return
        for item in self.spec:
            label, path, kind = item[0], item[1], item[2]
            if path not in self.vars or kind == "ro":
                continue
            raw = self.vars[path].get().strip()
            try:
                if kind == "int":
                    value: Any = int(raw or 0)
                elif kind == "float":
                    value = float(raw or 0)
                elif kind == "hex":
                    value = "0x%04X" % parse_int(raw)
                else:
                    value = raw
            except ValueError:
                raise ValueError("'%s' is not a valid value for %s" % (raw, label))
            set_path(self.target, path, value)



class ToolButton(tk.Frame):
    """A toolbar button carrying an icon above nothing but its own label.

    ttk.Button draws all of its text in one font, and the icon font has no
    letters in it, so icon-and-label needs two widgets - which means the hover,
    pressed and disabled looks are drawn here rather than by the theme engine.
    """

    def __init__(self, master, text: str, icon_name: str, command,
                 accent: bool = False, compact: bool = False,
                 surface: str = "raised"):
        p = theme.current()
        self.surface = surface          # the palette key of what it sits on
        super().__init__(master, background=p[surface], cursor="hand2",
                         padx=0, pady=0)
        self.command, self.accent, self.compact = command, accent, compact
        self._state = "normal"
        self._hover = False

        glyph = theme.icon(icon_name, master)
        self.icon = tk.Label(self, text=glyph, font=theme.icon_font(15 if not compact else 12),
                             background=p[surface], foreground=p.text)
        self.label = tk.Label(self, text=text, font=theme.BOLD_FONT if accent else theme.BASE_FONT,
                              background=p[surface], foreground=p.text)
        if glyph:
            self.icon.pack(side="left", padx=(10 if not compact else 6, 0), pady=5)
            self.label.pack(side="left", padx=(6, 10 if not compact else 6), pady=5)
        else:                                  # no icon font: a plain text button
            self.label.pack(side="left", padx=10, pady=5)

        for w in (self, self.icon, self.label):
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)
            w.bind("<Button-1>", self._press)
            w.bind("<ButtonRelease-1>", self._release)
        self.restyle()

    # -- looks ----------------------------------------------------------
    def restyle(self, pressed: bool = False) -> None:
        p = theme.current()
        base = p[self.surface]
        if self._state == "disabled":
            bg, fg = (p.border, p.muted) if self.accent else (base, p.muted)
        elif pressed:
            bg = p.accent_hi if self.accent else p.press
            fg = p.accent_fg if self.accent else p.text
        elif self._hover:
            bg = p.accent_hi if self.accent else p.hover
            fg = p.accent_fg if self.accent else p.text
        else:
            bg = p.accent if self.accent else base
            fg = p.accent_fg if self.accent else p.text
        self.configure(background=bg)
        for w in (self.icon, self.label):
            w.configure(background=bg, foreground=fg)
        self.configure(cursor="arrow" if self._state == "disabled" else "hand2")

    def configure_state(self, state: str) -> None:
        self._state = state
        self.restyle()

    # ttk-compatible enough for the licence gate to treat it like a Button
    def __getitem__(self, key):
        return self._state if key == "state" else tk.Frame.__getitem__(self, key)

    def configure(self, cnf=None, **kw):       # noqa: D401 - matches tk signature
        if "state" in kw:
            self._state = kw.pop("state")
            self.restyle()
            if not kw:
                return None
        return tk.Frame.configure(self, cnf, **kw)

    # -- events ---------------------------------------------------------
    def _enter(self, _e=None):
        self._hover = True
        self.restyle()

    def _leave(self, _e=None):
        self._hover = False
        self.restyle()

    def _press(self, _e=None):
        if self._state != "disabled":
            self.restyle(pressed=True)

    def _release(self, _e=None):
        if self._state == "disabled":
            return
        self.restyle()
        if self._hover:
            self.command()


def _align_columns(tree: ttk.Treeview, right=(), centre=()) -> None:
    """Numbers read down a column when they are flush right; the heading has to
    move with them or the two disagree by a column width."""
    for c in right:
        tree.column(c, anchor="e")
        tree.heading(c, anchor="e")
    for c in centre:
        tree.column(c, anchor="center")
        tree.heading(c, anchor="center")
    for c in tree["columns"]:
        if c not in right and c not in centre:
            tree.heading(c, anchor="w")


def _row_tag(tree: ttk.Treeview) -> str:
    """Alternating row colour: long tables are hard to read without one."""
    return "odd" if len(tree.get_children("")) % 2 else "even"


class FormDialog(tk.Toplevel):
    """Modal dialog built from the same field spec as Form.

    Long specs (a service has ~45 fields) would run off the bottom of the
    screen, so the form lives inside a scrollable canvas and the button bar
    stays pinned underneath it.
    """

    def __init__(self, master, title: str, spec: List[Tuple], target: Any):
        super().__init__(master)
        self.title(title)
        self.transient(master)
        self.result = False

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        body = ttk.Frame(self)
        body.grid(row=0, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(body, highlightthickness=0, borderwidth=0,
                                background=theme.current().bg)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self._vsb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._set_scroll)

        self.form = Form(self.canvas, spec, padding=(8, 8))
        self._win = self.canvas.create_window((0, 0), window=self.form, anchor="nw")
        self.form.load(target)
        self.form.bind("<Configure>", self._on_form_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self._bar = ttk.Frame(self)
        self._bar.grid(row=1, column=0, sticky="e", padx=8, pady=8)
        ttk.Button(self._bar, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(self._bar, text="Cancel", command=self.destroy).pack(side="left")

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Prior>", lambda _e: self.canvas.yview_scroll(-1, "pages"))
        self.bind("<Next>", lambda _e: self.canvas.yview_scroll(1, "pages"))
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel)   # X11
        self.bind_all("<Button-5>", self._on_mousewheel)
        self.bind("<Destroy>", self._on_destroy)

        self._size_to_screen(master)
        self.grab_set()
        self.wait_window(self)

    # ------------------------------------------------------------------
    def _size_to_screen(self, master) -> None:
        """Fit the dialog to its content, capped to what the screen can show."""
        self.update_idletasks()
        need_w = self.form.winfo_reqwidth() + 20          # + scrollbar
        need_h = self.form.winfo_reqheight() + self._bar.winfo_reqheight() + 24
        max_w = int(self.winfo_screenwidth() * 0.9)
        max_h = int(self.winfo_screenheight() * 0.82)
        w, h = min(need_w, max_w), min(need_h, max_h)

        try:
            x = master.winfo_rootx() + (master.winfo_width() - w) // 2
            y = master.winfo_rooty() + (master.winfo_height() - h) // 3
        except tk.TclError:
            x = y = 0
        x = max(0, min(x, self.winfo_screenwidth() - w))
        y = max(0, min(y, self.winfo_screenheight() - h))
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.minsize(320, 200)

    def _set_scroll(self, first: str, last: str) -> None:
        """Show the scrollbar only while the form is taller than the canvas."""
        if float(first) <= 0.0 and float(last) >= 1.0:
            self._vsb.grid_remove()
        else:
            self._vsb.grid(row=0, column=1, sticky="ns")
        self._vsb.set(first, last)

    def _on_form_configure(self, _e=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        # let the form stretch to the full canvas width
        self.canvas.itemconfigure(self._win, width=event.width)

    def _on_mousewheel(self, event) -> None:
        if not self.canvas.winfo_exists():
            return
        first, last = self.canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return                                        # nothing to scroll
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")

    def _on_destroy(self, event) -> None:
        if event.widget is not self:
            return
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                self.unbind_all(seq)
            except tk.TclError:
                pass

    def _ok(self) -> None:
        try:
            self.form.apply()
        except ValueError as exc:
            messagebox.showerror("Invalid value", str(exc), parent=self)
            return
        self.result = True
        self.destroy()


# --------------------------------------------------------------------------
# field specifications
# --------------------------------------------------------------------------
PROJECT_SPEC = [
    ("--Identification", "", "sep"),
    ("Project name", "name", "str"),
    ("ECU instance", "ecu_name", "str"),
    ("AUTOSAR release", "autosar_release", "str"),
    ("XSD schema", "schema", "str"),
    ("--Ethernet cluster", "", "sep"),
    ("Cluster name", "cluster_name", "str"),
    ("Physical channel", "channel_name", "str"),
    ("Baudrate [bit/s]", "baudrate", "int"),
    ("Physical layer", "physical_layer_type", "str"),
    ("ECU MAC (unicast)", "ecu_mac_unicast", "str"),
    ("--VLAN / multicast", "", "sep"),
    ("VLAN name", "vlan_name", "str"),
    ("VLAN id", "vlan_id", "int"),
    ("VLAN priority", "vlan_priority", "int"),
    ("Network mask", "network_mask", "str"),
    ("Multicast IPv4", "multicast_ipv4", "str"),
    ("Multicast MAC", "multicast_mac", "str"),
    ("--Generation options", "", "sep"),
    ("ARXML template", "template", "str"),
    ("COM tx time base [s]", "com_tx_time_base", "float"),
    ("Base type package", "base_type_package", "str"),
    ("Platform impl type package", "platform_type_package", "str"),
    ("Local endpoint tag", "local_endpoint_tag", "str"),
    ("Port iface prefix (provider)", "port_iface_prefix_provider", "str"),
    ("Port iface prefix (consumer)", "port_iface_prefix_consumer", "str"),
]

SERVICE_SPEC = [
    ("--Service", "", "sep"),
    ("Role", "role", "choice", ["provider", "consumer"]),
    ("Short tag", "tag", "str"),
    ("ServiceInstanceName", "instance_name", "str"),
    ("ServiceInterface", "interface_name", "str"),
    ("ServiceInterfaceId", "interface_id", "hex"),
    ("ServiceInstanceId", "instance_id", "hex"),
    ("Major version", "major_version", "int"),
    ("Minor version", "minor_version", "int"),
    ("Deployment name", "deployment_name", "str"),
    ("Service instance name", "service_instance_name", "str"),
    ("Machine mapping name", "mapping_name", "str"),
    ("Local UDP port", "udp_port", "int"),
    ("TCP port", "tcp_port", "str"),
    ("Static event routing", "routing_mode", "choice", ["StaticUnicast", "StaticMulticast"]),
    ("--Local MCU endpoint", "", "sep"),
    ("Zone", "local.zone", "str"),
    ("IPv4 address", "local.ipv4", "str"),
    ("MAC address", "local.mac", "str"),
    ("--Remote provider (consumer only)", "", "sep"),
    ("Zone", "remote.zone", "str"),
    ("IPv4 address", "remote.ipv4", "str"),
    ("MAC address", "remote.mac", "str"),
    ("UDP port", "remote_udp_port", "int"),
    ("--Service discovery", "", "sep"),
    ("SD UDP port", "sd_udp_port", "int"),
    ("TTL", "sd.ttl", "int"),
    ("Initial delay min [s]", "sd.initial_delay_min", "float"),
    ("Initial delay max [s]", "sd.initial_delay_max", "float"),
    ("Repetition base delay [s]", "sd.repetition_base_delay", "float"),
    ("Repetition max", "sd.repetition_max", "int"),
    ("Cyclic offer delay [s]", "sd.cyclic_offer_delay", "float"),
    ("Req/resp delay min [s]", "sd.request_response_delay_min", "float"),
    ("Req/resp delay max [s]", "sd.request_response_delay_max", "float"),
    ("--TSN", "", "sep"),
    ("Zone", "tsn.zone", "str"),
    ("Topology", "tsn.topology", "str"),
    ("VLAN id", "tsn.vlan_id", "int"),
    ("VLAN priority", "tsn.vlan_priority", "int"),
    ("Traffic class", "tsn.traffic_class", "str"),
    ("Traffic profile", "tsn.traffic_profile", "str"),
    ("--Local TSN switch", "", "sep"),
    ("Model", "tsn_switch.model", "str"),
    ("Bridge MAC", "tsn_switch.bridge_mac", "str"),
    ("Ring port CW neighbor", "tsn_switch.ring_port_cw_neighbor", "str"),
    ("Ring port CCW neighbor", "tsn_switch.ring_port_ccw_neighbor", "str"),
]

EVENT_SPEC = [
    ("Index", "index", "int"),
    ("Name", "name", "str"),
    ("EventId", "event_id", "hex"),
    ("Payload length [bytes]", "payload_length", "int"),
    ("PDU length override (0=auto)", "pdu_length_override", "int"),
    ("Serializer struct", "serializer", "str"),
    ("Transport", "transport", "choice", ["UDP", "TCP"]),
    ("Event group", "event_group", "str"),
    ("Max segment length", "max_segment_length", "str"),
    ("Separation time", "separation_time", "str"),
]

GROUP_SPEC = [
    ("Index", "index", "int"),
    ("Name", "name", "str"),
    ("EventGroupId", "group_id", "hex"),
    ("Destination zone", "dest_zone", "str"),
    ("Destination IPv4", "dest_ipv4", "str"),
    ("Destination MAC", "dest_mac", "str"),
    ("Destination UDP port", "dest_udp_port", "int"),
    ("Transport", "transport", "choice", ["UDP", "TCP"]),
    ("Routing mode", "routing_mode", "choice", ["StaticUnicast", "StaticMulticast"]),
]

ARRAY_SPEC = [
    ("Name", "name", "str"),
    ("Element type", "element_type", "str"),
    ("Element short name (blank = auto)", "element_name", "str"),
    ("Array size", "size", "int"),
    ("Size semantics", "size_semantics", "choice", ["FIXED-SIZE", "VARIABLE-SIZE"]),
    ("Description", "description", "str"),
]

STRUCT_SPEC = [("Name", "name", "str"), ("Description", "description", "str")]
MEMBER_SPEC = [("Element name", "name", "str"), ("Type", "type", "str"),
               ("Description", "description", "str")]
ENUM_SPEC = [("Name", "name", "str"), ("Base type", "base_type", "choice", BASE_TYPE_CHOICES),
             ("Description", "description", "str")]
LITERAL_SPEC = [("Literal", "name", "str"), ("Value", "value", "int"),
                ("AUTOSAR <VT> text", "vt", "str"), ("Description", "description", "str")]


# --------------------------------------------------------------------------
# main window
# --------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self, initial: Optional[str] = None):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1240x820")
        self.prj = Project()
        self.path: Optional[str] = None
        self._tool_buttons: list = []
        self._svc_buttons: list = []

        self.theme_mode = tk.StringVar(value="light")
        self.pal = theme.apply(self, self.theme_mode.get())

        self._build_menu()
        self._build_toolbar()

        # Packed before the notebook on purpose: the notebook expands, and pack
        # hands the whole remaining cavity to the first expanding slave, so a
        # status bar added afterwards is squeezed to a single pixel - which is
        # what had been happening to every message the tool tried to show.
        self.status = tk.StringVar(value="Ready. Use File > Import Excel to start.")
        self.counts = tk.StringVar(value="")
        sbar = ttk.Frame(self, style="Toolbar.TFrame")
        sbar.pack(fill="x", side="bottom")
        ttk.Label(sbar, textvariable=self.status, anchor="w",
                  style="Status.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Frame(sbar, style="ToolRule.TFrame", width=1).pack(
            side="left", fill="y", pady=4)
        ttk.Label(sbar, textvariable=self.counts, anchor="e",
                  style="Status.TLabel").pack(side="left")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self._tab_project()
        self._tab_services()
        self._tab_events()
        self._tab_groups()
        self._tab_types()
        self._tab_check()
        self._tab_preview()

        self._restyle()
        self.refresh_license()
        if initial:
            self.open_file(initial)
        self.refresh()
        if not self.lic.valid:
            self.status.set(self.lic.summary()
                            + "  Generate ARXML and Save JSON are locked.")

    # ------------------------------------------------------------------
    # licensing
    # ------------------------------------------------------------------
    def _update_counts(self) -> None:
        """What is loaded, at a glance, so the tabs need not be counted by hand."""
        svc = self.prj.services
        if not svc:
            self.counts.set("nothing loaded")
            return
        self.counts.set("%d service(s)   %d event(s)   %d group(s)"
                        % (len(svc), sum(len(s.events) for s in svc),
                           sum(len(s.event_groups) for s in svc)))

    def _set_title(self) -> None:
        """One place, so opening a file cannot drop the licence marker."""
        name = os.path.basename(self.path) if self.path else "untitled"
        mark = "" if getattr(self, "lic", None) and self.lic.valid else "  [UNLICENSED]"
        self.title("%s - %s%s" % (APP_TITLE, name, mark))

    def refresh_license(self, announce: bool = False) -> None:
        """Re-read the licence and open or close the two locked actions."""
        self.lic = licensing.status()
        state = "normal" if self.lic.valid else "disabled"
        for btn in (self.btn_gen, self.btn_save):
            btn.configure(state=state)
        self.lic_label.configure(
            text="" if self.lic.valid else "unlicensed  •  ")
        for i in self.locked_entries:
            self.file_menu.entryconfigure(i, state=state)
        self._set_title()
        if announce:
            self.status.set(self.lic.summary())
        self._schedule_license_recheck()

    def _schedule_license_recheck(self) -> None:
        """Grey the two out the moment the licence lapses, rather than leaving
        buttons that look usable until someone presses one.

        The expiry instant is known, so this waits for it instead of polling;
        the hourly cap is only there to notice a licence file that changed
        underneath us, and to keep the delay inside what after() accepts.
        """
        if getattr(self, "_recheck_job", None):
            self.after_cancel(self._recheck_job)
            self._recheck_job = None
        delay = 3600.0
        exp = self.lic.payload.get("exp") if self.lic.valid else None
        if exp:
            try:
                left = (datetime.datetime.strptime(exp, licensing.MINUTE)
                        .replace(tzinfo=datetime.timezone.utc)
                        - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
                delay = min(delay, max(left, 0) + 1)
            except ValueError:
                pass
        self._recheck_job = self.after(int(delay * 1000), self._on_recheck)

    def _on_recheck(self) -> None:
        was = self.lic.valid
        self.refresh_license()
        if was and not self.lic.valid:
            self.status.set(self.lic.summary()
                            + "  Generate ARXML and Save JSON are locked.")

    def _licensed_for(self, action: str) -> bool:
        """Re-read before acting: the licence file can change, or expire, while
        the window sits open, and a stale enabled button would be a lie."""
        self.refresh_license()
        if self.lic.valid:
            return True
        messagebox.showwarning(
            "Licence required",
            "A licence is required to %s.\n\n%s" % (action, self.lic.reason))
        return False

    def show_license(self) -> None:
        self.refresh_license()
        st = self.lic
        found = licensing.all_licenses()
        # naming every copy on disk, not just the one in force: a second file
        # elsewhere is otherwise invisible, and editing the wrong one looks
        # like the check being ignored
        where = "\n".join(
            "  %s %s\n      %s" % ("[in use]" if s.path == st.path and s.valid
                                   else "[ignored]", p, s.summary())
            for p, s in found) or "  (none)"
        if st.valid:
            messagebox.showinfo(
                "Licence",
                "Valid.\n\nLicensed to : %s\nMachine     : %s\nExpires     : %s "
                "local time\n\nLicence files found:\n%s"
                % (st.payload.get("to") or "-", st.payload.get("mac", ""),
                   st.expires_local, where))
        else:
            messagebox.showwarning(
                "Licence",
                "%s\n\nWithout one you can still import workbooks, open files and "
                "look at everything; generating ARXML and saving the project JSON "
                "stay locked.\n\nThis machine: %s\n\nLicence files found:\n%s"
                % (st.summary(), ", ".join(licensing.machine_macs()) or "unknown",
                   where))

    def install_license(self) -> None:
        path = filedialog.askopenfilename(
            title="Licence file", filetypes=[("Licence", "*.key"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                dest = licensing.install(fh.read())
        except licensing.LicenseError as exc:
            messagebox.showerror("Licence", "That licence was not accepted:\n\n%s" % exc)
            return
        except OSError as exc:
            messagebox.showerror("Licence", "Cannot read it:\n\n%s" % exc)
            return
        self.refresh_license(announce=True)
        if self.lic.valid:
            messagebox.showinfo("Licence", "Installed to:\n%s\n\n%s"
                                % (dest, self.lic.summary()))
        else:
            messagebox.showwarning(
                "Licence", "The signature is good, but it does not apply here:\n\n%s"
                % self.lic.reason)

    def remove_license(self) -> None:
        """Delete the copy installed for this user - the one place a licence
        can otherwise linger without being obvious."""
        path = os.path.join(licensing.user_dir(), licensing.LICENSE_FILENAME)
        if not os.path.isfile(path):
            messagebox.showinfo("Licence", "Nothing is installed for this user.\n\n"
                                           "(%s does not exist)" % path)
            return
        if not messagebox.askyesno("Licence", "Delete this licence?\n\n%s\n\n"
                                              "The file itself is gone afterwards - "
                                              "keep a copy if you may need it again."
                                   % path):
            return
        try:
            os.remove(path)
        except OSError as exc:
            messagebox.showerror("Licence", "Could not delete it:\n\n%s" % exc)
            return
        self.refresh_license(announce=True)

    def show_machine_id(self) -> None:
        macs = licensing.machine_macs()
        text = "\n".join(macs) or "none could be read"
        if macs:
            self.clipboard_clear()
            self.clipboard_append(macs[0])
        messagebox.showinfo(
            "This machine",
            "Send this address to whoever issues licences.\n\n%s\n\n"
            "(the first one is on the clipboard)" % text)

    # ------------------------------------------------------------------
    def switch_theme(self) -> None:
        """Re-skin every widget in place - no restart, nothing rebuilt."""
        self.pal = theme.apply(self, self.theme_mode.get())
        self._restyle()
        self.refresh()
        if self.preview.get("1.0", "1.10").strip():
            self.refresh_preview()
        self.status.set("Switched to the %s theme." % self.theme_mode.get())

    def _restyle(self) -> None:
        """Recolour the classic tk widgets, which ttk styles do not reach."""
        p = self.pal
        theme.style_listbox(self.svc_list, p)
        theme.style_text(self.preview, p)
        theme.tag_tree_severity(self.chk_tree, p)
        for tree in (self.ev_tree, self.grp_tree, self.st_tree,
                     self.en_tree, self.ar_tree, self.chk_tree):
            theme.stripe(tree, p)
        self.svc_canvas.configure(background=p.bg)
        # the toolbar buttons draw themselves, so the palette has to reach them
        for btn in (self.btn_gen, self.btn_save,
                    *self._tool_buttons, *self._svc_buttons):
            btn.restyle()

    # ------------------------------------------------------------------
    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        f = tk.Menu(menu, tearoff=0)
        f.add_command(label="Import Excel workbook(s)...", command=self.import_excel)
        f.add_separator()
        f.add_command(label="Open ARXML...", command=self.open_arxml)
        f.add_command(label="Open project JSON...", command=self.open_json)
        f.add_command(label="Save project JSON", command=self.save_json)
        f.add_command(label="Save project JSON as...", command=lambda: self.save_json(True))
        f.add_separator()
        f.add_command(label="Generate ARXML...", command=self.generate_arxml)
        f.add_separator()
        f.add_command(label="Exit", command=self.destroy)
        menu.add_cascade(label="File", menu=f)
        self.file_menu = f
        # the two entries a licence unlocks, by their index in the File menu
        self.locked_entries = [f.index("Save project JSON"),
                               f.index("Save project JSON as..."),
                               f.index("Generate ARXML...")]

        e = tk.Menu(menu, tearoff=0)
        e.add_command(label="Add service", command=self.add_service)
        e.add_command(label="Delete service", command=self.del_service)
        menu.add_cascade(label="Edit", menu=e)

        v = tk.Menu(menu, tearoff=0)
        for label, value in (("Light theme", "light"), ("Dark theme", "dark")):
            v.add_radiobutton(label=label, value=value, variable=self.theme_mode,
                              command=self.switch_theme)
        menu.add_cascade(label="View", menu=v)

        h = tk.Menu(menu, tearoff=0)
        h.add_command(label="Licence status...", command=self.show_license)
        h.add_command(label="Install licence...", command=self.install_license)
        h.add_command(label="Remove installed licence...", command=self.remove_license)
        h.add_command(label="This machine's address...", command=self.show_machine_id)
        h.add_separator()
        h.add_command(label="About", command=lambda: messagebox.showinfo(
            "About", APP_TITLE + "\n\nExcel -> model -> ARXML for DaVinci Classic.\n"
            "See MAPPING.md for the full field mapping."))
        menu.add_cascade(label="Help", menu=h)
        for m in (menu, f, e, v, h):
            theme.style_menu(m, self.pal)
        self.config(menu=menu)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, style="Toolbar.TFrame", padding=(8, 7))
        bar.pack(fill="x")
        # the last one is what the whole tool exists for, so it carries the accent
        def sep():
            ttk.Frame(bar, style="ToolRule.TFrame", width=1).pack(
                side="left", fill="y", padx=8, pady=3)

        # input, then output, then the one thing the tool exists for
        for text, ic, cmd in (("Import Excel", "excel", self.import_excel),
                              ("Open ARXML", "open", self.open_arxml)):
            b = ToolButton(bar, text, ic, cmd)
            b.pack(side="left", padx=(0, 2))
            self._tool_buttons.append(b)
        sep()
        self.btn_save = ToolButton(bar, "Save JSON", "save", self.save_json)
        self.btn_save.pack(side="left", padx=(0, 2))
        b = ToolButton(bar, "Validate", "check", self.run_validate)
        b.pack(side="left")
        self._tool_buttons.append(b)
        sep()
        self.btn_gen = ToolButton(bar, "Generate ARXML", "generate",
                                  self.generate_arxml, accent=True)
        self.btn_gen.pack(side="left")

        self.file_label = ttk.Label(bar, text="(no file)", style="Toolbar.TLabel")
        self.file_label.pack(side="right", padx=(8, 2))
        self.lic_label = ttk.Label(bar, text="", style="ToolbarMuted.TLabel")
        self.lic_label.pack(side="right")

    # ------------------------------------------------------------------
    # tabs
    # ------------------------------------------------------------------
    def _tab_project(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Project")
        self.project_form = Form(tab, PROJECT_SPEC, columns=2)
        self.project_form.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Button(tab, text="Apply", style="Accent.TButton",
                   command=self._apply_project).pack(anchor="w", padx=12, pady=8)

    def _apply_project(self) -> None:
        try:
            self.project_form.apply()
        except ValueError as exc:
            messagebox.showerror("Invalid value", str(exc))
            return
        self.refresh()
        self.status.set("Project settings applied.")

    def _commit_forms(self) -> bool:
        """Push what is typed in the tab forms into the model.

        The Project and Services tabs are plain forms with an Apply button.
        Without this, a value typed into a box but not applied - a port
        interface prefix, a UDP port - is silently dropped by Generate, Save
        and Check, and the file comes out with the old value.
        """
        for tab, form in (("Project", self.project_form), ("Services", self.service_form)):
            try:
                form.apply()
            except ValueError as exc:
                messagebox.showerror("Invalid value", "%s tab: %s" % (tab, exc))
                self.nb.select(0 if tab == "Project" else 1)
                return False
        return True

    def _tab_services(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Services")
        left = ttk.Frame(tab)
        left.pack(side="left", fill="y", padx=(8, 0), pady=8)
        cap = ttk.Frame(left)
        cap.pack(fill="x", pady=(0, 4))
        ttk.Label(cap, text="Services", style="Caption.TLabel").pack(side="left")
        ttk.Frame(cap, style="Rule.TFrame", height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=(7, 0))
        self.svc_list = tk.Listbox(left, width=22, exportselection=False)
        self.svc_list.pack(fill="y", expand=True)
        self.svc_list.bind("<<ListboxSelect>>", lambda _e: self._show_service())
        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(6, 0))
        # next to the list they act on, rather than only in the Edit menu
        for text, ic, cmd in (("Add", "add", self.add_service),
                              ("Delete", "delete", self.del_service)):
            b = ToolButton(btns, text, ic, cmd, compact=True, surface="bg")
            b.pack(side="left", padx=(0, 4))
            self._svc_buttons.append(b)

        right = ttk.Frame(tab)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        canvas = self.svc_canvas = tk.Canvas(right, highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        holder = ttk.Frame(canvas)
        holder.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=holder, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.service_form = Form(holder, SERVICE_SPEC, columns=2)
        self.service_form.pack(fill="both", expand=True)
        ttk.Button(holder, text="Apply", style="Accent.TButton",
                   command=self._apply_service).pack(anchor="w", pady=8)

    def _apply_service(self) -> None:
        try:
            self.service_form.apply()
        except ValueError as exc:
            messagebox.showerror("Invalid value", str(exc))
            return
        self.refresh()
        self.status.set("Service settings applied.")

    def _tab_events(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Events")
        cols = ("service", "idx", "name", "id", "payload", "pdu", "header", "group",
                "serializer", "transport")
        self.ev_tree = ttk.Treeview(tab, columns=cols, show="headings", selectmode="browse")
        for c, t, w in (("service", "Service", 80), ("idx", "#", 40), ("name", "Event", 200),
                        ("id", "EventId", 80), ("payload", "Payload", 70), ("pdu", "PDU len", 70),
                        ("header", "Header id", 110), ("group", "Event group", 150),
                        ("serializer", "Serializer", 180), ("transport", "Tp", 50)):
            self.ev_tree.heading(c, text=t)
            self.ev_tree.column(c, width=w, anchor="w")
        _align_columns(self.ev_tree, right=("idx", "payload", "pdu"),
                       centre=("id", "header", "transport"))
        self.ev_tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.ev_tree.bind("<Double-1>", lambda _e: self.edit_event())
        bar = ttk.Frame(tab)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(bar, text="Add", command=self.add_event).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Edit", command=self.edit_event).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Delete", command=self.del_event).pack(side="left")

    def _tab_groups(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Event Groups")
        cols = ("service", "idx", "name", "id", "zone", "ip", "mac", "port", "tp", "mode")
        self.grp_tree = ttk.Treeview(tab, columns=cols, show="headings", selectmode="browse")
        for c, t, w in (("service", "Service", 80), ("idx", "#", 40), ("name", "Event group", 190),
                        ("id", "Id", 60), ("zone", "Dest zone", 100), ("ip", "Dest IPv4", 120),
                        ("mac", "Dest MAC", 150), ("port", "Dest port", 80),
                        ("tp", "Tp", 50), ("mode", "Routing mode", 120)):
            self.grp_tree.heading(c, text=t)
            self.grp_tree.column(c, width=w, anchor="w")
        _align_columns(self.grp_tree, right=("idx", "port"), centre=("id", "tp"))
        self.grp_tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.grp_tree.bind("<Double-1>", lambda _e: self.edit_group())
        bar = ttk.Frame(tab)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(bar, text="Add", command=self.add_group).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Edit", command=self.edit_group).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Delete", command=self.del_group).pack(side="left")

    def _tab_types(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Data Types")
        pane = ttk.PanedWindow(tab, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=8, pady=8)

        sf = ttk.Frame(pane)
        pane.add(sf, weight=3)
        ttk.Label(sf, text="Structures", style="Caption.TLabel").pack(anchor="w", pady=(0, 4))
        self.st_tree = ttk.Treeview(sf, columns=("type", "size", "desc"), selectmode="browse")
        self.st_tree.heading("#0", text="Struct / element")
        self.st_tree.heading("type", text="Type")
        self.st_tree.heading("size", text="Bytes")
        self.st_tree.heading("desc", text="Description")
        self.st_tree.column("#0", width=200, minwidth=120)
        self.st_tree.column("type", width=150, minwidth=90)
        self.st_tree.column("size", width=55, minwidth=45, anchor="e", stretch=False)
        self.st_tree.column("desc", width=160, minwidth=80)
        self.st_tree.pack(fill="both", expand=True)
        self.st_tree.bind("<Double-1>", lambda _e: self.edit_struct_node())
        sb = ttk.Frame(sf)
        sb.pack(fill="x", pady=4)
        ttk.Button(sb, text="Add struct", command=self.add_struct).pack(side="left", padx=(0, 4))
        ttk.Button(sb, text="Add element", command=self.add_member).pack(side="left", padx=(0, 4))
        ttk.Button(sb, text="Edit", command=self.edit_struct_node).pack(side="left", padx=(0, 4))
        ttk.Button(sb, text="Delete", command=self.del_struct_node).pack(side="left")

        # Arrays and Enumerations share the right hand column: three side by
        # side panes do not fit 1240px and the last one was cut off.
        right = ttk.PanedWindow(pane, orient="vertical")
        pane.add(right, weight=4)

        af = ttk.Frame(right)
        right.add(af, weight=1)
        ttk.Label(af, text="Arrays", style="Caption.TLabel").pack(anchor="w", pady=(0, 4))
        self.ar_tree = ttk.Treeview(af, columns=("name", "type", "size", "bytes", "elem", "desc"),
                                    show="headings", selectmode="browse")
        for c, t, w, mw, a in (("name", "Array", 140, 90, "w"),
                               ("type", "Element type", 110, 80, "w"),
                               ("size", "Size", 48, 40, "e"), ("bytes", "Bytes", 52, 45, "e"),
                               ("elem", "Sub element", 100, 70, "w"),
                               ("desc", "Description", 110, 60, "w")):
            self.ar_tree.heading(c, text=t)
            self.ar_tree.column(c, width=w, minwidth=mw, anchor=a,
                                stretch=c in ("name", "type", "desc"))
        self.ar_tree.pack(fill="both", expand=True)
        self.ar_tree.bind("<Double-1>", lambda _e: self.edit_array())
        ab = ttk.Frame(af)
        ab.pack(fill="x", pady=4)
        ttk.Button(ab, text="Add array", command=self.add_array).pack(side="left", padx=(0, 4))
        ttk.Button(ab, text="Edit", command=self.edit_array).pack(side="left", padx=(0, 4))
        ttk.Button(ab, text="Delete", command=self.del_array).pack(side="left")

        ef = ttk.Frame(right)
        right.add(ef, weight=1)
        ttk.Label(ef, text="Enumerations", style="Caption.TLabel").pack(anchor="w", pady=(0, 4))
        self.en_tree = ttk.Treeview(ef, columns=("value", "vt"), selectmode="browse")
        self.en_tree.heading("#0", text="Enum / literal")
        self.en_tree.heading("value", text="Value")
        self.en_tree.heading("vt", text="AUTOSAR <VT>")
        self.en_tree.column("#0", width=200, minwidth=120)
        self.en_tree.column("value", width=60, minwidth=50, anchor="e", stretch=False)
        self.en_tree.column("vt", width=220, minwidth=100)
        self.en_tree.pack(fill="both", expand=True)
        self.en_tree.bind("<Double-1>", lambda _e: self.edit_enum_node())
        eb = ttk.Frame(ef)
        eb.pack(fill="x", pady=4)
        ttk.Button(eb, text="Add enum", command=self.add_enum).pack(side="left", padx=(0, 4))
        ttk.Button(eb, text="Add literal", command=self.add_literal).pack(side="left", padx=(0, 4))
        ttk.Button(eb, text="Edit", command=self.edit_enum_node).pack(side="left", padx=(0, 4))
        ttk.Button(eb, text="Delete", command=self.del_enum_node).pack(side="left")

    def _tab_check(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Check")
        self.chk_tree = ttk.Treeview(tab, columns=("sev", "where", "msg"), show="headings")
        for c, t, w in (("sev", "Severity", 90), ("where", "Where", 260), ("msg", "Message", 800)):
            self.chk_tree.heading(c, text=t)
            self.chk_tree.column(c, width=w, anchor="w")
        _align_columns(self.chk_tree)
        self.chk_tree.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Button(tab, text="Re-check", style="Accent.TButton",
                   command=self.run_validate).pack(anchor="w", padx=12, pady=(0, 8))

    def _tab_preview(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="ARXML Preview")
        self.preview = tk.Text(tab, wrap="none", font=("Consolas", 9))
        ys = ttk.Scrollbar(tab, orient="vertical", command=self.preview.yview)
        xs = ttk.Scrollbar(tab, orient="horizontal", command=self.preview.xview)
        self.preview.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.preview.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        bar = ttk.Frame(tab)
        bar.grid(row=2, column=0, sticky="w", padx=8, pady=6)
        ttk.Button(bar, text="Refresh preview", style="Accent.TButton",
                   command=self.refresh_preview).pack(side="left")

    # ------------------------------------------------------------------
    # selection helpers
    # ------------------------------------------------------------------
    def current_service(self) -> Optional[Service]:
        sel = self.svc_list.curselection()
        if not sel or sel[0] >= len(self.prj.services):
            return self.prj.services[0] if self.prj.services else None
        return self.prj.services[sel[0]]

    def _sel(self, tree: ttk.Treeview) -> Optional[str]:
        s = tree.selection()
        return s[0] if s else None

    def _locate(self, iid: str) -> Tuple[Optional[Service], Optional[int]]:
        """Rows are tagged '<service index>:<item index>'."""
        try:
            si, ii = iid.split(":")
            return self.prj.services[int(si)], int(ii)
        except (ValueError, IndexError):
            return None, None

    # ------------------------------------------------------------------
    # refresh
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self._update_counts()
        self.project_form.load(self.prj)
        keep = self.svc_list.curselection()
        self.svc_list.delete(0, "end")
        for s in self.prj.services:
            self.svc_list.insert("end", "%s (%s)" % (s.tag or "?", s.role[:4]))
        if self.prj.services:
            self.svc_list.selection_set(keep[0] if keep and keep[0] < len(self.prj.services) else 0)
        self._show_service()
        self._fill_events()
        self._fill_groups()
        self._fill_types()
        self.file_label.config(text=self.path or "(no file)")
        self._set_title()

    def _show_service(self) -> None:
        self.service_form.load(self.current_service())
        self._fill_types()

    def _fill_events(self) -> None:
        self.ev_tree.delete(*self.ev_tree.get_children())
        for si, s in enumerate(self.prj.services):
            for ii, e in enumerate(s.events):
                hid = (parse_int(s.interface_id) << 16) | parse_int(e.event_id)
                self.ev_tree.insert("", "end", iid="%d:%d" % (si, ii),
                                    tags=(_row_tag(self.ev_tree),), values=(
                    s.tag, e.index, e.name, e.event_id, e.payload_length, e.pdu_length(),
                    "0x%08X" % hid, e.event_group, e.serializer, e.transport))

    def _fill_groups(self) -> None:
        self.grp_tree.delete(*self.grp_tree.get_children())
        for si, s in enumerate(self.prj.services):
            for ii, g in enumerate(s.event_groups):
                self.grp_tree.insert("", "end", iid="%d:%d" % (si, ii),
                                     tags=(_row_tag(self.grp_tree),), values=(
                    s.tag, g.index, g.name, g.group_id, g.dest_zone, g.dest_ipv4,
                    g.dest_mac, g.dest_udp_port, g.transport, g.routing_mode))

    def _fill_types(self) -> None:
        self.st_tree.delete(*self.st_tree.get_children())
        self.en_tree.delete(*self.en_tree.get_children())
        self.ar_tree.delete(*self.ar_tree.get_children())
        s = self.current_service()
        if s is None:
            return
        si = self.prj.services.index(s)
        for ii, st in enumerate(s.structs):
            node = self.st_tree.insert("", "end", iid="%d:%d" % (si, ii), text=st.name,
                                       open=True, values=("STRUCTURE", s.struct_size(st.name),
                                                          st.description))
            for mi, m in enumerate(st.members):
                self.st_tree.insert(node, "end", iid="%d:%d:%d" % (si, ii, mi), text=m.name,
                                    values=(m.type, s.struct_size(m.type), m.description))
        for ii, ar in enumerate(s.arrays):
            self.ar_tree.insert("", "end", iid="%d:%d" % (si, ii),
                                tags=(_row_tag(self.ar_tree),),
                                values=(ar.name, ar.element_type, ar.size,
                                        s.struct_size(ar.name), ar.element, ar.description))
        for ii, en in enumerate(s.enums):
            node = self.en_tree.insert("", "end", iid="%d:%d" % (si, ii), text=en.name,
                                       open=False, values=(en.base_type, en.description))
            for li, lit in enumerate(en.literals):
                self.en_tree.insert(node, "end", iid="%d:%d:%d" % (si, ii, li), text=lit.name,
                                    values=("0x%X" % lit.value, lit.vt))

    def refresh_preview(self) -> None:
        self._commit_forms()
        self.preview.delete("1.0", "end")
        try:
            text = arxml_gen.generate(self.prj, self.prj.template)
            self.preview.insert("1.0", text)
            coloured = theme.highlight_xml(self.preview, self.pal, text)
            self.status.set("Preview refreshed."
                            if coloured else "Preview refreshed (too large to colour).")
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.preview.insert("1.0", "Generation failed:\n\n" + traceback.format_exc())
            self.status.set("Preview failed: %s" % exc)

    # ------------------------------------------------------------------
    # file actions
    # ------------------------------------------------------------------
    def import_excel(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select the customer SOME/IP workbook(s)",
            filetypes=[("Excel workbook", "*.xlsx"), ("All files", "*.*")])
        if not paths:
            return
        log = []
        try:
            import excel_io
            # the project currently loaded acts as the base: the workbooks win
            # for everything they define, the base fills the rest (see resolve.py)
            self.prj = excel_io.import_project(list(paths), self.prj, log=log)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Import failed", traceback.format_exc())
            self.status.set("Import failed: %s" % exc)
            return
        self.refresh()
        self.run_validate()
        self.status.set("Imported %d workbook(s): %s" % (
            len(paths), ", ".join(os.path.basename(p) for p in paths)))
        if log:
            self._show_log("Import adjustments", log)

    def _show_log(self, title: str, lines: List[str]) -> None:
        """Report what the import rules changed - nothing happens silently."""
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("900x420")
        ttk.Label(win, text="%d adjustment(s). The workbook could not express these, "
                            "so they were taken from the project that was already open "
                            "or repaired by the nearest-match rule." % len(lines),
                  wraplength=860, justify="left").pack(anchor="w", padx=10, pady=(10, 4))
        text = tk.Text(win, wrap="word", font=("Consolas", 9))
        bar = ttk.Scrollbar(win, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=bar.set)
        text.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        bar.pack(side="right", fill="y", pady=(0, 10), padx=(0, 10))
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")

    def open_file(self, path: str) -> None:
        if path.lower().endswith(".json"):
            self.prj = Project.from_json(path)
        else:
            self.prj = arxml_io.read(path)
        self.path = path
        # show it: leaving the window on the previous project is a trap for
        # anything that calls this outside __init__
        self.refresh()

    def open_arxml(self) -> None:
        path = filedialog.askopenfilename(title="Open ARXML",
                                          filetypes=[("ARXML", "*.arxml"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.prj = arxml_io.read(path)
        except Exception:  # noqa: BLE001
            messagebox.showerror("Open failed", traceback.format_exc())
            return
        self.path = path
        self.refresh()
        self.run_validate()
        self.status.set("Loaded %s" % os.path.basename(path))

    def open_json(self) -> None:
        path = filedialog.askopenfilename(title="Open project JSON",
                                          filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.prj = Project.from_json(path)
        except Exception:  # noqa: BLE001
            messagebox.showerror("Open failed", traceback.format_exc())
            return
        self.path = path
        self.refresh()
        self.status.set("Loaded %s" % os.path.basename(path))

    def save_json(self, ask: bool = False) -> None:
        if not self._commit_forms() or not self._licensed_for("save the project JSON"):
            return
        path = self.path if (self.path and self.path.lower().endswith(".json") and not ask) else None
        if not path:
            path = filedialog.asksaveasfilename(
                title="Save project", defaultextension=".json",
                initialfile=self.prj.name + ".someip.json",
                filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            self.prj.to_json(path)
        except licensing.LicenseError as exc:
            messagebox.showwarning("Licence required", str(exc))
            self.refresh_license()
            return
        self.path = path
        self.refresh()
        self.status.set("Saved %s" % path)

    def generate_arxml(self) -> None:
        if not self._commit_forms() or not self._licensed_for("generate ARXML"):
            return
        issues = validator.validate(self.prj)
        errors = [i for i in issues if i[0] == validator.ERROR]
        if errors:
            self.run_validate()
            if not messagebox.askyesno(
                    "Validation errors",
                    "%d error(s) found - see the Check tab.\n\nGenerate anyway?"
                    % len(errors)):
                return
        path = filedialog.asksaveasfilename(
            title="Generate ARXML", defaultextension=".arxml",
            initialfile=self.prj.name + ".arxml", filetypes=[("ARXML", "*.arxml")])
        if not path:
            return
        try:
            arxml_gen.write(self.prj, path, self.prj.template)
        except licensing.LicenseError as exc:
            messagebox.showwarning("Licence required", str(exc))
            self.refresh_license()
            return
        except Exception:  # noqa: BLE001
            messagebox.showerror("Generation failed", traceback.format_exc())
            return
        self.refresh_preview()
        self.status.set("Generated %s" % path)
        messagebox.showinfo("Done", "ARXML written to:\n%s" % path)

    def run_validate(self) -> None:
        self._commit_forms()
        self.chk_tree.delete(*self.chk_tree.get_children())
        issues = validator.validate(self.prj)
        for sev, where, msg in issues:
            self.chk_tree.insert("", "end", values=(sev, where, msg),
                                 tags=(sev, _row_tag(self.chk_tree)))
        self.status.set("Validation: " + validator.summary(issues))
        self.nb.select(5)

    # ------------------------------------------------------------------
    # service / event / group editing
    # ------------------------------------------------------------------
    def add_service(self) -> None:
        s = Service(role="provider", tag="NEW", instance_name="NEWService",
                    interface_name="NEWServiceInterface")
        if FormDialog(self, "New service", SERVICE_SPEC, s).result:
            self.prj.services.append(s)
            self.refresh()

    def del_service(self) -> None:
        s = self.current_service()
        if s is None or not messagebox.askyesno("Delete", "Delete service '%s'?" % s.tag):
            return
        self.prj.services.remove(s)
        self.refresh()

    def add_event(self) -> None:
        s = self.current_service()
        if s is None:
            return
        e = Event(index=len(s.events) + 1,
                  event_group=s.event_groups[0].name if s.event_groups else "")
        if FormDialog(self, "New event (%s)" % s.tag, EVENT_SPEC, e).result:
            s.events.append(e)
            self.refresh()

    def edit_event(self) -> None:
        s, i = self._locate(self._sel(self.ev_tree) or "")
        if s is None:
            return
        if FormDialog(self, "Edit event", EVENT_SPEC, s.events[i]).result:
            self.refresh()

    def del_event(self) -> None:
        s, i = self._locate(self._sel(self.ev_tree) or "")
        if s is None or not messagebox.askyesno("Delete", "Delete event '%s'?" % s.events[i].name):
            return
        del s.events[i]
        self.refresh()

    def add_group(self) -> None:
        s = self.current_service()
        if s is None:
            return
        g = EventGroup(index=len(s.event_groups) + 1)
        if FormDialog(self, "New event group (%s)" % s.tag, GROUP_SPEC, g).result:
            s.event_groups.append(g)
            self.refresh()

    def edit_group(self) -> None:
        s, i = self._locate(self._sel(self.grp_tree) or "")
        if s is None:
            return
        if FormDialog(self, "Edit event group", GROUP_SPEC, s.event_groups[i]).result:
            self.refresh()

    def del_group(self) -> None:
        s, i = self._locate(self._sel(self.grp_tree) or "")
        if s is None or not messagebox.askyesno("Delete", "Delete group '%s'?"
                                                % s.event_groups[i].name):
            return
        del s.event_groups[i]
        self.refresh()

    # ------------------------------------------------------------------
    # data type editing
    # ------------------------------------------------------------------
    def add_struct(self) -> None:
        s = self.current_service()
        if s is None:
            return
        st = StructType(name="NewStruct")
        if FormDialog(self, "New struct", STRUCT_SPEC, st).result:
            s.structs.append(st)
            self.refresh()

    def add_member(self) -> None:
        iid = self._sel(self.st_tree)
        if not iid:
            messagebox.showinfo("Add element", "Select the struct to add the element to.")
            return
        parts = iid.split(":")
        s = self.prj.services[int(parts[0])]
        st = s.structs[int(parts[1])]
        m = StructMember(type="uint8_t")
        if FormDialog(self, "New element of %s" % st.name, MEMBER_SPEC, m).result:
            st.members.append(m)
            self.refresh()

    def edit_struct_node(self) -> None:
        iid = self._sel(self.st_tree)
        if not iid:
            return
        parts = iid.split(":")
        s = self.prj.services[int(parts[0])]
        st = s.structs[int(parts[1])]
        if len(parts) == 2:
            ok = FormDialog(self, "Edit struct", STRUCT_SPEC, st).result
        else:
            ok = FormDialog(self, "Edit element", MEMBER_SPEC, st.members[int(parts[2])]).result
        if ok:
            self.refresh()

    def del_struct_node(self) -> None:
        iid = self._sel(self.st_tree)
        if not iid:
            return
        parts = iid.split(":")
        s = self.prj.services[int(parts[0])]
        if len(parts) == 2:
            if messagebox.askyesno("Delete", "Delete struct '%s'?" % s.structs[int(parts[1])].name):
                del s.structs[int(parts[1])]
        else:
            st = s.structs[int(parts[1])]
            if messagebox.askyesno("Delete", "Delete element '%s'?" % st.members[int(parts[2])].name):
                del st.members[int(parts[2])]
        self.refresh()

    def add_array(self) -> None:
        s = self.current_service()
        if s is None:
            return
        ar = ArrayType(name=default_array_name("uint8_t", 16), element_type="uint8_t", size=16)
        if FormDialog(self, "New array", ARRAY_SPEC, ar).result:
            self._normalise_array(ar)
            s.arrays.append(ar)
            self.refresh()

    def edit_array(self) -> None:
        iid = self._sel(self.ar_tree)
        if not iid:
            return
        parts = iid.split(":")
        ar = self.prj.services[int(parts[0])].arrays[int(parts[1])]
        if FormDialog(self, "Edit array", ARRAY_SPEC, ar).result:
            self._normalise_array(ar)
            self.refresh()

    def del_array(self) -> None:
        iid = self._sel(self.ar_tree)
        if not iid:
            return
        parts = iid.split(":")
        s = self.prj.services[int(parts[0])]
        if messagebox.askyesno("Delete", "Delete array '%s'?" % s.arrays[int(parts[1])].name):
            del s.arrays[int(parts[1])]
            self.refresh()

    @staticmethod
    def _normalise_array(ar: ArrayType) -> None:
        """Fill in what the dialog left blank and keep the size sane."""
        ar.size = max(1, ar.size)
        if not ar.name.strip():
            ar.name = default_array_name(ar.element_type, ar.size)
        ar.name = ar.name.strip()
        ar.element_name = ar.element_name.strip()

    def add_enum(self) -> None:
        s = self.current_service()
        if s is None:
            return
        en = EnumType(name="NewType", base_type="uint8_t")
        if FormDialog(self, "New enum", ENUM_SPEC, en).result:
            s.enums.append(en)
            self.refresh()

    def add_literal(self) -> None:
        iid = self._sel(self.en_tree)
        if not iid:
            messagebox.showinfo("Add literal", "Select the enum to add the literal to.")
            return
        parts = iid.split(":")
        s = self.prj.services[int(parts[0])]
        en = s.enums[int(parts[1])]
        lit = EnumLiteral(value=len(en.literals))
        if FormDialog(self, "New literal of %s" % en.name, LITERAL_SPEC, lit).result:
            if not lit.vt:
                import excel_io
                lit.vt = excel_io.default_vt(en.name, lit.name)
            en.literals.append(lit)
            self.refresh()

    def edit_enum_node(self) -> None:
        iid = self._sel(self.en_tree)
        if not iid:
            return
        parts = iid.split(":")
        s = self.prj.services[int(parts[0])]
        en = s.enums[int(parts[1])]
        if len(parts) == 2:
            ok = FormDialog(self, "Edit enum", ENUM_SPEC, en).result
        else:
            ok = FormDialog(self, "Edit literal", LITERAL_SPEC, en.literals[int(parts[2])]).result
        if ok:
            self.refresh()

    def del_enum_node(self) -> None:
        iid = self._sel(self.en_tree)
        if not iid:
            return
        parts = iid.split(":")
        s = self.prj.services[int(parts[0])]
        if len(parts) == 2:
            if messagebox.askyesno("Delete", "Delete enum '%s'?" % s.enums[int(parts[1])].name):
                del s.enums[int(parts[1])]
        else:
            en = s.enums[int(parts[1])]
            if messagebox.askyesno("Delete", "Delete literal '%s'?" % en.literals[int(parts[2])].name):
                del en.literals[int(parts[2])]
        self.refresh()


def main() -> None:
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    App(initial).mainloop()


if __name__ == "__main__":
    main()

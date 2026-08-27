"""Tkinter front end for the SOME/IP configuration database.

    python gui.py [file.arxml | file.someip.json]

Import the customer workbooks, review every configuration item, fix what the
workbook got wrong, and regenerate the DaVinci Classic ARXML.
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import arxml_gen
import arxml_io
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
            if label.startswith("--"):
                ttk.Label(self, text=label[2:], font=("Segoe UI", 9, "bold")).grid(
                    row=row, column=col * 2, columnspan=2, sticky="w", pady=(10, 2), padx=4)
                continue
            ttk.Label(self, text=label).grid(row=row, column=col * 2, sticky="w", padx=(8, 4), pady=2)
            var = tk.StringVar()
            self.vars[path] = var
            if kind == "choice":
                w = ttk.Combobox(self, textvariable=var, values=list(opts or []), width=30)
            else:
                w = ttk.Entry(self, textvariable=var, width=32,
                              state="readonly" if kind == "ro" else "normal")
            w.grid(row=row, column=col * 2 + 1, sticky="ew", padx=(0, 12), pady=2)
            self.widgets[path] = w
        for c in range(columns):
            self.columnconfigure(c * 2 + 1, weight=1)

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

        self.canvas = tk.Canvas(body, highlightthickness=0, borderwidth=0)
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

        self._build_menu()
        self._build_toolbar()

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self._tab_project()
        self._tab_services()
        self._tab_events()
        self._tab_groups()
        self._tab_types()
        self._tab_check()
        self._tab_preview()

        self.status = tk.StringVar(value="Ready. Use File > Import Excel to start.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(
            fill="x", side="bottom")

        if initial:
            self.open_file(initial)
        self.refresh()

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

        e = tk.Menu(menu, tearoff=0)
        e.add_command(label="Add service", command=self.add_service)
        e.add_command(label="Delete service", command=self.del_service)
        menu.add_cascade(label="Edit", menu=e)

        h = tk.Menu(menu, tearoff=0)
        h.add_command(label="About", command=lambda: messagebox.showinfo(
            "About", APP_TITLE + "\n\nExcel -> model -> ARXML for DaVinci Classic.\n"
            "See MAPPING.md for the full field mapping."))
        menu.add_cascade(label="Help", menu=h)
        self.config(menu=menu)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=6, pady=6)
        for text, cmd in (("Import Excel", self.import_excel),
                          ("Open ARXML", self.open_arxml),
                          ("Save JSON", self.save_json),
                          ("Validate", self.run_validate),
                          ("Generate ARXML", self.generate_arxml)):
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 6))
        self.file_label = ttk.Label(bar, text="(no file)", foreground="#555")
        self.file_label.pack(side="right")

    # ------------------------------------------------------------------
    # tabs
    # ------------------------------------------------------------------
    def _tab_project(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Project")
        self.project_form = Form(tab, PROJECT_SPEC, columns=2)
        self.project_form.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Button(tab, text="Apply", command=self._apply_project).pack(anchor="w", padx=12, pady=8)

    def _apply_project(self) -> None:
        try:
            self.project_form.apply()
        except ValueError as exc:
            messagebox.showerror("Invalid value", str(exc))
            return
        self.refresh()
        self.status.set("Project settings applied.")

    def _tab_services(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="Services")
        left = ttk.Frame(tab)
        left.pack(side="left", fill="y", padx=(8, 0), pady=8)
        ttk.Label(left, text="Services").pack(anchor="w")
        self.svc_list = tk.Listbox(left, width=22, exportselection=False)
        self.svc_list.pack(fill="y", expand=True)
        self.svc_list.bind("<<ListboxSelect>>", lambda _e: self._show_service())
        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Add", width=7, command=self.add_service).pack(side="left")
        ttk.Button(btns, text="Delete", width=8, command=self.del_service).pack(side="left")

        right = ttk.Frame(tab)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        canvas = tk.Canvas(right, highlightthickness=0)
        scroll = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        holder = ttk.Frame(canvas)
        holder.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=holder, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.service_form = Form(holder, SERVICE_SPEC, columns=2)
        self.service_form.pack(fill="both", expand=True)
        ttk.Button(holder, text="Apply", command=self._apply_service).pack(anchor="w", pady=8)

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
        ttk.Label(sf, text="Structures").pack(anchor="w")
        self.st_tree = ttk.Treeview(sf, columns=("type", "size", "desc"), selectmode="browse")
        self.st_tree.heading("#0", text="Struct / element")
        self.st_tree.heading("type", text="Type")
        self.st_tree.heading("size", text="Bytes")
        self.st_tree.heading("desc", text="Description")
        self.st_tree.column("#0", width=230)
        self.st_tree.column("type", width=180)
        self.st_tree.column("size", width=55, anchor="e")
        self.st_tree.column("desc", width=320)
        self.st_tree.pack(fill="both", expand=True)
        self.st_tree.bind("<Double-1>", lambda _e: self.edit_struct_node())
        sb = ttk.Frame(sf)
        sb.pack(fill="x", pady=4)
        ttk.Button(sb, text="Add struct", command=self.add_struct).pack(side="left", padx=(0, 4))
        ttk.Button(sb, text="Add element", command=self.add_member).pack(side="left", padx=(0, 4))
        ttk.Button(sb, text="Edit", command=self.edit_struct_node).pack(side="left", padx=(0, 4))
        ttk.Button(sb, text="Delete", command=self.del_struct_node).pack(side="left")

        af = ttk.Frame(pane)
        pane.add(af, weight=2)
        ttk.Label(af, text="Arrays").pack(anchor="w")
        self.ar_tree = ttk.Treeview(af, columns=("name", "type", "size", "bytes", "elem", "desc"),
                                    show="headings", selectmode="browse")
        for c, t, w, a in (("name", "Array", 150, "w"), ("type", "Element type", 120, "w"),
                           ("size", "Size", 50, "e"), ("bytes", "Bytes", 55, "e"),
                           ("elem", "Sub element", 110, "w"), ("desc", "Description", 180, "w")):
            self.ar_tree.heading(c, text=t)
            self.ar_tree.column(c, width=w, anchor=a)
        self.ar_tree.pack(fill="both", expand=True)
        self.ar_tree.bind("<Double-1>", lambda _e: self.edit_array())
        ab = ttk.Frame(af)
        ab.pack(fill="x", pady=4)
        ttk.Button(ab, text="Add array", command=self.add_array).pack(side="left", padx=(0, 4))
        ttk.Button(ab, text="Edit", command=self.edit_array).pack(side="left", padx=(0, 4))
        ttk.Button(ab, text="Delete", command=self.del_array).pack(side="left")

        ef = ttk.Frame(pane)
        pane.add(ef, weight=2)
        ttk.Label(ef, text="Enumerations").pack(anchor="w")
        self.en_tree = ttk.Treeview(ef, columns=("value", "vt"), selectmode="browse")
        self.en_tree.heading("#0", text="Enum / literal")
        self.en_tree.heading("value", text="Value")
        self.en_tree.heading("vt", text="AUTOSAR <VT>")
        self.en_tree.column("#0", width=220)
        self.en_tree.column("value", width=60, anchor="e")
        self.en_tree.column("vt", width=280)
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
        self.chk_tree.tag_configure("ERROR", foreground="#b00020")
        self.chk_tree.tag_configure("WARNING", foreground="#8a6d00")
        self.chk_tree.tag_configure("INFO", foreground="#3a3a3a")
        self.chk_tree.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Button(tab, text="Re-check", command=self.run_validate).pack(anchor="w", padx=12, pady=(0, 8))

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
        ttk.Button(bar, text="Refresh preview", command=self.refresh_preview).pack(side="left")

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
        self.title("%s - %s" % (APP_TITLE, os.path.basename(self.path) if self.path else "untitled"))

    def _show_service(self) -> None:
        self.service_form.load(self.current_service())
        self._fill_types()

    def _fill_events(self) -> None:
        self.ev_tree.delete(*self.ev_tree.get_children())
        for si, s in enumerate(self.prj.services):
            for ii, e in enumerate(s.events):
                hid = (parse_int(s.interface_id) << 16) | parse_int(e.event_id)
                self.ev_tree.insert("", "end", iid="%d:%d" % (si, ii), values=(
                    s.tag, e.index, e.name, e.event_id, e.payload_length, e.pdu_length(),
                    "0x%08X" % hid, e.event_group, e.serializer, e.transport))

    def _fill_groups(self) -> None:
        self.grp_tree.delete(*self.grp_tree.get_children())
        for si, s in enumerate(self.prj.services):
            for ii, g in enumerate(s.event_groups):
                self.grp_tree.insert("", "end", iid="%d:%d" % (si, ii), values=(
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
                                values=(ar.name, ar.element_type, ar.size,
                                        s.struct_size(ar.name), ar.element, ar.description))
        for ii, en in enumerate(s.enums):
            node = self.en_tree.insert("", "end", iid="%d:%d" % (si, ii), text=en.name,
                                       open=False, values=(en.base_type, en.description))
            for li, lit in enumerate(en.literals):
                self.en_tree.insert(node, "end", iid="%d:%d:%d" % (si, ii, li), text=lit.name,
                                    values=("0x%X" % lit.value, lit.vt))

    def refresh_preview(self) -> None:
        self.preview.delete("1.0", "end")
        try:
            self.preview.insert("1.0", arxml_gen.generate(self.prj, self.prj.template))
            self.status.set("Preview refreshed.")
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
        path = self.path if (self.path and self.path.lower().endswith(".json") and not ask) else None
        if not path:
            path = filedialog.asksaveasfilename(
                title="Save project", defaultextension=".json",
                initialfile=self.prj.name + ".someip.json",
                filetypes=[("JSON", "*.json")])
        if not path:
            return
        self.prj.to_json(path)
        self.path = path
        self.refresh()
        self.status.set("Saved %s" % path)

    def generate_arxml(self) -> None:
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
        except Exception:  # noqa: BLE001
            messagebox.showerror("Generation failed", traceback.format_exc())
            return
        self.refresh_preview()
        self.status.set("Generated %s" % path)
        messagebox.showinfo("Done", "ARXML written to:\n%s" % path)

    def run_validate(self) -> None:
        self.chk_tree.delete(*self.chk_tree.get_children())
        issues = validator.validate(self.prj)
        for sev, where, msg in issues:
            self.chk_tree.insert("", "end", values=(sev, where, msg), tags=(sev,))
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

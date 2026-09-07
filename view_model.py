"""Flatten the model into the context the ARXML template renders.

Everything derived - short names, absolute paths, header ids, PDU lengths,
socket pairings, the inlined struct tree - is computed here, so the template
stays a plain description of the XML and contains no logic beyond `t-foreach`
and `t-if`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from naming import Endpoint, Names, SocketPlan, uuid_for
from someip_model import (
    BASE_TYPES, SD_HEADER_ID, EnumType, Event, EventGroup, Project, Service,
    StructMember, StructType, base_type_name, base_type_size_bits,
    default_array_element_name, default_array_name, parse_int,
)

BASE_TYPE_BY_AR_NAME: Dict[str, tuple] = {}
for _k, _v in BASE_TYPES.items():
    BASE_TYPE_BY_AR_NAME.setdefault(_v[0], _v)


def build(prj: Project) -> Dict[str, Any]:
    n = Names(prj)
    plan = SocketPlan(prj, n)
    ctx = Builder(prj, n, plan).build()
    return ctx


def build_swc(prj: Project) -> Dict[str, Any]:
    """Context for the SWC file, which is generated separately.

    It reuses the same Builder, so the port interface paths and the data type
    tree it references are by construction the ones the SOME/IP file declares -
    the SWC is only useful next to that file, and a name computed a second way
    would eventually drift from it.
    """
    n = Names(prj)
    return Builder(prj, n, SocketPlan(prj, n)).build_swc()


def build_gateway_swc(prj: Project) -> Dict[str, Any]:
    """Context for the gateway SWC, generated beside the other one."""
    n = Names(prj)
    return Builder(prj, n, SocketPlan(prj, n)).build_gateway_swc()


def layout_problems(prj: Project) -> List[tuple]:
    """[(struct name, emitted bytes, model bytes)] where the two disagree.

    The struct that reaches the ARXML is not the list of rows in the workbook -
    bit fields are packed into wider members - so its size is computed twice by
    two different pieces of code.  They have drifted apart before (a 14 bit
    signal spanning two bytes used to cost one byte too many), and the symptom
    was a data type quietly out of step with the DLC.  Checking it here means
    validate.py can say so before anything is generated.
    """
    n = Names(prj)
    b = Builder(prj, n, SocketPlan(prj, n))
    by_path = {t["path"]: t for t in b._impl_types()}
    out: List[tuple] = []
    for t in by_path.values():
        if t["category"] != "STRUCTURE":
            continue
        svc = next((s for s in prj.services if s.find_struct(t["name"])), None)
        if svc is None:
            continue
        emitted = _node_bytes(t, by_path)
        wanted = svc.struct_size(t["name"])
        if emitted != wanted:
            out.append((t["name"], emitted, wanted))
    return out


def _unique(items) -> List[Any]:
    """First-seen order, duplicates dropped."""
    out, seen = [], set()
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _strip_suffix(name: str, suffix: str) -> str:
    return name[:-len(suffix)] if name.endswith(suffix) and len(name) > len(suffix) else name


def _node_bytes(node: Dict[str, Any], by_path: Dict[str, Any], depth: int = 0) -> int:
    """How many bytes one emitted type occupies."""
    if depth > 16:
        return 0
    cat = node.get("category")
    if cat == "STRUCTURE":
        return sum(_node_bytes(c, by_path, depth + 1) for c in node.get("children") or [])
    if cat == "ARRAY":
        kids = node.get("children") or []
        if not kids:
            return 0
        return (max(1, int(kids[0].get("array_size") or 1))
                * _node_bytes(kids[0], by_path, depth + 1))
    if cat == "TYPE_REFERENCE":
        target = by_path.get(node.get("impl_ref") or "")
        if target is not None:
            return _node_bytes(target, by_path, depth + 1)
        leaf = (node.get("impl_ref") or "").rsplit("/", 1)[-1]
        return BASE_TYPE_BY_AR_NAME.get(leaf, ("", 8, "", ""))[1] // 8
    leaf = (node.get("base_ref") or "").rsplit("/", 1)[-1]
    return BASE_TYPE_BY_AR_NAME.get(leaf, ("", 8, "", ""))[1] // 8


class Builder:
    def __init__(self, prj: Project, n: Names, plan: SocketPlan):
        self.prj, self.n, self.plan = prj, n, plan
        self.fibex: List[Dict[str, str]] = []
        # populated by _struct_children() while _impl_types() walks the
        # structs, consumed by _compu_methods()/_data_constrs() right after -
        # see the note there for why a byte-wide BITFIELD_TEXTTABLE compu
        # method belongs there and not on the member itself.
        self._bitfield_compus: List[Dict[str, Any]] = []
        self._bitfield_constrs: List[Dict[str, Any]] = []
        # every <SYMBOL> already handed out: it becomes a global C identifier,
        # so a name may not be reused even across compu methods
        self._bitfield_symbols: set = set()
        # enums some emitted member really points at.  A bit field enum is
        # folded into its byte's BITFIELD_TEXTTABLE instead, and emitting its
        # own TEXTTABLE too would put an enumeration in the workspace that
        # nothing uses.
        self._used_enums: set = set()
        # base types a synthesized packed member needs.  A run of four 4 bit
        # fields is one uint16 even though no member of the model is one, so
        # the BASE-TYPE-REF would otherwise dangle.
        self._bitfield_base_types: set = set()
        # array_u8_<n> types a packed run needs; spliced into the output just
        # before the struct that refers to them, the way model arrays are
        self._synth_arrays: List[Dict[str, Any]] = []
        self._synth_array_names: set = set()

    # ------------------------------------------------------------------
    def build(self) -> Dict[str, Any]:
        events = self._events()
        sd = self._service_discovery()
        routing_groups = self._routing_groups()
        sockets = self._sockets()
        bundles = self._bundles(events)

        ctx: Dict[str, Any] = {
            "project": self.prj,
            "names": self.n,
            "plan": self.plan,
            "uuid": uuid_for,
            "interface_version": self.prj.services[0].major_version if self.prj.services else 1,
            "transformer_set": self.n.transformer_set,
            "transformation": self.n.transformer_set + "/SomeIpDefaultTransformation",
            "transformer": self.n.transformer_set + "/SomeIpDefaultTransformer",
            "events": events,
            "sd": sd,
            "routing_groups": routing_groups,
            "port_interfaces": self._port_interfaces(events),
            "impl_types": self._impl_types(),
            "base_types": self._base_types(),
            "compu_methods": self._compu_methods(),
            "data_constrs": self._data_constrs(),
            "endpoints": self._endpoints(),
            "sockets": sockets,
            "bundles": bundles,
            "pdu_triggerings": self._pdu_triggerings(events, sd),
            "ecu": self._ecu(events, sd),
        }
        # the FIBEX list references elements produced above, so it comes last
        ctx["fibex"] = self._fibex(events, sd, routing_groups)
        return ctx

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    def _events(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for s in self.prj.services:
            for e in s.events:
                direction = "OUT" if s.is_provider else "IN"
                out.append({
                    "service": s,
                    "event": e,
                    "name": e.name,
                    "tag": s.tag,
                    "direction": direction,
                    "length": e.pdu_length(),
                    "payload_length": e.payload_length,
                    "header_id": (parse_int(s.interface_id) << 16) | parse_int(e.event_id),
                    "interface_version": s.major_version,
                    "sig": self.n.sig(e), "sig_path": self.n.sig_path(e),
                    "sys": self.n.sys(e), "sys_path": self.n.sys_path(e),
                    "pdu": self.n.pdu(e), "pdu_path": self.n.pdu_path(e),
                    "map": self.n.sig_map(e),
                    "st": self.n.st(e), "st_path": self.n.st_path(e),
                    "pt": self.n.pt(e), "pt_path": self.n.pt_path(e),
                    "pp": self.n.pp(e), "pp_path": self.n.pp_path(e),
                    "sp": self.n.sp(e), "sp_path": self.n.sp_path(e),
                    "port_interface": self.n.port_interface(s, e),
                    "port_interface_path": self.n.port_interface_path(s, e),
                    "type_ref": self.n.impl_type_path(e.serializer),
                    "routing_group_ref": self._routing_group_for(s, e.event_group)["path"],
                })
        return out

    # ------------------------------------------------------------------
    # service discovery
    # ------------------------------------------------------------------
    def _service_discovery(self) -> Dict[str, Any]:
        n = self.n
        port = self.prj.services[0].sd_udp_port if self.prj.services else 30490
        pdus = [
            {"name": n.sd_mc(), "path": n.pdu_pkg(n.sd_mc()),
             "triggering": "PT_SD_Ctrl_Rx_Multicast", "port": n.sd_mc() + "_CN", "direction": "IN"},
            {"name": n.sd_rx(), "path": n.pdu_pkg(n.sd_rx()),
             "triggering": "PT_SD_Ctrl_%s_Rx" % n.local, "port": n.sd_rx() + "_CN", "direction": "IN"},
            {"name": n.sd_tx(), "path": n.pdu_pkg(n.sd_tx()),
             "triggering": "PT_SD_Ctrl_%s_Tx" % n.local, "port": n.sd_tx() + "_CN", "direction": "OUT"},
        ]
        for p in pdus:
            p["triggering_path"] = "%s/%s" % (n.chan, p["triggering"])
            p["port_path"] = "%s/%s" % (n.connector, p["port"])
        return {"port": port, "header_id": SD_HEADER_ID, "pdus": pdus, "length": 1500}

    def _routing_group_for(self, s: Service, group_name: str) -> Dict[str, str]:
        """The SO-AD-ROUTING-GROUP that carries one event group of one service."""
        short = self.n.routing_group(s, group_name)
        return {
            "name": short,
            "path": self.n.routing_group_path(s, group_name),
            "control_type": ("ACTIVATION-MULTICAST"
                             if s.routing_mode.lower().startswith("staticmulticast")
                             else "ACTIVATION-UNICAST"),
        }

    def _routing_groups(self) -> List[Dict[str, str]]:
        out, seen = [], set()
        for s in self.prj.services:
            # both the declared groups and the ones events merely name, so that
            # no reference is left dangling
            names = [g.name for g in s.event_groups] + [e.event_group for e in s.events]
            for gname in names:
                rg = self._routing_group_for(s, gname)
                if rg["path"] in seen:
                    continue
                seen.add(rg["path"])
                out.append(rg)
        return out

    def _port_interfaces(self, events) -> List[Dict[str, Any]]:
        return [{
            "name": ev["port_interface"], "path": ev["port_interface_path"],
            "element": ev["name"], "type_ref": ev["type_ref"],
        } for ev in events]

    # ------------------------------------------------------------------
    # SWC (its own file)
    # ------------------------------------------------------------------
    def build_swc(self) -> Dict[str, Any]:
        prj = self.prj
        events = self._events()
        types_by_path = {t["path"]: t for t in self._impl_types()}
        name = prj.swc_name or (prj.ecu_name + "_SoIpSwc")
        package = prj.swc_package or "ComponentTypes"
        path = "/%s/%s" % (package, name)
        behavior = name + "_InternalBehavior"
        behavior_path = path + "/" + behavior
        impl_types = list(types_by_path.values())
        ports = self._swc_ports(events, types_by_path, path)
        triggers, runnables = self._swc_triggers(ports, name, path, behavior_path)
        pims = self._swc_per_instance_memory(impl_types, behavior_path)
        return {
            "project": prj,
            "uuid": uuid_for,
            "package": package,
            "package_path": "/" + package,
            "swc": {"name": name, "path": path},
            "behavior": {"name": behavior, "path": behavior_path},
            "implementation": {"name": name + "_Implementation",
                               "path": "/%s/%s_Implementation" % (package, name)},
            "trigger": {"interface": prj.gateway_trigger_interface,
                        "element_ref": "%s/%s" % (prj.gateway_trigger_interface,
                                                  prj.gateway_trigger_element)},
            "ports": ports,
            "trigger_ports": triggers,
            "runnables": runnables,
            "per_instance_memory": pims,
        }

    def _swc_per_instance_memory(self, impl_types, behavior_path: str) -> List[Dict[str, Any]]:
        """One AR-TYPED-PER-INSTANCE-MEMORY per struct the SWC serializes.

        The same thing gen_per_instance_memory.py writes as a fragment to paste
        by hand, produced here from the types the SOME/IP file really declares,
        so the SWC arrives complete.  Only STRUCTURE types get one: the byte
        arrays behind a packed member are a detail of a struct, not a buffer of
        their own.
        """
        out: List[Dict[str, Any]] = []
        for t in impl_types:
            if t.get("category") != "STRUCTURE":
                continue
            name = _strip_suffix(t["name"], "Struct")
            out.append({
                "name": name, "path": behavior_path + "/" + name,
                "type_ref": t["path"],
                "calibration": t.get("calibration") or "READ-ONLY",
            })
        return out

    def _swc_triggers(self, ports, swc_name: str, swc_path: str,
                      behavior_path: str) -> tuple:
        """The R-Ports the gateway connects to, and the runnables they start.

        One of each per CAN message, mirroring the gateway's P-Ports so the two
        components pair up.  Receiving the trigger starts a runnable that sends
        that message on every SOME/IP port carrying it - the same struct may go
        to several zones, and one trigger feeds all of them.
        """
        prj = self.prj
        triggers: List[Dict[str, Any]] = []
        runnables: List[Dict[str, Any]] = []
        for serializer in _unique(p["serializer"] for p in ports if p["provided"]):
            base = _strip_suffix(serializer, "Struct")
            rport = prj.swc_trigger_port_prefix + base
            runnable = "%s_%s%s" % (swc_name, base, prj.swc_runnable_suffix)
            runnable_path = behavior_path + "/" + runnable
            event = "DRT_%s_%s_%s" % (runnable, rport, prj.gateway_trigger_element)
            triggers.append({"name": rport, "path": swc_path + "/" + rport})
            runnables.append({
                "name": runnable, "path": runnable_path,
                "event": {"name": event, "path": behavior_path + "/" + event},
                "rport_ref": swc_path + "/" + rport,
                "sends": [{
                    "name": "SEND_%s_%s" % (p["name"], p["element"]),
                    "path": "%s/SEND_%s_%s" % (runnable_path, p["name"], p["element"]),
                    "port_ref": p["path"],
                    "target_ref": p["data_element_ref"],
                } for p in ports if p["provided"] and p["serializer"] == serializer],
            })
        return triggers, runnables

    def build_gateway_swc(self) -> Dict[str, Any]:
        """The gateway SWC: one trigger port per CAN message it forwards.

        The events that carry the same serializer are the same CAN message on
        its way to several zones, so they share one port - the port says the
        message arrived, and the SOME/IP side decides who hears about it.  All
        of them point at one trigger interface, which is not generated here:
        it holds a single primitive and belongs to the workspace, not to any
        one database.
        """
        prj = self.prj
        name = prj.gateway_swc_name
        package = prj.swc_package or "ComponentTypes"
        path = "/%s/%s" % (package, name)
        behavior = name + "_InternalBehavior"
        behavior_path = path + "/" + behavior
        runnable = prj.gateway_runnable or "Runnable"
        element_ref = "%s/%s" % (prj.gateway_trigger_interface, prj.gateway_trigger_element)

        ports: List[Dict[str, Any]] = []
        provider_serializers = _unique(
            ev["event"].serializer for ev in self._events()
            if ev["service"].is_provider)     # the gateway sends, it does not receive
        for serializer in provider_serializers:
            port = prj.gateway_port_prefix + _strip_suffix(serializer, "Struct")
            ports.append({
                "name": port, "path": path + "/" + port,
                "access": "SEND_%s_%s" % (port, prj.gateway_trigger_element),
                "access_path": "%s/%s/SEND_%s_%s" % (behavior_path, runnable, port,
                                                     prj.gateway_trigger_element),
            })
        return {
            "project": prj,
            "uuid": uuid_for,
            "package": package,
            "package_path": "/" + package,
            "swc": {"name": name, "path": path},
            "behavior": {"name": behavior, "path": behavior_path},
            "runnable": {"name": runnable, "path": behavior_path + "/" + runnable},
            "timing": {"name": "TMT_" + runnable,
                       "path": behavior_path + "/TMT_" + runnable,
                       "period": prj.gateway_period},
            "implementation": {"name": name + "_Implementation",
                               "path": "/%s/%s_Implementation" % (package, name)},
            "trigger": {"interface": prj.gateway_trigger_interface,
                        "element_ref": element_ref},
            "ports": ports,
        }

    def _swc_ports(self, events, types_by_path, swc_path) -> List[Dict[str, Any]]:
        """One port per event: the provider sends, so it gets a P-Port.

        Both directions carry an init value shaped like the data type behind
        the interface - the receiver so it has something defined to read before
        the first message arrives, the sender so the buffer the RTE hands the
        application is defined before the first write.
        """
        out: List[Dict[str, Any]] = []
        for ev in events:
            s = ev["service"]
            prefix = (self.prj.swc_port_prefix_provider if s.is_provider
                      else self.prj.swc_port_prefix_consumer)
            name = prefix + ev["name"]
            target = types_by_path.get(ev["type_ref"])
            init = (self._value_spec(target, types_by_path) if target is not None
                    else {"kind": "numerical", "label": "", "value": 0, "children": []})
            out.append({
                "name": name, "path": swc_path + "/" + name,
                "provided": s.is_provider,
                "iface_ref": ev["port_interface_path"],
                "element": ev["name"],
                "serializer": ev["event"].serializer,
                "data_element_ref": "%s/%s" % (ev["port_interface_path"], ev["name"]),
                "init": init,
            })
        return out

    def _value_spec(self, node: Dict[str, Any], types_by_path: Dict[str, Any],
                    label: Optional[str] = None, depth: int = 0) -> Dict[str, Any]:
        """An INIT-VALUE tree shaped like one IMPLEMENTATION-DATA-TYPE.

        It is built from the emitted type tree rather than from the model, so
        it matches what the SOME/IP file really declares - a struct whose bit
        fields were packed into Byte<n> members has to be initialised with one
        field per byte, not one per signal.
        """
        cat = node.get("category")
        lbl = node.get("name", "") if label is None else label
        plain = {"kind": "numerical", "label": lbl, "value": 0, "children": []}
        if depth > 16:
            return plain                                  # cyclic: stop
        if cat == "TYPE_REFERENCE":
            target = types_by_path.get(node.get("impl_ref") or "")
            if target is None:
                return plain                              # a platform type
            return self._value_spec(target, types_by_path, lbl, depth + 1)
        if cat == "STRUCTURE":
            return {"kind": "record", "label": lbl, "value": 0,
                    "children": [self._value_spec(c, types_by_path, None, depth + 1)
                                 for c in node.get("children") or []]}
        if cat == "ARRAY":
            kids = node.get("children") or []
            if not kids:
                return plain
            elem = kids[0]
            # the elements are indistinguishable, so none of them takes a label
            return {"kind": "array", "label": lbl, "value": 0,
                    "children": [self._value_spec(elem, types_by_path, "", depth + 1)
                                 for _ in range(max(1, int(elem.get("array_size") or 1)))]}
        return plain

    # ------------------------------------------------------------------
    # data types
    # ------------------------------------------------------------------
    def _impl_types(self) -> List[Dict[str, Any]]:
        """Top level IMPLEMENTATION-DATA-TYPEs, dependencies first.

        A struct is emitted once per serializer and its nested structs stay
        inlined, but an array is always a type of its own: DaVinci needs an
        IMPLEMENTATION-DATA-TYPE-REF to it, so every array reachable from a
        serializer is emitted before whatever refers to it.
        """
        out: List[Dict[str, Any]] = []
        seen: set = set()
        for s in self.prj.services:
            for e in s.events:
                if not e.serializer:
                    continue
                if s.find_array(e.serializer) is not None:
                    self._emit_array_type(s, e.serializer, out, seen, frozenset())
                else:
                    self._emit_struct_type(s, e.serializer, out, seen, frozenset())
        return out

    def _emit_struct_type(self, s: Service, name: str, out: List[Dict[str, Any]],
                          seen: set, guard: frozenset) -> None:
        st = s.find_struct(name)
        if st is None or name in seen or name in guard:
            return
        seen.add(name)
        self._emit_member_arrays(s, st, out, seen, guard | {name})
        path = self.n.impl_type_path(st.name)
        children = self._struct_children(s, st.name, st.members, path)
        # a referenced type has to exist before whatever points at it
        out.extend(self._synth_arrays)
        self._synth_arrays = []
        out.append({
            "name": st.name, "path": path, "category": "STRUCTURE",
            "calibration": "READ-ONLY", "type_emitter": "RTE",
            "children": children,
        })

    def _emit_array_type(self, s: Service, name: str, out: List[Dict[str, Any]],
                         seen: set, guard: frozenset) -> None:
        arr = s.find_array(name)
        if arr is None or name in seen or name in guard:
            return
        seen.add(name)
        inner = guard | {name}
        # the element type is referenced, never inlined, so it needs to exist
        if s.find_array(arr.element_type) is not None:
            self._emit_array_type(s, arr.element_type, out, seen, inner)
        else:
            self._emit_struct_type(s, arr.element_type, out, seen, inner)
        path = self.n.impl_type_path(arr.name)
        out.append({
            "name": arr.name, "path": path, "category": "ARRAY",
            "calibration": "READ-ONLY", "type_emitter": "RTE",
            "children": [self._array_element_node(s, arr, path)],
        })

    def _emit_member_arrays(self, s: Service, st: StructType, out: List[Dict[str, Any]],
                            seen: set, guard: frozenset) -> None:
        """Emit every array a struct reaches, through inlined nested structs too."""
        for m in st.members:
            if s.find_array(m.type) is not None:
                self._emit_array_type(s, m.type, out, seen, guard)
                continue
            nested = s.find_struct(m.type)
            if nested is not None and m.type not in guard:
                self._emit_member_arrays(s, nested, out, seen, guard | {m.type})

    def _struct_children(self, s: Service, struct_name: str,
                         members: List[StructMember], path: str,
                         seen: set = frozenset()) -> List[Dict[str, Any]]:
        """SUB-ELEMENTS for a struct (or an inlined nested struct).

        DaVinci Developer has no notion of a struct member narrower than its
        own base type: the AR4 Data Types reference never mentions a "number
        of bits" attribute on a Record Element, and the RTE always emits a
        plain `typedef`, never a C bit field, for one. The only bit-level
        construct it actually supports is a BITFIELD_TEXTTABLE compu method
        on a *whole* byte - see /Predefined_DEV/CompuMethods/
        Dem_UdsStatusByteType already used elsewhere in this project's own
        DataTypes.arxml. So a run of consecutive CAN-signal bit fields (Type
        column "uint8_t : 4" and friends) is packed here into one byte-wide
        VALUE member with one compu scale per named sub-value, instead of one
        member per signal.

        A run is closed at the first *byte boundary*, not after eight bits: a
        CAN signal may be wider than a byte and still not fill whole ones -
        UBatt is 14 bits over byte2..byte3, and the two padding bits after it
        belong to the same two byte unit.  Closing such a run early cost a byte
        and put the struct out of step with the DLC.
        """
        out: List[Dict[str, Any]] = []
        i, n = 0, len(members)
        byte_index = 0
        while i < n:
            m = members[i]
            # A member keeps its own name and type only when it fills that type
            # exactly: "uint8_t : 8" and "uint16_t : 16" do, "uint32_t : 24"
            # does not - that one is three bytes on the wire while a uint32 is
            # four, which used to make the struct longer than the frame.
            if not m.bit_size or m.bit_size == self._storage_bits(s, m):
                out.append(self._impl_node(s, m.name, m.type, path, seen))
                byte_index += max(1, m.bit_size // 8 if m.bit_size
                                  else s.struct_size(m.type))
                i += 1
                continue
            run: List[StructMember] = []
            bits = 0
            while i < n and members[i].bit_size:
                run.append(members[i])
                bits += members[i].bit_size
                i += 1
                if bits % 8 == 0:
                    break               # the run now ends on a byte boundary
            nodes = self._bitfield_group_nodes(s, struct_name, run, bits, byte_index, path)
            out.extend(nodes)
            byte_index += max(1, (bits + 7) // 8)
        return out

    @staticmethod
    def _storage_bits(s: Service, m: StructMember) -> int:
        """Width of the type a member is declared with, enums resolved."""
        en = s.find_enum(m.type)
        return base_type_size_bits(en.base_type if en is not None else m.type)

    def _bitfield_group_nodes(self, s: Service, struct_name: str,
                              run: List[StructMember], bits: int, byte_index: int,
                              path: str) -> List[Dict[str, Any]]:
        """The member one packed run becomes.

        One byte is a uint8 carrying the run's BITFIELD_TEXTTABLE.  Anything
        wider is an array of uint8, not a uint16/uint32: the transformer writes
        a multi byte integer least significant byte first
        (MOST-SIGNIFICANT-BYTE-LAST), which would put the bytes on the wire in
        the opposite order to the Motorola frame they came from.  An array of
        bytes keeps them where the frame has them - and there is no three or
        five byte integer for a 24 or 40 bit signal anyway.
        """
        nbytes = max(1, (bits + 7) // 8)
        if nbytes == 1:
            return [self._bitfield_node(s, struct_name, run, bits, byte_index, path)]
        # a run of one member keeps that member's name; a mixed run cannot
        name = (run[0].name if len(run) == 1
                else "Bytes%d_%d" % (byte_index, byte_index + nbytes - 1))
        return [self._byte_array_node(name, nbytes, byte_index, path)]

    def _byte_array_node(self, name: str, nbytes: int, byte_index: int,
                         path: str) -> Dict[str, Any]:
        """A member pointing at array_u8_<n>, which is emitted alongside.

        Arrays are named types here rather than inlined, because that is what
        DaVinci wants (see _emit_array_type), so the type is registered for the
        struct to be preceded by.
        """
        arr_name = default_array_name("uint8_t", nbytes)
        self._need_byte_array(arr_name, nbytes)
        return {
            "name": name, "path": path + "/" + name, "category": "TYPE_REFERENCE",
            "type": arr_name, "base_ref": None, "compu_ref": None, "constr_ref": None,
            "impl_ref": self.n.impl_type_path(arr_name),
            "array_size": None, "array_semantics": None, "calibration": None,
            "children": [],
        }

    def _need_byte_array(self, arr_name: str, nbytes: int) -> None:
        if arr_name in self._synth_array_names:
            return
        self._synth_array_names.add(arr_name)
        self._bitfield_base_types.add("uint8")
        path = self.n.impl_type_path(arr_name)
        elem = default_array_element_name("uint8_t")
        self._synth_arrays.append({
            "name": arr_name, "path": path, "category": "ARRAY",
            "calibration": "READ-ONLY", "type_emitter": "RTE",
            "children": [{
                "name": elem, "path": path + "/" + elem, "category": "TYPE_REFERENCE",
                "type": "uint8_t", "base_ref": None, "compu_ref": None,
                "constr_ref": None,
                "impl_ref": self.prj.platform_type_package + "/uint8",
                "array_size": nbytes, "array_semantics": "FIXED-SIZE",
                "calibration": None, "children": [],
            }],
        })

    def _bitfield_node(self, s: Service, struct_name: str, run: List[StructMember],
                       bits: int, byte_index: int, path: str) -> Dict[str, Any]:
        """One packed run: a VALUE as wide as the run, plus a synthesized compu
        method that gives each named sub-field its own masked compu scale.

        A sub-field with no enum (padding, or a raw numeric range with no named
        values) contributes its width but gets no scale - BITFIELD_TEXTTABLE
        can only name discrete values.
        """
        byte_name = "Byte%d" % byte_index
        ar_type = "uint8"
        self._bitfield_base_types.add(ar_type)
        cm_name = "%s_%s" % (struct_name, byte_name)
        scales: List[Dict[str, Any]] = []
        pos = bits                      # the run is filled MSB first
        for mm in run:
            pos -= mm.bit_size
            en = s.find_enum(mm.type)
            if en is None:
                continue
            for lit in en.literals:
                value = lit.value << pos
                label = self._bitfield_symbol(struct_name, byte_name, mm, lit)
                scales.append({
                    "label": label, "symbol": label,
                    "mask": ((1 << mm.bit_size) - 1) << pos,
                    "lower": value, "upper": value,
                })
        node: Dict[str, Any] = {
            "name": byte_name, "path": path + "/" + byte_name, "category": "VALUE",
            "type": ar_type + "_t",
            "base_ref": "%s/%s" % (self.prj.base_type_package, ar_type),
            "compu_ref": None, "constr_ref": None, "impl_ref": None,
            "array_size": None, "array_semantics": None, "calibration": "READ-ONLY",
            "children": [],
        }
        if scales:
            # the constraint is named apart from the compu method, the way the
            # enums do it (CrashOtptStsType / CrashOtptStsconst)
            dc_name = cm_name + "const"
            self._bitfield_compus.append({
                "name": cm_name, "path": self.n.compu_path(cm_name),
                "category": "BITFIELD_TEXTTABLE", "scales": scales,
            })
            self._bitfield_constrs.append({
                "name": dc_name, "path": self.n.constr_path(dc_name),
                "lower": 0, "upper": 255,
            })
            node["compu_ref"] = self.n.compu_path(cm_name)
            node["constr_ref"] = self.n.constr_path(dc_name)
            node["calibration"] = None
        return node

    def _bitfield_symbol(self, struct_name: str, byte_name: str,
                         member: StructMember, lit) -> str:
        """The C identifier one compu scale becomes.

        DaVinci refuses the same ShortLabel twice, and the workspace it refuses
        it in may hold several imported ARXMLs - so a counter that only sees
        the file being written is not enough: a provider and a consumer
        generated separately would both emit `ACU_CRASH_STS_CRASH_DETECTED` for
        their own struct.  The name is therefore derived from the struct, which
        has to be unique anyway because every struct lands in the same
        /DataTypes package.  Same input, same name, whatever else is generated
        alongside it.
        """
        base = lit.vt or lit.name
        for cand in ("%s_%s" % (struct_name, base),
                     "%s_%s_%s" % (struct_name, byte_name, base),
                     "%s_%s_%s" % (struct_name, member.name, base)):
            if cand not in self._bitfield_symbols:
                self._bitfield_symbols.add(cand)
                return cand
        n = 2
        while "%s_%s_%d" % (struct_name, base, n) in self._bitfield_symbols:
            n += 1
        cand = "%s_%s_%d" % (struct_name, base, n)
        self._bitfield_symbols.add(cand)
        return cand

    def _array_element_node(self, s: Service, arr, parent_path: str) -> Dict[str, Any]:
        """The single sub element of an array, carrying ARRAY-SIZE."""
        node = self._impl_node(s, arr.element, arr.element_type, parent_path, set())
        node["array_size"] = max(1, int(arr.size or 1))
        node["array_semantics"] = arr.size_semantics or "FIXED-SIZE"
        # an enum element keeps its compu method and constraint; anything else
        # is a plain reference to the element type
        if s.find_enum(arr.element_type) is None:
            self._as_type_reference(node, self._type_ref(s, arr.element_type))
        return node

    @staticmethod
    def _as_type_reference(node: Dict[str, Any], ref: str) -> None:
        node["category"] = "TYPE_REFERENCE"
        node["impl_ref"] = ref
        node["base_ref"] = None
        node["compu_ref"] = None
        node["constr_ref"] = None
        node["calibration"] = None
        node["children"] = []

    def _type_ref(self, s: Service, type_name: str) -> str:
        """Absolute path of the IMPLEMENTATION-DATA-TYPE `type_name` refers to."""
        bt = base_type_name(type_name)
        if bt is not None:
            return "%s/%s" % (self.prj.platform_type_package, bt)
        if s.find_array(type_name) is not None or s.find_struct(type_name) is not None:
            return self.n.impl_type_path(type_name)
        # unresolved: keep the file importable, validate.py reports it
        return self.prj.platform_type_package + "/uint8"

    def _impl_node(self, s: Service, name: str, type_name: str,
                   parent_path: str, seen: set) -> Dict[str, Any]:
        path = parent_path + "/" + name
        node: Dict[str, Any] = {
            "name": name, "path": path, "category": "VALUE", "type": type_name,
            "base_ref": None, "compu_ref": None, "constr_ref": None, "impl_ref": None,
            "array_size": None, "array_semantics": None,
            "calibration": "READ-ONLY", "children": [],
        }
        bt = base_type_name(type_name)
        en = s.find_enum(type_name)
        arr = s.find_array(type_name)
        nested = s.find_struct(type_name)

        if bt is not None:
            node["base_ref"] = "%s/%s" % (self.prj.base_type_package, bt)
        elif en is not None:
            self._used_enums.add(en.name)
            node["base_ref"] = "%s/%s" % (self.prj.base_type_package,
                                          base_type_name(en.base_type) or "uint8")
            node["compu_ref"] = self.n.compu_path(en.compu_method)
            node["constr_ref"] = self.n.constr_path(en.data_constr)
            # the compu method and the constraint already say how the value is
            # read, so a calibration access on top adds nothing; the files
            # DaVinci is happy with leave it out here
            node["calibration"] = None
        elif arr is not None:
            # arrays are named types; a member points at one instead of inlining it
            self._as_type_reference(node, self.n.impl_type_path(type_name))
        elif nested is not None and type_name not in seen:
            node["category"] = "STRUCTURE"
            node["children"] = self._struct_children(s, type_name, nested.members,
                                                      path, seen | {type_name})
        else:
            # unresolved type: fall back to the smallest base type so the file
            # stays importable; validate.py reports it as an error
            node["base_ref"] = self.prj.base_type_package + "/uint8"
        return node

    def _used_base_types(self) -> List[str]:
        used = set()
        for s in self.prj.services:
            for st in s.structs:
                for m in st.members:
                    b = base_type_name(m.type)
                    if b:
                        used.add(b)
            for en in s.enums:
                b = base_type_name(en.base_type)
                if b:
                    used.add(b)
            for ar in s.arrays:
                b = base_type_name(ar.element_type)
                if b:
                    used.add(b)
        # _impl_types() has run by now and recorded what the packed members use
        used.update(self._bitfield_base_types)
        return sorted(used)

    def _base_types(self) -> List[Dict[str, Any]]:
        out = []
        for name in self._used_base_types():
            _, bits, encoding, native = BASE_TYPE_BY_AR_NAME[name]
            out.append({"name": name, "path": "/DataTypes/BaseTypes/" + name,
                        "size": bits, "encoding": encoding, "native": native})
        return out

    def _all_enums(self) -> List[EnumType]:
        out, seen = [], set()
        for s in self.prj.services:
            for en in s.enums:
                if en.name in seen:
                    continue
                seen.add(en.name)
                out.append(en)
        return out

    def _compu_methods(self) -> List[Dict[str, Any]]:
        # _impl_types() (built earlier in build()) has already appended one
        # BITFIELD_TEXTTABLE entry per packed byte to self._bitfield_compus -
        # see _struct_children()/_bitfield_byte_node().
        out = []
        for en in self._all_enums():
            if en.name not in self._used_enums:
                continue        # folded into a byte's BITFIELD_TEXTTABLE
            out.append({
                "name": en.compu_method, "path": self.n.compu_path(en.compu_method),
                "category": "TEXTTABLE",
                "scales": [{"label": "CompuScale" if i == 0 else "CompuScale_%d" % i,
                            "lower": lit.value, "upper": lit.value,
                            "vt": lit.vt or lit.name}
                           for i, lit in enumerate(en.literals)],
            })
        out.extend(self._bitfield_compus)
        return out

    def _data_constrs(self) -> List[Dict[str, Any]]:
        out = []
        for en in self._all_enums():
            if en.name not in self._used_enums:
                continue        # its compu method is not emitted either
            bits = BASE_TYPES.get(en.base_type, ("uint8", 8, "NONE", None))[1]
            out.append({"name": en.data_constr, "path": self.n.constr_path(en.data_constr),
                        "lower": 0, "upper": (1 << bits) - 1})
        out.extend(self._bitfield_constrs)
        return out

    # ------------------------------------------------------------------
    # topology
    # ------------------------------------------------------------------
    def _endpoints(self) -> List[Dict[str, Any]]:
        return [{
            "name": self.n.nep(ep.tag), "path": self.n.nep_path(ep.tag), "tag": ep.tag,
            "ipv4": ep.ipv4 or "ANY", "mask": "" if (ep.any or ep.multicast) else ep.mask,
            "fixed": not ep.any, "multicast": ep.multicast,
            "multicast_group_ref": self.n.multicast_group if ep.multicast else None,
        } for ep in self.plan.endpoints]

    def _pdu_triggerings(self, events, sd) -> List[Dict[str, Any]]:
        out = [{
            "name": ev["pt"], "path": ev["pt_path"], "pdu_dest": "I-SIGNAL-I-PDU",
            "pdu_ref": ev["pdu_path"], "port_ref": ev["pp_path"],
            "signal_triggering_ref": ev["st_path"],
        } for ev in events]
        out += [{
            "name": p["triggering"], "path": p["triggering_path"], "pdu_dest": "GENERAL-PURPOSE-PDU",
            "pdu_ref": p["path"], "port_ref": p["port_path"], "signal_triggering_ref": None,
        } for p in sd["pdus"]]
        return out

    def _sd_config(self, s: Service, server: bool) -> Dict[str, Any]:
        return {
            "ttl": s.sd.ttl,
            "delay_min": s.sd.initial_delay_min, "delay_max": s.sd.initial_delay_max,
            "base_delay": s.sd.repetition_base_delay, "repetitions": s.sd.repetition_max,
            "cyclic_offer": s.sd.cyclic_offer_delay,
            "rr_min": s.sd.request_response_delay_min,
            "rr_max": s.sd.request_response_delay_max,
            "major": s.major_version, "minor": s.minor_version,
            "server": server,
        }

    def _sockets(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for s in self.prj.services:
            dests = self.plan.destinations(s)
            local_sa = self.n.sa_local(s)
            # where each event group's CONSUMED-EVENT-GROUP ends up, so that the
            # EVENT-HANDLERs can reference the right one
            ceg_of: Dict[str, str] = {}
            for d in dests:
                peer_sa = self.plan.peer_socket(s, d)
                holder = peer_sa if s.is_provider else local_sa
                csi = self.n.csi(holder)
                for g in d.groups:
                    ceg_of[g.name] = "%s/%s/%s" % (self.n.aep_path(holder), csi, self.n.ceg(g))

            if s.is_provider:
                out.append(self._socket(s, local_sa, self.n.local, s.udp_port, connector=True,
                                        provided=self._provided(s, local_sa, s.event_groups, ceg_of)))
                for d in dests:
                    peer_sa = self.plan.peer_socket(s, d)
                    out.append(self._socket(s, peer_sa, d.zone, d.port, connector=False,
                                            consumed=self._consumed(s, peer_sa, d.groups, local_sa)))
            else:
                for d in dests:
                    peer_sa = self.plan.peer_socket(s, d)
                    out.append(self._socket(s, local_sa, self.n.local, s.udp_port, connector=True,
                                            consumed=self._consumed(s, local_sa, d.groups, peer_sa)))
                    out.append(self._socket(s, peer_sa, d.zone, d.port, connector=False,
                                            provided=self._provided(s, peer_sa, d.groups, ceg_of)))
        out += self._sd_sockets()
        return out

    def _socket(self, s: Service, sa: str, nep_tag: str, port: int, connector: bool,
                provided=None, consumed=None) -> Dict[str, Any]:
        return {
            "name": sa, "path": self.n.sa_path(sa),
            "aep": self.n.aep(sa), "aep_path": self.n.aep_path(sa),
            "nep_ref": self.n.nep_path(nep_tag), "port": port, "dynamic": False,
            "connector_ref": self.n.connector if connector else None,
            "multicast_connector_ref": None,
            "provided": provided, "consumed": consumed,
        }

    def _provided(self, s: Service, sa: str, groups, ceg_of: Dict[str, str]) -> Dict[str, Any]:
        aep_path = self.n.aep_path(sa)
        name = self.n.psi(sa)
        path = aep_path + "/" + name
        return {
            "name": name, "path": path,
            "routing_group_refs": [self._routing_group_for(s, g.name)["path"] for g in groups],
            "instance_id": parse_int(s.instance_id),
            "service_id": parse_int(s.interface_id),
            "sd": self._sd_config(s, server=True),
            # Only the instance this ECU really offers announces itself: it
            # carries the routing groups and the SD server config.  The
            # instance that stands for a remote provider just names the
            # application endpoint its events arrive on.
            "handlers": [{
                "name": self.n.eh(g), "path": path + "/" + self.n.eh(g),
                "aep_ref": aep_path,
                "offered": s.is_provider,
                "ceg_ref": ceg_of.get(g.name, ""),
                "routing_group_ref": self._routing_group_for(s, g.name)["path"],
                "rr_min": s.sd.request_response_delay_min,
                "rr_max": s.sd.request_response_delay_max,
                "ttl": s.sd.ttl,
            } for g in groups],
        }

    def _consumed(self, s: Service, sa: str, groups, peer: str) -> Dict[str, Any]:
        aep_path = self.n.aep_path(sa)
        name = self.n.csi(sa)
        path = aep_path + "/" + name
        return {
            "name": name, "path": path,
            "routing_group_refs": [self._routing_group_for(s, g.name)["path"] for g in groups],
            "psi_ref": "%s/%s" % (self.n.aep_path(peer), self.n.psi(peer)),
            "sd": self._sd_config(s, server=False),
            "groups": [{
                "name": self.n.ceg(g), "path": path + "/" + self.n.ceg(g),
                "aep_ref": aep_path,
                "group_id": parse_int(g.group_id),
                "routing_group_ref": self._routing_group_for(s, g.name)["path"],
                "rr_min": s.sd.request_response_delay_min,
                "rr_max": s.sd.request_response_delay_max,
                "ttl": s.sd.ttl,
            } for g in groups],
        }

    def _sd_sockets(self) -> List[Dict[str, Any]]:
        port = self.prj.services[0].sd_udp_port if self.prj.services else 30490
        out = [{
            "name": "SD_SA_ANY", "path": self.n.sa_path("SD_SA_ANY"),
            "aep": "SD_AEP_ANY", "aep_path": self.n.sa_path("SD_SA_ANY") + "/SD_AEP_ANY",
            "nep_ref": self.n.nep_path("ANY_SD"), "port": 0, "dynamic": True,
            "connector_ref": None, "multicast_connector_ref": None,
            "provided": None, "consumed": None,
        }]
        for tag in self.plan.sd_tags():
            sa = "SD_SA_" + tag
            out.append({
                "name": sa, "path": self.n.sa_path(sa),
                "aep": "SD_AEP_" + tag, "aep_path": self.n.sa_path(sa) + "/SD_AEP_" + tag,
                "nep_ref": self.n.nep_path(tag), "port": port, "dynamic": False,
                "connector_ref": None,
                "multicast_connector_ref": self.n.connector if tag == "MC" else None,
                "provided": None, "consumed": None,
            })
        return out

    def _bundles(self, events) -> List[Dict[str, Any]]:
        """One bundle per server socket; every peer is a connection inside it."""
        out: List[Dict[str, Any]] = []

        for s in self.prj.services:
            dests = self.plan.destinations(s)
            local_sa = self.n.sa_local(s)
            own = [ev for ev in events if ev["service"] is s]
            known = {g.name for g in s.event_groups}

            by_server: Dict[str, Dict[str, Any]] = {}
            for i, d in enumerate(dests):
                peer_sa = self.plan.peer_socket(s, d)
                server, client = (local_sa, peer_sa) if s.is_provider else (peer_sa, local_sa)
                server_ref = self.n.sa_path(server)
                client_ref = self.n.sa_path(client)

                # an event with an unknown group name lands on the first peer;
                # validate.py reports the dangling group separately
                names_here = set(d.group_names)
                mine = [ev for ev in own
                        if ev["event"].event_group in names_here
                        or (i == 0 and ev["event"].event_group not in known)]
                pdus = [{"header_id": ev["header_id"], "pt_ref": ev["pt_path"],
                         "routing_group_ref": ev["routing_group_ref"]} for ev in mine]

                b = by_server.setdefault(server_ref, {"first_dest": d, "conns": {}})
                c = b["conns"].get(client_ref)
                if c is None:
                    c = {"client_ref": client_ref, "from_request": False,
                         "label": "SC_%s_%s" % (s.tag, d.zone), "pdus": []}
                    b["conns"][client_ref] = c
                c["pdus"].extend(pdus)

            multi_bundle = len(by_server) > 1
            for server_ref, b in by_server.items():
                name = self.plan.bundle_name(s, b["first_dest"], multi_bundle)
                out.append({
                    "name": name, "path": "%s/%s" % (self.n.chan, name),
                    "server_ref": server_ref,
                    "connections": list(b["conns"].values()),
                })

        sd = self._service_discovery()
        by_tag = {p["triggering"]: p for p in sd["pdus"]}
        local_pdus = [by_tag["PT_SD_Ctrl_%s_Rx" % self.n.local],
                      by_tag["PT_SD_Ctrl_%s_Tx" % self.n.local]]
        plans = [(self.n.local, local_pdus)]
        plans += [(z, []) for z in self.plan.remote_tags()]
        plans += [("MC", [by_tag["PT_SD_Ctrl_Rx_Multicast"]])]
        for tag, pdus in plans:
            name = "SD_SCB_" + tag
            conn_pdus = [{"header_id": sd["header_id"], "pt_ref": p["triggering_path"],
                          "routing_group_ref": None} for p in pdus]
            out.append({
                "name": name, "path": "%s/%s" % (self.n.chan, name),
                "server_ref": self.n.sa_path("SD_SA_" + tag),
                "connections": [{
                    "client_ref": self.n.sa_path("SD_SA_ANY"),
                    "from_request": bool(conn_pdus),
                    "label": (name + "_SC") if conn_pdus else "",
                    "pdus": conn_pdus,
                }],
            })
        return out

    # ------------------------------------------------------------------
    def _ecu(self, events, sd) -> Dict[str, Any]:
        prj = self.prj
        ports = [{"kind": "I-PDU-PORT", "name": ev["pp"], "path": ev["pp_path"],
                  "direction": ev["direction"]} for ev in events]
        ports += [{"kind": "I-PDU-PORT", "name": p["port"], "path": p["port_path"],
                   "direction": p["direction"]} for p in sd["pdus"]]
        ports += [{"kind": "I-SIGNAL-PORT", "name": ev["sp"], "path": ev["sp_path"],
                   "direction": ev["direction"]} for ev in events]
        return {
            "name": prj.ecu_name, "path": self.n.ecu,
            "controller": "CT_%s_%s" % (prj.ecu_name, prj.cluster_name),
            "controller_path": self.n.controller,
            "connector": "CN_%s_%s" % (prj.ecu_name, prj.cluster_name),
            "connector_path": self.n.connector,
            "coupling_port": "CN_%s_%s" % (prj.ecu_name, prj.cluster_name),
            "ports": ports,
            "network_endpoint_refs": [self.n.nep_path(ep.tag) for ep in self.plan.endpoints
                                      if not ep.any],
        }

    def _fibex(self, events, sd, routing_groups) -> List[Dict[str, str]]:
        out = [{"dest": "ECU-INSTANCE", "path": self.n.ecu},
               {"dest": "ETHERNET-CLUSTER", "path": self.n.cluster}]
        out += [{"dest": "GENERAL-PURPOSE-PDU", "path": p["path"]} for p in sd["pdus"]]
        out += [{"dest": "I-SIGNAL", "path": ev["sig_path"]} for ev in events]
        out += [{"dest": "I-SIGNAL-I-PDU", "path": ev["pdu_path"]} for ev in events]
        out += [{"dest": "SO-AD-ROUTING-GROUP", "path": rg["path"]} for rg in routing_groups]
        seen, unique = set(), []
        for item in out:
            if item["path"] in seen:
                continue
            seen.add(item["path"])
            unique.append(item)
        return unique

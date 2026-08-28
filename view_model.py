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
    StructType, base_type_name, parse_int,
)

BASE_TYPE_BY_AR_NAME: Dict[str, tuple] = {}
for _k, _v in BASE_TYPES.items():
    BASE_TYPE_BY_AR_NAME.setdefault(_v[0], _v)


def build(prj: Project) -> Dict[str, Any]:
    n = Names(prj)
    plan = SocketPlan(prj, n)
    ctx = Builder(prj, n, plan).build()
    return ctx


class Builder:
    def __init__(self, prj: Project, n: Names, plan: SocketPlan):
        self.prj, self.n, self.plan = prj, n, plan
        self.fibex: List[Dict[str, str]] = []

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
                    "routing_group_ref": self.n.routing_group_path(s),
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

    def _routing_groups(self) -> List[Dict[str, str]]:
        out = []
        for s in self.prj.services:
            out.append({
                "name": s.routing_group,
                "path": self.n.routing_group_path(s),
                "control_type": ("ACTIVATION-MULTICAST"
                                 if s.routing_mode.lower().startswith("staticmulticast")
                                 else "ACTIVATION-UNICAST"),
            })
        return out

    def _port_interfaces(self, events) -> List[Dict[str, Any]]:
        return [{
            "name": ev["port_interface"], "path": ev["port_interface_path"],
            "element": ev["name"], "type_ref": ev["type_ref"],
        } for ev in events]

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
        out.append({
            "name": st.name, "path": path, "category": "STRUCTURE",
            "calibration": "READ-ONLY", "type_emitter": "RTE",
            "children": [self._impl_node(s, m.name, m.type, path, set())
                         for m in st.members],
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
            node["children"] = [self._impl_node(s, m.name, m.type, path, seen | {type_name})
                                for m in nested.members]
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
        out = []
        for en in self._all_enums():
            out.append({
                "name": en.compu_method, "path": self.n.compu_path(en.compu_method),
                "scales": [{"label": "CompuScale" if i == 0 else "CompuScale_%d" % i,
                            "lower": lit.value, "upper": lit.value,
                            "vt": lit.vt or lit.name}
                           for i, lit in enumerate(en.literals)],
            })
        return out

    def _data_constrs(self) -> List[Dict[str, Any]]:
        out = []
        for en in self._all_enums():
            bits = BASE_TYPES.get(en.base_type, ("uint8", 8, "NONE", None))[1]
            out.append({"name": en.data_constr, "path": self.n.constr_path(en.data_constr),
                        "lower": 0, "upper": (1 << bits) - 1})
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
            "routing_group_ref": self.n.routing_group_path(s),
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
                "routing_group_ref": self.n.routing_group_path(s),
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
            "routing_group_ref": self.n.routing_group_path(s),
            "psi_ref": "%s/%s" % (self.n.aep_path(peer), self.n.psi(peer)),
            "sd": self._sd_config(s, server=False),
            "groups": [{
                "name": self.n.ceg(g), "path": path + "/" + self.n.ceg(g),
                "aep_ref": aep_path,
                "group_id": parse_int(g.group_id),
                "routing_group_ref": self.n.routing_group_path(s),
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
        out: List[Dict[str, Any]] = []
        for s in self.prj.services:
            dests = self.plan.destinations(s)
            multi = len(dests) > 1
            local_sa = self.n.sa_local(s)
            own = [ev for ev in events if ev["service"] is s]
            for i, d in enumerate(dests):
                peer_sa = self.plan.peer_socket(s, d)
                server, client = (local_sa, peer_sa) if s.is_provider else (peer_sa, local_sa)
                name = self.plan.bundle_name(s, d, multi)
                # an event with an unknown group name lands on the first peer;
                # validate.py reports the dangling group separately
                names_here = set(d.group_names)
                known = {g.name for g in s.event_groups}
                mine = [ev for ev in own
                        if ev["event"].event_group in names_here
                        or (i == 0 and ev["event"].event_group not in known)]
                out.append({
                    "name": name, "path": "%s/%s" % (self.n.chan, name),
                    "client_ref": self.n.sa_path(client),
                    "server_ref": self.n.sa_path(server),
                    "client_from_request": False,
                    "label": "SC_" + (("%s_%s" % (s.tag, d.zone)) if multi else s.tag),
                    "connection_pdus": [],
                    "pdus": [{"header_id": ev["header_id"], "pt_ref": ev["pt_path"],
                              "routing_group_ref": ev["routing_group_ref"]} for ev in mine],
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
            out.append({
                "name": name, "path": "%s/%s" % (self.n.chan, name),
                "client_ref": self.n.sa_path("SD_SA_ANY"),
                "server_ref": self.n.sa_path("SD_SA_" + tag),
                "client_from_request": True,
                "label": name + "_SC",
                "connection_pdus": [{"header_id": sd["header_id"], "pt_ref": p["triggering_path"]}
                                    for p in pdus],
                "pdus": [],
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

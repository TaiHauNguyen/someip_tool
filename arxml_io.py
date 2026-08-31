"""Read an existing SOME/IP ARXML back into the model.

This lets the GUI open a hand written file (such as the original
ZA_someip.arxml) and show every configuration item, then regenerate a clean
file from it.  Information the ARXML does not carry - the names of the nested
struct types, the Excel descriptions - is reconstructed with a deterministic
rule so that a load/generate round trip is stable.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from someip_model import (
    BASE_TYPES, SOMEIP_HEADER_IN_PDU, ArrayType, EnumLiteral, EnumType,
    Endpoint, Event, EventGroup, Project, SdTiming, Service, StructMember,
    StructType, parse_int,
)


def _strip_ns(elem: ET.Element) -> None:
    for e in elem.iter():
        if isinstance(e.tag, str) and "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]
        for k in list(e.attrib):
            if "}" in k:
                e.attrib[k.split("}", 1)[1]] = e.attrib.pop(k)


def _sn(e: Optional[ET.Element]) -> str:
    if e is None:
        return ""
    c = e.find("SHORT-NAME")
    return (c.text or "").strip() if c is not None and c.text else ""


def _txt(e: Optional[ET.Element], path: str, default: str = "") -> str:
    if e is None:
        return default
    c = e.find(path)
    return (c.text or "").strip() if c is not None and c.text else default


def _flt(e: Optional[ET.Element], path: str, default: float) -> float:
    v = _txt(e, path)
    try:
        return float(v) if v else default
    except ValueError:
        return default


def _int(e: Optional[ET.Element], path: str, default: int = 0) -> int:
    return parse_int(_txt(e, path), default)


BASE_BY_AR = {}
for _k, _v in BASE_TYPES.items():
    BASE_BY_AR.setdefault(_v[0], _k)
BASE_BY_AR.update({"uint8": "uint8_t", "uint16": "uint16_t", "uint32": "uint32_t",
                   "uint64": "uint64_t", "sint8": "int8_t", "sint16": "int16_t",
                   "sint32": "int32_t", "sint64": "int64_t",
                   "float32": "float", "float64": "double", "boolean": "boolean"})


class ArxmlReader:
    def __init__(self, path: str):
        tree = ET.parse(path)
        self.root = tree.getroot()
        _strip_ns(self.root)
        self.by_path: Dict[str, ET.Element] = {}
        self._index(self.root, "")
        self.prj = Project()

    # -- indexing ---------------------------------------------------------
    def _index(self, elem: ET.Element, prefix: str) -> None:
        for child in list(elem):
            name = _sn(child)
            if name:
                path = prefix + "/" + name
                self.by_path.setdefault(path, child)
                self._index(child, path)
            else:
                self._index(child, prefix)

    def find(self, path: str) -> Optional[ET.Element]:
        return self.by_path.get(path)

    def all(self, tag: str) -> List[ET.Element]:
        return list(self.root.iter(tag))

    # -- entry point ------------------------------------------------------
    def read(self) -> Project:
        prj = self.prj
        self._read_topology_basics()
        enums = self._read_enums()
        structs = self._read_structs()
        arrays = self._read_arrays()
        events = self._read_events()
        prj.services = self._read_services(events, structs, enums, arrays)
        self._read_port_iface_prefixes(prj.services)
        return prj

    def _read_port_iface_prefixes(self, services: List[Service]) -> None:
        """Recover the SENDER-RECEIVER-INTERFACE naming prefix from the file.

        The prefix is a project setting, so a file that follows its own
        convention (`SoIp_I_Srv_`, `IF_`, none at all) would otherwise be
        regenerated under the tool's default and every port interface - short
        name and UUID alike - would silently change.
        """
        by_event = {e.name: s for s in services for e in s.events}
        found: Dict[bool, str] = {}
        for si in self.all("SENDER-RECEIVER-INTERFACE"):
            iface = _sn(si)
            for vdp in si.iter("VARIABLE-DATA-PROTOTYPE"):
                ev = _sn(vdp)
                svc = by_event.get(ev)
                if not ev or svc is None or not iface.endswith(ev):
                    continue
                found.setdefault(svc.is_provider, iface[:len(iface) - len(ev)])
        if True in found:
            self.prj.port_iface_prefix_provider = found[True]
        if False in found:
            self.prj.port_iface_prefix_consumer = found[False]

    # -- topology ---------------------------------------------------------
    def _read_topology_basics(self) -> None:
        prj = self.prj
        ecu = next(iter(self.all("ECU-INSTANCE")), None)
        if ecu is not None:
            prj.ecu_name = _sn(ecu)
            prj.com_tx_time_base = _flt(ecu, "COM-CONFIGURATION-TX-TIME-BASE", 0.01)
        cluster = next(iter(self.all("ETHERNET-CLUSTER")), None)
        if cluster is not None:
            prj.cluster_name = _sn(cluster)
            cond = cluster.find("ETHERNET-CLUSTER-VARIANTS/ETHERNET-CLUSTER-CONDITIONAL")
            prj.baudrate = _int(cond, "BAUDRATE", 100000000)
            ch = cond.find("PHYSICAL-CHANNELS/ETHERNET-PHYSICAL-CHANNEL") if cond is not None else None
            if ch is not None:
                prj.channel_name = _sn(ch)
                vlan = ch.find("VLAN")
                if vlan is not None:
                    prj.vlan_name = _sn(vlan)
                    prj.vlan_id = _int(vlan, "VLAN-IDENTIFIER", 5)
            mg = cond.find("MAC-MULTICAST-GROUPS/MAC-MULTICAST-GROUP") if cond is not None else None
            if mg is not None:
                prj.multicast_mac = _txt(mg, "MAC-MULTICAST-ADDRESS", prj.multicast_mac)
        ctrl = next(iter(self.all("ETHERNET-COMMUNICATION-CONTROLLER")), None)
        if ctrl is not None:
            cond = ctrl.find("ETHERNET-COMMUNICATION-CONTROLLER-VARIANTS/"
                             "ETHERNET-COMMUNICATION-CONTROLLER-CONDITIONAL")
            if cond is not None:
                prj.ecu_mac_unicast = _txt(cond, "MAC-UNICAST-ADDRESS", prj.ecu_mac_unicast)
                prj.vlan_priority = _int(cond, "COUPLING-PORTS/COUPLING-PORT/VLAN-MEMBERSHIPS/"
                                               "VLAN-MEMBERSHIP/DEFAULT-PRIORITY", 6)
        for nep in self.all("NETWORK-ENDPOINT"):
            cfg = nep.find("NETWORK-ENDPOINT-ADDRESSES/IPV-4-CONFIGURATION")
            ip = _txt(cfg, "IPV-4-ADDRESS")
            if ip.startswith("239.") or ip.startswith("224."):
                prj.multicast_ipv4 = ip
            mask = _txt(cfg, "NETWORK-MASK")
            if mask:
                prj.network_mask = mask

    def _network_endpoints(self) -> Dict[str, Tuple[str, str]]:
        """{NEP short name: (ipv4, mask)}"""
        out = {}
        for nep in self.all("NETWORK-ENDPOINT"):
            cfg = nep.find("NETWORK-ENDPOINT-ADDRESSES/IPV-4-CONFIGURATION")
            out[_sn(nep)] = (_txt(cfg, "IPV-4-ADDRESS"), _txt(cfg, "NETWORK-MASK"))
        return out

    # -- data types -------------------------------------------------------
    def _read_enums(self) -> Dict[str, EnumType]:
        out: Dict[str, EnumType] = {}
        for cm in self.all("COMPU-METHOD"):
            name = _sn(cm)
            en = EnumType(name=name, base_type="uint8_t")
            for sc in cm.iter("COMPU-SCALE"):
                vt = _txt(sc, "COMPU-CONST/VT")
                if not vt:
                    continue
                en.literals.append(EnumLiteral(
                    name=_literal_name(name, vt),
                    value=parse_int(_txt(sc, "LOWER-LIMIT")),
                    vt=vt))
            out[name] = en
        for dc in self.all("DATA-CONSTR"):
            upper = parse_int(_txt(dc, "DATA-CONSTR-RULES/DATA-CONSTR-RULE/"
                                       "INTERNAL-CONSTRS/UPPER-LIMIT"), 255)
            base = {255: "uint8_t", 65535: "uint16_t", 4294967295: "uint32_t"}.get(upper, "uint8_t")
            stem = _sn(dc)[:-5] if _sn(dc).endswith("const") else _sn(dc)
            for cand in (stem + "Type", stem):
                if cand in out:
                    out[cand].base_type = base
                    break
        return out

    def _read_structs(self) -> Dict[str, List[StructType]]:
        """{top level struct name: [top struct, nested structs...]}"""
        out: Dict[str, List[StructType]] = {}
        for idt in self.all("IMPLEMENTATION-DATA-TYPE"):
            if _txt(idt, "CATEGORY") != "STRUCTURE":
                continue
            top = StructType(name=_sn(idt))
            collected: List[StructType] = [top]
            self._read_members(idt.find("SUB-ELEMENTS"), top, collected)
            out[top.name] = collected
        return out

    def _read_arrays(self) -> Dict[str, ArrayType]:
        """{array short name: ArrayType} for every CATEGORY ARRAY data type."""
        out: Dict[str, ArrayType] = {}
        for idt in self.all("IMPLEMENTATION-DATA-TYPE"):
            if _txt(idt, "CATEGORY") != "ARRAY":
                continue
            subs = idt.find("SUB-ELEMENTS")
            el = subs.find("IMPLEMENTATION-DATA-TYPE-ELEMENT") if subs is not None else None
            if el is None:
                continue
            out[_sn(idt)] = ArrayType(
                name=_sn(idt),
                element_name=_sn(el),
                element_type=self._element_type(el),
                size=_int(el, "ARRAY-SIZE", 1),
                size_semantics=_txt(el, "ARRAY-SIZE-SEMANTICS", "FIXED-SIZE"),
            )
        return out

    @staticmethod
    def _element_type(el: ET.Element) -> str:
        """The model type name an IMPLEMENTATION-DATA-TYPE-ELEMENT stands for."""
        cond = el.find("SW-DATA-DEF-PROPS/SW-DATA-DEF-PROPS-VARIANTS/SW-DATA-DEF-PROPS-CONDITIONAL")
        if cond is None:
            return "uint8_t"
        # an enum keeps its compu method, a named type is referenced, a plain
        # value carries the base type
        for tag in ("COMPU-METHOD-REF", "IMPLEMENTATION-DATA-TYPE-REF", "BASE-TYPE-REF"):
            ref = cond.find(tag)
            if ref is None or not ref.text:
                continue
            leaf = ref.text.rsplit("/", 1)[-1]
            if tag == "COMPU-METHOD-REF":
                return leaf
            return BASE_BY_AR.get(leaf, leaf)
        return "uint8_t"

    def _read_members(self, subs: Optional[ET.Element], target: StructType,
                      collected: List[StructType]) -> None:
        if subs is None:
            return
        for el in subs.findall("IMPLEMENTATION-DATA-TYPE-ELEMENT"):
            name = _sn(el)
            cat = _txt(el, "CATEGORY")
            if cat == "STRUCTURE":
                nested_name = _nested_struct_name(name)
                nested = StructType(name=nested_name, synthetic=True)
                collected.append(nested)
                self._read_members(el.find("SUB-ELEMENTS"), nested, collected)
                target.members.append(StructMember(name=name, type=nested_name))
                continue
            cond = el.find("SW-DATA-DEF-PROPS/SW-DATA-DEF-PROPS-VARIANTS/SW-DATA-DEF-PROPS-CONDITIONAL")
            compu = cond.find("COMPU-METHOD-REF") if cond is not None else None
            if compu is not None and compu.text:
                target.members.append(StructMember(name=name, type=compu.text.rsplit("/", 1)[-1]))
                continue
            impl = cond.find("IMPLEMENTATION-DATA-TYPE-REF") if cond is not None else None
            if impl is not None and impl.text:
                leaf = impl.text.rsplit("/", 1)[-1]
                target.members.append(StructMember(name=name, type=BASE_BY_AR.get(leaf, leaf)))
                continue
            bt = cond.find("BASE-TYPE-REF") if cond is not None else None
            ar = bt.text.rsplit("/", 1)[-1] if bt is not None and bt.text else "uint8"
            target.members.append(StructMember(name=name, type=BASE_BY_AR.get(ar, "uint8_t")))

    # -- events -----------------------------------------------------------
    def _read_events(self) -> Dict[str, Dict]:
        """{event name: {pdu_length, signal, pdu triggering path}}"""
        out: Dict[str, Dict] = {}
        for pdu in self.all("I-SIGNAL-I-PDU"):
            name = _sn(pdu)
            ev = name[4:] if name.startswith("pdu_") else name
            out[ev] = {"pdu_length": _int(pdu, "LENGTH")}
        return out

    # -- services ---------------------------------------------------------
    def _read_services(self, events, structs, enums, arrays) -> List[Service]:
        neps = self._network_endpoints()
        connector_local = "/Topology/HardwareComponents/%s/CN_%s_%s" % (
            self.prj.ecu_name, self.prj.ecu_name, self.prj.cluster_name)

        # socket address -> (nep name, udp port, is_local)
        sockets: Dict[str, Dict] = {}
        for sa in self.all("SOCKET-ADDRESS"):
            ap = sa.find("APPLICATION-ENDPOINT")
            if ap is None:
                continue
            nref = ap.find("NETWORK-ENDPOINT-REF")
            cref = sa.find("CONNECTOR-REF")
            sockets[_sn(sa)] = {
                "nep": nref.text.rsplit("/", 1)[-1] if nref is not None and nref.text else "",
                "port": _int(ap, "TP-CONFIGURATION/UDP-TP/UDP-TP-PORT/PORT-NUMBER"),
                "local": cref is not None and (cref.text or "").strip() == connector_local,
                "elem": sa, "aep": ap,
            }
            # the endpoint our own connector points at names the local ECU tag
            # (NEP_<tag>); keeping it makes a read/generate round trip stable
            if sockets[_sn(sa)]["local"] and not self.prj.local_endpoint_tag:
                self.prj.local_endpoint_tag = _zone_of(sockets[_sn(sa)]["nep"])

        # header ids per pdu triggering, from the connection bundles
        header_by_pt: Dict[str, int] = {}
        for ident in self.all("SOCKET-CONNECTION-IPDU-IDENTIFIER"):
            r = ident.find("PDU-TRIGGERING-REF")
            if r is not None and r.text:
                header_by_pt[r.text.rsplit("/", 1)[-1]] = _int(ident, "HEADER-ID")

        # A SOME/IP service always shows up twice: once as the offering
        # PROVIDED-SERVICE-INSTANCE and once as the requesting
        # CONSUMED-SERVICE-INSTANCE.  The authoritative link between the two is
        # the CONSUMED-SERVICE-INSTANCE/PROVIDED-SERVICE-INSTANCE-REF.
        # One provider may serve several consumers, so a PSI can be referenced
        # by more than one CSI; those all belong to the same service.
        psi_by_path = {p: e for p, e in self.by_path.items()
                       if e.tag == "PROVIDED-SERVICE-INSTANCE"}
        grouped: Dict[int, Tuple[ET.Element, List[ET.Element]]] = {}
        orphans: List[ET.Element] = []
        for csi in self.all("CONSUMED-SERVICE-INSTANCE"):
            r = csi.find("PROVIDED-SERVICE-INSTANCE-REF")
            psi = psi_by_path.get((r.text or "").strip()) if r is not None and r.text else None
            if psi is None:
                orphans.append(csi)
                continue
            grouped.setdefault(id(psi), (psi, []))[1].append(csi)
        for psi in psi_by_path.values():
            grouped.setdefault(id(psi), (psi, []))

        pairs = [(psi, csis) for psi, csis in grouped.values()]
        pairs += [(None, [csi]) for csi in orphans]

        services = [self._build_service(psi, csis, sockets, neps) for psi, csis in pairs]
        services = [s for s in services if s is not None]
        services.sort(key=lambda x: (x.role != "provider", x.tag))
        self._attach_payload(services, events, structs, enums, arrays)
        return services

    def _build_service(self, psi, csis, sockets, neps) -> Optional[Service]:
        psi_sa, psi_info = self._owner_socket(psi, sockets) if psi is not None else ("", {})
        csi_infos = [(c,) + self._owner_socket(c, sockets) for c in csis]
        if not psi_info and not csi_infos:
            return None

        s = Service()
        local_csi = next((t for t in csi_infos if t[2].get("local")), None)
        if local_csi is not None:
            # we consume the service: our socket holds the CONSUMED-SERVICE-INSTANCE
            s.role = "consumer"
            local_info, peer_info = local_csi[2], psi_info
            local_sa = local_csi[1]
        elif psi_info.get("local") or not csi_infos:
            # we offer it: every CSI is one of our peers
            s.role = "provider"
            local_info = psi_info
            peer_info = csi_infos[0][2] if csi_infos else {}
            local_sa = psi_sa
        else:
            s.role, local_info, peer_info = "provider", psi_info or csi_infos[0][2], csi_infos[0][2]
            local_sa = psi_sa or csi_infos[0][1]

        first_csi = local_csi[0] if local_csi is not None else (csis[0] if csis else None)
        s.tag = self._derive_tag(psi, first_csi, local_sa)
        s.instance_name = s.tag + "Service"
        s.interface_name = s.tag + "ServiceInterface"
        s.deployment_name = s.interface_name + "_Deployment"
        s.service_instance_name = ("Provided" if s.is_provider else "Consumed") \
            + "Someip" + s.instance_name + "Instance"
        s.mapping_name = s.instance_name + "InstanceToMachineMapping"

        local_ip = neps.get(local_info.get("nep", ""), ("", ""))[0]
        peer_ip = neps.get(peer_info.get("nep", ""), ("", ""))[0]
        s.udp_port = local_info.get("port", 0)
        s.local = Endpoint(zone=_zone_of(local_info.get("nep", "")), ipv4=local_ip)

        if psi is not None:
            s.interface_id = "0x%04X" % _int(psi, "SERVICE-IDENTIFIER")
            s.instance_id = "0x%04X" % _int(psi, "INSTANCE-IDENTIFIER")
            sd = psi.find("SD-SERVER-CONFIG")
            offer = sd.find("INITIAL-OFFER-BEHAVIOR") if sd is not None else None
            s.major_version = _int(sd, "SERVER-SERVICE-MAJOR-VERSION", 1)
            s.minor_version = _int(sd, "SERVER-SERVICE-MINOR-VERSION", 0)
            s.sd = SdTiming(
                ttl=_int(sd, "TTL", 3),
                initial_delay_min=_flt(offer, "INITIAL-DELAY-MIN-VALUE", 0.05),
                initial_delay_max=_flt(offer, "INITIAL-DELAY-MAX-VALUE", 0.05),
                repetition_base_delay=_flt(offer, "INITIAL-REPETITIONS-BASE-DELAY", 0.1),
                repetition_max=_int(offer, "INITIAL-REPETITIONS-MAX", 3),
                cyclic_offer_delay=_flt(sd, "OFFER-CYCLIC-DELAY", 2.0),
                request_response_delay_min=_flt(sd, "REQUEST-RESPONSE-DELAY/MIN-VALUE", 0.02),
                request_response_delay_max=_flt(sd, "REQUEST-RESPONSE-DELAY/MAX-VALUE", 0.2),
            )

        # Event groups: the identifier lives on the consumer side, the handler
        # name on the provider side.  A provider reached by several consumers
        # contributes one batch of groups per peer, each with its own address.
        groups: List[EventGroup] = []
        if s.is_provider:
            for csi, _sa, info in csi_infos:
                ip = neps.get(info.get("nep", ""), ("", ""))[0]
                groups += _event_groups(csi, len(groups),
                                        ip, info.get("port", 0), _zone_of(info.get("nep", "")))
        elif local_csi is not None:
            groups += _event_groups(local_csi[0], 0, local_ip, s.udp_port, s.local.zone)
            s.remote = Endpoint(zone=_zone_of(peer_info.get("nep", "")), ipv4=peer_ip)
            s.remote_udp_port = peer_info.get("port", 30500)

        if not groups and psi is not None:
            for eh in psi.iter("EVENT-HANDLER"):
                name = _sn(eh)
                groups.append(EventGroup(index=len(groups) + 1,
                                         name=name[3:] if name.startswith("EH_") else name,
                                         dest_ipv4=peer_ip,
                                         dest_udp_port=peer_info.get("port", 0),
                                         dest_zone=_zone_of(peer_info.get("nep", ""))))
        s.event_groups = groups
        return s

    def _derive_tag(self, psi, csi, local_sa: str) -> str:
        for inst in (psi, csi):
            if inst is None:
                continue
            rg = inst.find("ROUTING-GROUP-REFS/ROUTING-GROUP-REF")
            if rg is not None and rg.text:
                # SoAdRG_<tag>_<event group>_PEG|CEG, and the older
                # SoAdRG_<tag>_P|C_EventGroup that earlier files carry
                short = rg.text.rsplit("/", 1)[-1]
                m = (re.match(r"SoAdRG_(.+?)_.+_(?:PEG|CEG)$", short)
                     or re.match(r"SoAdRG_(.+?)_(?:P|C)_EventGroup$", short))
                if m:
                    return m.group(1)
        if local_sa.startswith("SA_"):
            return local_sa[3:].rsplit("_", 1)[-1]
        return local_sa or "Service"

    def _owner_socket(self, inst: ET.Element, sockets) -> Tuple[str, Dict]:
        for name, info in sockets.items():
            for e in info["aep"].iter():
                if e is inst:
                    return name, info
        return "", {}

    def _attach_payload(self, services: List[Service], events, structs, enums, arrays) -> None:
        """Attach events, structs, enums and arrays to the service that owns them."""
        # map: event name -> service, via the header id upper half
        by_iface = {parse_int(s.interface_id): s for s in services}
        pt_header: Dict[str, int] = {}
        for ident in self.all("SOCKET-CONNECTION-IPDU-IDENTIFIER"):
            r = ident.find("PDU-TRIGGERING-REF")
            hid = _int(ident, "HEADER-ID")
            if r is not None and r.text and hid != 0xFFFF8100:
                pt = r.text.rsplit("/", 1)[-1]
                pt_header[pt[3:] if pt.startswith("PT_") else pt] = hid

        used_structs: Dict[str, Service] = {}
        for ev_name, info in events.items():
            hid = pt_header.get(ev_name)
            if hid is None:
                continue
            svc = by_iface.get(hid >> 16) or (services[0] if services else None)
            if svc is None:
                continue
            struct_name = _struct_for_event(self, ev_name)
            e = Event(
                index=len(svc.events) + 1,
                name=ev_name,
                event_id="0x%04X" % (hid & 0xFFFF),
                # the ARXML stores payload + header, the model the payload
                # alone - this is the inverse of Event.pdu_length()
                payload_length=max(info["pdu_length"] - SOMEIP_HEADER_IN_PDU, 0),
                serializer=struct_name,
                transport="UDP",
                event_group=svc.event_groups[0].name if svc.event_groups else "",
            )
            svc.events.append(e)
            if struct_name:
                used_structs[struct_name] = svc

        for top, group in structs.items():
            svc = used_structs.get(top) or (services[0] if services else None)
            if svc is None:
                continue
            for st in group:
                if svc.find_struct(st.name) is None:
                    svc.structs.append(st)

        # an array is a named type of its own, so pull in every one a struct
        # member - or an event serializer - reaches, arrays of arrays included
        for svc in services:
            wanted: List[str] = []
            pending = [m.type for st in svc.structs for m in st.members]
            pending += [e.serializer for e in svc.events]
            while pending:
                name = pending.pop()
                if name not in arrays or name in wanted:
                    continue
                wanted.append(name)
                pending.append(arrays[name].element_type)
            for name in sorted(wanted):
                if svc.find_array(name) is None:
                    svc.arrays.append(arrays[name])

        for svc in services:
            wanted_enums = set()
            for st in svc.structs:
                for m in st.members:
                    if m.type in enums:
                        wanted_enums.add(m.type)
            for ar in svc.arrays:
                if ar.element_type in enums:
                    wanted_enums.add(ar.element_type)
            for name in sorted(wanted_enums):
                if svc.find_enum(name) is None:
                    svc.enums.append(enums[name])

        # An enum that no member happens to reference is still part of the
        # file, and the ECU code uses its <VT> constants.  Dropping it here
        # would delete the COMPU-METHOD from the next generated file, so park
        # the leftovers on the first service; validate.py reports them as
        # unreferenced instead.
        if services:
            attached = {en.name for svc in services for en in svc.enums}
            for name in sorted(set(enums) - attached):
                services[0].enums.append(enums[name])


def _event_groups(csi, start: int, ipv4: str, port: int, zone: str) -> List[EventGroup]:
    out: List[EventGroup] = []
    for ceg in csi.iter("CONSUMED-EVENT-GROUP"):
        name = _sn(ceg)
        out.append(EventGroup(
            index=start + len(out) + 1,
            name=name[4:] if name.startswith("CEG_") else name,
            group_id="0x%02X" % _int(ceg, "EVENT-GROUP-IDENTIFIER"),
            dest_ipv4=ipv4, dest_udp_port=port, dest_zone=zone))
    return out


def _zone_of(nep_short_name: str) -> str:
    return nep_short_name[4:] if nep_short_name.startswith("NEP_") else nep_short_name


def _nested_struct_name(member_name: str) -> str:
    return member_name[:1].upper() + member_name[1:] + "Struct"


def _literal_name(enum_name: str, vt: str) -> str:
    """CRASH_OTPT_STS_NO_EVENT + CrashOtptStsType -> NoEvent"""
    stem = enum_name[:-4] if enum_name.endswith("Type") else enum_name
    prefix = re.sub(r"[^A-Z0-9]", "", stem.upper())
    parts = [p for p in vt.split("_") if p]
    # drop as many leading tokens as the enum name prefix covers
    acc = ""
    drop = 0
    for p in parts:
        if prefix.startswith(re.sub(r"[^A-Z0-9]", "", (acc + p).upper())):
            acc += p
            drop += 1
        else:
            break
    rest = parts[drop:] or parts
    return "".join(w.capitalize() for w in rest)


def _struct_for_event(reader: "ArxmlReader", event_name: str) -> str:
    """Find the struct an event serialises through its port interface."""
    for si in reader.all("SENDER-RECEIVER-INTERFACE"):
        for vdp in si.iter("VARIABLE-DATA-PROTOTYPE"):
            if _sn(vdp) == event_name:
                t = vdp.find("TYPE-TREF")
                if t is not None and t.text:
                    return t.text.rsplit("/", 1)[-1]
    return ""


def read(path: str) -> Project:
    return ArxmlReader(path).read()

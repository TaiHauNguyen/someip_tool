"""Short name and topology derivation rules.

This is the part that genuinely belongs in code: given the model, work out what
each element is called and which endpoint/socket talks to which.  What XML gets
written around those names is the template's business (templates/*.arxml.tpl).

Every rule below is expressed in terms of the model, never of a concrete
project, so a new service or a renamed ECU flows through automatically.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Tuple

from someip_model import Event, EventGroup, Project, Service


def uuid_for(path: str) -> str:
    """Deterministic UUID: regenerating the file keeps the same identities."""
    h = hashlib.md5(path.encode("utf-8")).hexdigest()
    return "%s-%s-%s-%s-%s" % (h[0:8], h[8:12], h[12:16], h[16:20], h[20:32])


class Names:
    """All short names and absolute paths of the generated file."""

    def __init__(self, prj: Project):
        self.prj = prj
        self.local = prj.local_tag()
        self.chan = "/Topology/Clusters/%s/%s" % (prj.cluster_name, prj.channel_name)
        self.connector = "/Topology/HardwareComponents/%s/CN_%s_%s" % (
            prj.ecu_name, prj.ecu_name, prj.cluster_name)
        self.controller = "/Topology/HardwareComponents/%s/CT_%s_%s" % (
            prj.ecu_name, prj.ecu_name, prj.cluster_name)
        self.ecu = "/Topology/HardwareComponents/" + prj.ecu_name
        self.cluster = "/Topology/Clusters/" + prj.cluster_name
        self.transformer_set = "/Communication/DataTransformation/TransformerConfiguration"
        self.multicast_group = self.cluster + "/MulticastMacAddress"

    # -- communication ----------------------------------------------------
    def sig(self, e: Event) -> str:
        return "sig_" + e.name

    def sys(self, e: Event) -> str:
        return "sys_" + e.name

    def pdu(self, e: Event) -> str:
        return "pdu_" + e.name

    def sig_map(self, e: Event) -> str:
        return "map_" + self.sig(e)

    def sig_path(self, e: Event) -> str:
        return "/Communication/Signals/" + self.sig(e)

    def sys_path(self, e: Event) -> str:
        return "/Communication/SystemSignals/" + self.sys(e)

    def pdu_path(self, e: Event) -> str:
        return "/Communication/PDUs/" + self.pdu(e)

    # -- triggerings / ports ----------------------------------------------
    def st(self, e: Event) -> str:
        return "ST_" + e.name

    def pt(self, e: Event) -> str:
        return "PT_" + e.name

    def pp(self, e: Event) -> str:
        return "PP_" + e.name

    def sp(self, e: Event) -> str:
        return "SP_" + e.name

    def st_path(self, e: Event) -> str:
        return "%s/%s" % (self.chan, self.st(e))

    def pt_path(self, e: Event) -> str:
        return "%s/%s" % (self.chan, self.pt(e))

    def pp_path(self, e: Event) -> str:
        return "%s/%s" % (self.connector, self.pp(e))

    def sp_path(self, e: Event) -> str:
        return "%s/%s" % (self.connector, self.sp(e))

    # -- service discovery -------------------------------------------------
    def sd_rx(self) -> str:
        return "SD_Ctrl_Rx_" + self.local

    def sd_tx(self) -> str:
        return "SD_Ctrl_Tx_" + self.local

    def sd_mc(self) -> str:
        return "SD_Ctrl_Rx_Multicast"

    def pdu_pkg(self, name: str) -> str:
        return "/Communication/PDUs/" + name

    # -- endpoints / sockets -----------------------------------------------
    def nep(self, tag: str) -> str:
        return "NEP_" + tag

    def nep_path(self, tag: str) -> str:
        return "%s/%s" % (self.chan, self.nep(tag))

    def sa_local(self, s: Service) -> str:
        return "SA_" + s.tag

    def sa_peer(self, s: Service, zone: str) -> str:
        return "SA_%s_%s" % (zone, s.tag)

    def aep(self, socket: str) -> str:
        return "AEP_" + socket[3:] if socket.startswith("SA_") else "AEP_" + socket

    def sa_path(self, socket: str) -> str:
        return "%s/%s" % (self.chan, socket)

    def aep_path(self, socket: str) -> str:
        return "%s/%s/%s" % (self.chan, socket, self.aep(socket))

    def psi(self, socket: str) -> str:
        return "PSI_" + socket[3:]

    def csi(self, socket: str) -> str:
        return "CSI_" + socket[3:]

    def ceg(self, g: EventGroup) -> str:
        return "CEG_" + g.name

    def eh(self, g: EventGroup) -> str:
        return "EH_" + g.name

    def routing_group_path(self, s: Service) -> str:
        return "/SoAdRoutingGroups/" + s.routing_group

    def port_interface(self, s: Service, e: Event) -> str:
        prefix = (self.prj.port_iface_prefix_provider if s.is_provider
                  else self.prj.port_iface_prefix_consumer)
        return prefix + e.name

    def port_interface_path(self, s: Service, e: Event) -> str:
        return "/PortInterfaces/" + self.port_interface(s, e)

    def impl_type_path(self, struct_name: str) -> str:
        return "/DataTypes/" + struct_name

    def compu_path(self, name: str) -> str:
        return "/DataTypes/CompuMethods/" + name

    def constr_path(self, name: str) -> str:
        return "/DataTypes/DataConstraints/" + name


class Endpoint:
    def __init__(self, tag: str, ipv4: str, mask: str = "",
                 multicast: bool = False, any_: bool = False):
        self.tag, self.ipv4, self.mask = tag, ipv4, mask
        self.multicast, self.any = multicast, any_


class Destination:
    """One peer a service talks to, with the event groups delivered there.

    A provider may offer several event groups to different ECUs, so a service
    has as many peer sockets as it has distinct destinations - not one.
    """

    def __init__(self, zone: str, ipv4: str, port: int, groups: List[EventGroup]):
        self.zone, self.ipv4, self.port, self.groups = zone, ipv4, port, groups

    @property
    def group_names(self) -> List[str]:
        return [g.name for g in self.groups]


class SocketPlan:
    """Which network endpoints exist and which socket pairs talk to each other."""

    def __init__(self, prj: Project, names: Names):
        self.prj, self.n = prj, names
        self.local_ip = prj.local_endpoint().ipv4
        self.endpoints: List[Endpoint] = []
        self._by_tag: Dict[str, Endpoint] = {}

        self._add(Endpoint("ANY_SD", "ANY", any_=True))
        self._add(Endpoint("MC", prj.multicast_ipv4, multicast=True))
        self._add(Endpoint(names.local, self.local_ip, prj.network_mask))

        for s in prj.services:
            for d in self.destinations(s):
                if d.zone != names.local:
                    self._add(Endpoint(d.zone, d.ipv4, prj.network_mask))

    def _add(self, ep: Endpoint) -> None:
        known = self._by_tag.get(ep.tag)
        if known is not None:
            if ep.ipv4 and not known.ipv4:
                known.ipv4 = ep.ipv4
            return
        self._by_tag[ep.tag] = ep
        self.endpoints.append(ep)

    def zone_tag(self, ipv4: str, zone: str) -> str:
        """A destination that resolves to the local ECU reuses the local endpoint."""
        if ipv4 and ipv4 == self.local_ip:
            return self.n.local
        return zone or "REMOTE"

    def destinations(self, s: Service) -> List[Destination]:
        """Every peer this service exchanges events with.

        For a provider that is one entry per distinct (zone, address, port) of
        its event groups.  A consumer receives on its own socket, so its single
        peer is the ECU that offers the service.
        """
        if not s.is_provider:
            zone = self.zone_tag(s.remote.ipv4, s.remote.zone or "REMOTE")
            return [Destination(zone, s.remote.ipv4, s.remote_udp_port, list(s.event_groups))]

        buckets: Dict[tuple, List[EventGroup]] = {}
        for g in s.event_groups:
            key = (self.zone_tag(g.dest_ipv4, g.dest_zone), g.dest_ipv4, g.dest_udp_port)
            buckets.setdefault(key, []).append(g)
        return [Destination(zone, ipv4, port, groups)
                for (zone, ipv4, port), groups in buckets.items()]

    def remote_tags(self) -> List[str]:
        return [e.tag for e in self.endpoints
                if e.tag not in (self.n.local, "MC", "ANY_SD")]

    def sd_tags(self) -> List[str]:
        return [self.n.local] + self.remote_tags() + ["MC"]

    def peer_socket(self, s: Service, d: Destination) -> str:
        return self.n.sa_peer(s, d.zone)

    def bundle_name(self, s: Service, d: Destination, multi: bool) -> str:
        """SCB_<tag>, or SCB_<tag>_<zone> once a service has several peers."""
        return "SCB_%s_%s" % (s.tag, d.zone) if multi else "SCB_" + s.tag

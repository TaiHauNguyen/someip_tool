"""Command line front end - same engine as the GUI, for batch / CI use.

    python someip_cli.py build PCU_Provider.xlsx RMCU_Consumer.xlsx -o ZA_someip.arxml
    python someip_cli.py build *.xlsx --base ZA_someip.arxml -o out.arxml
    python someip_cli.py build ZA_someip.someip.json -o out.arxml --template my.tpl
    python someip_cli.py show      ZA_someip.arxml
    python someip_cli.py check     PCU_Provider.xlsx RMCU_Consumer.xlsx
    python someip_cli.py templates

Inputs may be mixed: .arxml/.json become the base project, .xlsx are imported
on top of it.  The workbooks win for everything they define; the base supplies
what a workbook cannot express (see resolve.py).
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import arxml_gen
import arxml_io
import excel_io
import licensing
import validate as validator
from someip_model import Project, parse_int


def read_project(path: str) -> Project:
    return Project.from_json(path) if path.lower().endswith(".json") else arxml_io.read(path)


def load(inputs, base_path=None):
    """Build a Project from any mix of .xlsx, .arxml and .json inputs."""
    base = read_project(base_path) if base_path else None
    excels = []
    for path in inputs:
        if path.lower().endswith(".xlsx"):
            if not os.path.basename(path).startswith("~$"):
                excels.append(path)
        else:
            base = read_project(path)
    log = []
    prj = excel_io.import_project(excels, base, log=log) if excels else (base or Project())
    return prj, log


def report(prj: Project, verbose: bool = False) -> int:
    issues = validator.validate(prj)
    for sev, where, msg in issues:
        if sev == "INFO" and not verbose:
            continue
        print("%-8s %-34s %s" % (sev, where, msg))
    print("--", validator.summary(issues))
    return sum(1 for sev, _, _ in issues if sev == validator.ERROR)


def show(prj: Project) -> None:
    print("Project %s   ECU=%s cluster=%s channel=%s VLAN=%d/prio %d   template=%s"
          % (prj.name, prj.ecu_name, prj.cluster_name, prj.channel_name,
             prj.vlan_id, prj.vlan_priority, prj.template))
    for s in prj.services:
        print("\n== %s  (%s)" % (s.instance_name or s.tag, s.role))
        print("   ServiceInterfaceId %s   ServiceInstanceId %s   v%d.%d"
              % (s.interface_id, s.instance_id, s.major_version, s.minor_version))
        print("   local  %s %s  udp %d   sd %d"
              % (s.local.zone, s.local.ipv4, s.udp_port, s.sd_udp_port))
        if not s.is_provider:
            print("   remote %s %s  udp %d" % (s.remote.zone, s.remote.ipv4, s.remote_udp_port))
        for g in s.event_groups:
            print("   group  %-22s id %s -> %s %s:%d"
                  % (g.name, g.group_id, g.dest_zone, g.dest_ipv4, g.dest_udp_port))
        for e in s.events:
            hid = (parse_int(s.interface_id) << 16) | parse_int(e.event_id)
            print("   event  %-22s %s  payload %3d  pdu %3d  header 0x%08X  %s"
                  % (e.name, e.event_id, e.payload_length, e.pdu_length(), hid, e.serializer))
        for st in s.structs:
            print("   struct %-24s %d byte(s)" % (st.name, s.struct_size(st.name)))
            for m in st.members:
                print("          %-26s %s" % (m.name, m.type))
        for en in s.enums:
            print("   enum   %-24s %s" % (en.name, en.base_type))
            for lit in en.literals:
                print("          0x%-4X %-26s %s" % (lit.value, lit.name, lit.vt))


def print_log(log) -> None:
    if not log:
        return
    print("Adjustments (the workbook could not express these):")
    for line in log:
        print("  " + line)
    print()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    b = sp.add_parser("build", help="generate the ARXML")
    b.add_argument("inputs", nargs="+", help=".xlsx / .arxml / .json")
    b.add_argument("-o", "--output", required=True)
    b.add_argument("--base", help="project the workbooks are imported on top of")
    b.add_argument("--template", help="template file (default: the project's own setting)")
    b.add_argument("--json", help="also write the project model as JSON")
    b.add_argument("--force", action="store_true", help="generate even with validation errors")

    c = sp.add_parser("check", help="validate only")
    c.add_argument("inputs", nargs="+")
    c.add_argument("--base")
    c.add_argument("-v", "--verbose", action="store_true")

    s = sp.add_parser("show", help="print the configuration")
    s.add_argument("inputs", nargs="+")
    s.add_argument("--base")

    sp.add_parser("templates", help="list the available ARXML templates")

    args = ap.parse_args(argv)

    if args.cmd == "templates":
        for path in arxml_gen.available_templates():
            print(os.path.basename(path), " ", path)
        return 0

    prj, log = load(args.inputs, getattr(args, "base", None))

    if args.cmd == "show":
        print_log(log)
        show(prj)
        return 0
    if args.cmd == "check":
        print_log(log)
        return 1 if report(prj, args.verbose) else 0

    print_log(log)
    errors = report(prj)
    if errors and not args.force:
        print("\nAborted - fix the errors above or pass --force.")
        return 1
    try:
        arxml_gen.write(prj, args.output, args.template or prj.template)
        print("\nWritten", args.output)
        if args.json:
            prj.to_json(args.json)
            print("Written", args.json)
    except licensing.LicenseError as exc:
        # show and check need no licence, so this is the only place it bites
        print("\n%s" % exc, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

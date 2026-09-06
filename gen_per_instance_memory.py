#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_per_instance_memory.py
--------------------------
Doc file ARXML, tim cac IMPLEMENTATION-DATA-TYPE trong package DataTypes
va sinh ra block <AR-TYPED-PER-INSTANCE-MEMORYS> chua cac VARIABLE-DATA-PROTOTYPE
tuong ung (per-instance memory).

Chi dung thu vien chuan cua Python (>= 3.7), khong can cai dat gi them.

Vi du:
    python gen_per_instance_memory.py DataTypes.arxml
    python gen_per_instance_memory.py DataTypes.arxml -o pim.arxml
    python gen_per_instance_memory.py *.arxml --category ALL --strip-suffix Struct Type
    python gen_per_instance_memory.py DataTypes.arxml --package /DataTypes --no-uuid
"""

import argparse
import glob
import sys
import uuid
import xml.etree.ElementTree as ET


# --------------------------------------------------------------------------- #
# Helper: lam viec voi tag co namespace (http://autosar.org/schema/r4.0)
# --------------------------------------------------------------------------- #
def localname(tag):
    """Bo namespace khoi tag: '{ns}SHORT-NAME' -> 'SHORT-NAME'."""
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def find_child(elem, name):
    """Tim con truc tiep dau tien co ten (khong ke namespace)."""
    for child in elem:
        if localname(child.tag) == name:
            return child
    return None


def find_desc(elem, name):
    """Tim phan tu con cháu dau tien co ten (khong ke namespace)."""
    for node in elem.iter():
        if localname(node.tag) == name:
            return node
    return None


def get_short_name(elem):
    node = find_child(elem, 'SHORT-NAME')
    if node is not None and node.text:
        return node.text.strip()
    return None


def get_text(elem, name, default=None):
    node = find_child(elem, name)
    if node is not None and node.text:
        return node.text.strip()
    return default


# --------------------------------------------------------------------------- #
# Duyet cay AR-PACKAGE de lay tat ca IMPLEMENTATION-DATA-TYPE + duong dan AR
# --------------------------------------------------------------------------- #
def collect_impl_data_types(root):
    """
    Tra ve list (ar_path, element) voi ar_path la duong dan AUTOSAR day du,
    vi du '/DataTypes/ACUCrashInfoStruct'.
    """
    found = []

    def walk_package(pkg, parent_path):
        name = get_short_name(pkg) or ''
        pkg_path = '{}/{}'.format(parent_path, name)

        elements = find_child(pkg, 'ELEMENTS')
        if elements is not None:
            for el in elements:
                if localname(el.tag) == 'IMPLEMENTATION-DATA-TYPE':
                    el_name = get_short_name(el)
                    if el_name:
                        found.append(('{}/{}'.format(pkg_path, el_name), el))

        sub = find_child(pkg, 'AR-PACKAGES')
        if sub is not None:
            for child in sub:
                if localname(child.tag) == 'AR-PACKAGE':
                    walk_package(child, pkg_path)

    root_local = localname(root.tag)
    if root_local == 'AR-PACKAGE':
        # File fragment: root chinh la mot AR-PACKAGE
        walk_package(root, '')
    else:
        # File AUTOSAR day du
        packages = find_child(root, 'AR-PACKAGES')
        if packages is None:
            packages = find_desc(root, 'AR-PACKAGES')
        if packages is not None:
            for child in packages:
                if localname(child.tag) == 'AR-PACKAGE':
                    walk_package(child, '')

    return found


def get_calibration_access(dtype_elem):
    """
    Lay SW-CALIBRATION-ACCESS o muc SW-DATA-DEF-PROPS CUA CHINH data type
    (khong lay cua cac SUB-ELEMENTS).
    """
    props = find_child(dtype_elem, 'SW-DATA-DEF-PROPS')
    if props is None:
        return None
    node = find_desc(props, 'SW-CALIBRATION-ACCESS')
    if node is not None and node.text:
        return node.text.strip()
    return None


# --------------------------------------------------------------------------- #
# Sinh XML
# --------------------------------------------------------------------------- #
def make_instance_name(short_name, strip_suffixes, prefix='', suffix=''):
    name = short_name
    for suf in strip_suffixes:
        if suf and name.endswith(suf) and len(name) > len(suf):
            name = name[:-len(suf)]
            break
    return '{}{}{}'.format(prefix, name, suffix)


def build_variable_data_prototype(inst_name, type_path, calib_access,
                                  uuid_str, indent, step='  '):
    i = indent
    lines = []
    attr = ' UUID="{}"'.format(uuid_str) if uuid_str else ''
    lines.append('{}<VARIABLE-DATA-PROTOTYPE{}>'.format(i, attr))
    lines.append('{}{}<SHORT-NAME>{}</SHORT-NAME>'.format(i, step, inst_name))
    if calib_access:
        lines.append('{}{}<SW-DATA-DEF-PROPS>'.format(i, step))
        lines.append('{}{}<SW-DATA-DEF-PROPS-VARIANTS>'.format(i, step * 2))
        lines.append('{}{}<SW-DATA-DEF-PROPS-CONDITIONAL>'.format(i, step * 3))
        lines.append('{}{}<SW-CALIBRATION-ACCESS>{}</SW-CALIBRATION-ACCESS>'
                     .format(i, step * 4, calib_access))
        lines.append('{}{}</SW-DATA-DEF-PROPS-CONDITIONAL>'.format(i, step * 3))
        lines.append('{}{}</SW-DATA-DEF-PROPS-VARIANTS>'.format(i, step * 2))
        lines.append('{}{}</SW-DATA-DEF-PROPS>'.format(i, step))
    lines.append('{}{}<TYPE-TREF DEST="IMPLEMENTATION-DATA-TYPE">{}</TYPE-TREF>'
                 .format(i, step, type_path))
    lines.append('{}</VARIABLE-DATA-PROTOTYPE>'.format(i))
    return '\n'.join(lines)


def new_uuid():
    return str(uuid.uuid4()).upper()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def process_file(path, args):
    """Tra ve list cac chuoi VARIABLE-DATA-PROTOTYPE sinh ra tu 1 file."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        sys.stderr.write('[LOI] Khong parse duoc "{}": {}\n'.format(path, exc))
        sys.stderr.write('      (File ARXML phai day du va dong the dung cach.)\n')
        return []

    root = tree.getroot()
    dtypes = collect_impl_data_types(root)

    inner_indent = ' ' * (args.indent + args.indent_step)
    step = ' ' * args.indent_step

    blocks = []
    for ar_path, elem in dtypes:
        short_name = get_short_name(elem)
        category = get_text(elem, 'CATEGORY', '')

        # Loc theo package
        if args.package and not ar_path.startswith(args.package.rstrip('/') + '/'):
            continue
        # Loc theo category
        if args.category.upper() != 'ALL' and category.upper() != args.category.upper():
            continue
        # Loc theo ten (neu co --only)
        if args.only and short_name not in args.only:
            continue

        inst_name = make_instance_name(short_name, args.strip_suffix,
                                       args.prefix, args.suffix)
        calib = get_calibration_access(elem)
        if args.calibration_access:
            calib = args.calibration_access
        uid = '' if args.no_uuid else new_uuid()

        blocks.append(build_variable_data_prototype(
            inst_name, ar_path, calib, uid, inner_indent, step))

        sys.stderr.write('  + {:<32} -> {}\n'.format(short_name, inst_name))

    return blocks


def main():
    parser = argparse.ArgumentParser(
        description='Sinh AR-TYPED-PER-INSTANCE-MEMORYS tu package DataTypes trong ARXML.')
    parser.add_argument('inputs', nargs='+',
                        help='File ARXML dau vao (co the dung wildcard).')
    parser.add_argument('-o', '--output',
                        help='File ket qua. Mac dinh in ra man hinh (stdout).')
    parser.add_argument('--package', default='',
                        help='Chi lay data type trong package nay, vd /DataTypes. '
                             'Mac dinh: lay tat ca.')
    parser.add_argument('--category', default='STRUCTURE',
                        help='Loc theo CATEGORY (STRUCTURE, VALUE, ARRAY, ... hoac ALL). '
                             'Mac dinh: STRUCTURE.')
    parser.add_argument('--only', nargs='*', default=None,
                        help='Chi sinh cho cac SHORT-NAME duoc liet ke.')
    parser.add_argument('--strip-suffix', nargs='*', default=['Struct'],
                        help='Hau to can bo khoi ten khi dat ten instance. '
                             'Mac dinh: Struct. Dung "--strip-suffix" rong de giu nguyen ten.')
    parser.add_argument('--prefix', default='', help='Tien to them vao ten instance.')
    parser.add_argument('--suffix', default='', help='Hau to them vao ten instance.')
    parser.add_argument('--calibration-access', default=None,
                        help='Ep SW-CALIBRATION-ACCESS (vd READ-ONLY). '
                             'Mac dinh: lay theo data type goc.')
    parser.add_argument('--no-uuid', action='store_true',
                        help='Khong sinh thuoc tinh UUID.')
    parser.add_argument('--no-wrapper', action='store_true',
                        help='Khong bao boi the <AR-TYPED-PER-INSTANCE-MEMORYS>.')
    parser.add_argument('--indent', type=int, default=14,
                        help='So khoang trang thut le cua the wrapper. Mac dinh: 14.')
    parser.add_argument('--indent-step', type=int, default=2,
                        help='So khoang trang cho moi cap long nhau. Mac dinh: 2.')
    args = parser.parse_args()

    files = []
    for pattern in args.inputs:
        matched = glob.glob(pattern)
        files.extend(matched if matched else [pattern])

    all_blocks = []
    for path in files:
        sys.stderr.write('[FILE] {}\n'.format(path))
        all_blocks.extend(process_file(path, args))

    if not all_blocks:
        sys.stderr.write('[CANH BAO] Khong tim thay data type nao phu hop.\n')

    if args.no_wrapper:
        result = '\n'.join(all_blocks)
    else:
        pad = ' ' * args.indent
        result = '{0}<AR-TYPED-PER-INSTANCE-MEMORYS>\n{1}\n{0}</AR-TYPED-PER-INSTANCE-MEMORYS>'.format(
            pad, '\n'.join(all_blocks))

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as fh:
            fh.write(result + '\n')
        sys.stderr.write('[OK] Da ghi {} prototype vao "{}"\n'
                         .format(len(all_blocks), args.output))
    else:
        print(result)


if __name__ == '__main__':
    main()

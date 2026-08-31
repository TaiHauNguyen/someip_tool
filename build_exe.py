"""Package the tool as Windows executables that need no Python installed.

    python build_exe.py                # both exes, one file each
    python build_exe.py --onedir       # a folder per exe: starts faster
    python build_exe.py --gui          # only the window
    python build_exe.py --clean        # throw away build/ and dist/ first

Two programs come out of it, because they want different consoles:

    dist/SomeIpTool.exe   the window, with no console behind it
    dist/someip-cli.exe   the batch front end, which needs one

`templates/` is bundled inside each exe, and is also copied next to them so a
variant can be dropped in without a rebuild - arxml_gen looks beside the
executable before it looks inside.

The result is one folder to hand over.  It runs on any 64-bit Windows of the
same or newer version than the machine that built it; it is not portable to
another OS, and building on Windows 10 for Windows 10 is the safe choice.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist")
BUILD = os.path.join(HERE, "build")

# (exe name, entry script, windowed)  - the GUI gets no console, the CLI needs one
TARGETS = [
    ("SomeIpTool", "gui.py", True),
    ("someip-cli", "someip_cli.py", False),
]

# openpyxl is the only third-party import; everything else the tool uses is
# stdlib.  PyInstaller finds it on its own, but a missing one must stop the
# build rather than produce an exe that dies on the first Import Excel.
REQUIRED = ["openpyxl"]


def fail(msg: str) -> None:
    print("\n[build] " + msg)
    sys.exit(1)


def ensure(module: str, package: str = "") -> None:
    """Import it, installing it once if that is what is missing."""
    package = package or module
    try:
        __import__(module)
        return
    except ImportError:
        pass
    print("[build] %s is missing - installing it" % package)
    rc = subprocess.call([sys.executable, "-m", "pip", "install", package])
    if rc != 0:
        fail("could not install %s.  Install it by hand and run this again:\n"
             "        python -m pip install %s" % (package, package))
    try:
        __import__(module)
    except ImportError:
        fail("%s installed but still will not import." % package)


def check_not_running(name: str, onefile: bool) -> None:
    """An executable that is still open cannot be replaced, and PyInstaller
    reports only "Access is denied" about it."""
    target = (os.path.join(DIST, name + ".exe") if onefile
              else os.path.join(DIST, name, name + ".exe"))
    if not os.path.exists(target):
        return
    try:
        # Windows locks a running image against writing - but not against
        # renaming it, so opening for write is the probe that tells the truth
        open(target, "r+b").close()
    except OSError:
        fail("%s.exe is still running, so it cannot be replaced.\n"
             "        Close its window, or run:  taskkill /IM %s.exe /F"
             % (name, name))


def run(cmd: list) -> None:
    print("[build] " + " ".join(cmd[1:]))
    if subprocess.call(cmd) != 0:
        fail("PyInstaller failed - the output above says why.\n"
             '        "Access is denied" on an .exe means it is still running:\n'
             "        close it and build again.")


def build(name: str, entry: str, windowed: bool, onefile: bool) -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile" if onefile else "--onedir",
        "--name", name,
        "--distpath", DIST,
        "--workpath", BUILD,
        "--specpath", BUILD,
        # the templates travel inside the exe; ';' is the Windows separator
        "--add-data", "%s%s%s" % (os.path.join(HERE, "templates"), os.pathsep, "templates"),
        "--hidden-import", "openpyxl",
        # nothing here draws plots or crunches arrays; leaving these out keeps
        # the exe from swelling if they happen to be installed
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--exclude-module", "matplotlib",
        "--exclude-module", "PIL",
        "--exclude-module", "lxml",
    ]
    if windowed:
        cmd.append("--windowed")
    cmd.append(os.path.join(HERE, entry))
    run(cmd)


def copy_templates() -> None:
    """Also leave the templates loose, so one can be edited without a rebuild."""
    dst = os.path.join(DIST, "templates")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(os.path.join(HERE, "templates"), dst)
    print("[build] copied templates/ next to the executables")


def write_readme() -> None:
    text = """SOME/IP Config Tool
===================

Nothing to install - Python is already inside the executable.

    SomeIpTool.exe     the window
    someip-cli.exe     the command line, for batch use

Command line examples (open cmd in this folder):

    someip-cli.exe build PCU_Provider.xlsx RMCU_Consumer.xlsx -o ZA_someip.arxml
    someip-cli.exe check ZA_someip.arxml
    someip-cli.exe show  ZA_someip.arxml
    someip-cli.exe templates

templates/
    The shape of the generated ARXML.  A copy also lives inside the exe; the
    one in this folder wins, so it can be edited without rebuilding.  Delete
    the folder and the built-in copy is used again.

Requires 64-bit Windows.  If SmartScreen blocks the first run, choose
"More info" then "Run anyway" - the executable is unsigned.
"""
    with open(os.path.join(DIST, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onedir", action="store_true",
                    help="a folder per exe instead of a single file (starts faster)")
    ap.add_argument("--gui", action="store_true", help="build only the window")
    ap.add_argument("--cli", action="store_true", help="build only the command line")
    ap.add_argument("--clean", action="store_true", help="delete build/ and dist/ first")
    args = ap.parse_args(argv)

    needed = [e for _, e, _ in TARGETS] + [os.path.join("templates", "someip.arxml.tpl")]
    missing = [f for f in needed if not os.path.exists(os.path.join(HERE, f))]
    if missing:
        fail("not found next to build_exe.py: %s\n"
             "        Run this from inside the someip_tool folder itself."
             % ", ".join(missing))

    if sys.maxsize <= 2 ** 32:
        print("[build] warning: this is 32-bit Python, so the exe will be 32-bit too")

    for mod in REQUIRED:
        ensure(mod)
    ensure("PyInstaller", "pyinstaller")

    if args.clean:
        for d in (BUILD, DIST):
            if not os.path.isdir(d):
                continue
            try:
                shutil.rmtree(d)
            except OSError as exc:
                fail("cannot delete %s: %s\n"
                     "        Something inside it is open - close SomeIpTool.exe\n"
                     "        and any Explorer window showing that folder."
                     % (os.path.relpath(d, HERE), exc))
            print("[build] removed %s" % os.path.relpath(d, HERE))

    wanted = TARGETS
    if args.gui:
        wanted = [t for t in TARGETS if t[1] == "gui.py"]
    elif args.cli:
        wanted = [t for t in TARGETS if t[1] == "someip_cli.py"]

    for name, entry, windowed in wanted:
        print("\n[build] === %s (%s) ===" % (name, entry))
        check_not_running(name, onefile=not args.onedir)
        build(name, entry, windowed, onefile=not args.onedir)

    copy_templates()
    write_readme()

    print("\n[build] done.  Hand over this folder:\n    %s" % DIST)
    for f in sorted(os.listdir(DIST)):
        p = os.path.join(DIST, f)
        size = "" if os.path.isdir(p) else "  %.1f MB" % (os.path.getsize(p) / 1e6)
        print("    %s%s" % (f + ("/" if os.path.isdir(p) else ""), size))
    return 0


if __name__ == "__main__":
    sys.exit(main())

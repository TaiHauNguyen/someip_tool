# SOME/IP Config Tool (Template)

Turns the customer SOME/IP workbooks into the DaVinci Classic import ARXML, and
lets you review and edit every configuration item in between.

```
PCU_Provider.xlsx  ─┐
RMCU_Consumer.xlsx ─┼─► model ─► template ─► ZA_someip.arxml
ZA_someip.arxml    ─┤   (GUI)
*.someip.json      ─┘
```

The workbooks are the input, the model is what you edit, and
`templates/someip.arxml.tpl` decides what the XML looks like.  No project
specific value and no AUTOSAR element is hard coded in Python - see section 7
of `MAPPING.md`.

## Install

Python 3.9+ and one package:

```
python -m pip install openpyxl
```

Tkinter ships with the standard Windows Python installer.

## Run the GUI

```
someip_tool\run_gui.bat
```

or

```
python someip_tool\gui.py ZA_someip.someip.json
```

| Tab | What it shows |
|---|---|
| **Project** | ECU, cluster, channel, VLAN, multicast, generation options |
| **Services** | one panel per service: ids, versions, local/remote endpoints, SD timing, TSN |
| **Events** | every event with its computed PDU length and header id |
| **Event Groups** | group ids and destinations |
| **Data Types** | struct tree with computed byte sizes, and the enums with their `<VT>` texts |
| **Check** | validation results (errors, warnings, info) |
| **ARXML Preview** | the file that *Generate ARXML* would write |

Everything in the tables is editable: double click a row, or use the
Add / Edit / Delete buttons.

Typical flow:

1. **Import Excel** – pick both workbooks at once.
2. Fix what the workbook cannot express (a consumer's remote provider endpoint,
   any name you want to keep from the previous ARXML).
3. **Validate** – the Check tab must be free of errors.
4. **Save JSON** – this is your editable database, keep it in the repo.
5. **Generate ARXML** – import the result in DaVinci Classic.

## Command line

```
python someip_tool\someip_cli.py build PCU_Provider.xlsx RMCU_Consumer.xlsx ^
        -o ZA_someip.arxml --json ZA_someip.someip.json
python someip_tool\someip_cli.py show  ZA_someip.arxml
python someip_tool\someip_cli.py check PCU_Provider.xlsx RMCU_Consumer.xlsx
```

`build` refuses to write when validation reports an error; pass `--force` to
override.  `--base` names the project the workbooks are imported on top of,
`--template` picks a different ARXML template, and `someip_cli.py templates`
lists the ones that are installed.

## Changing the generated ARXML

Edit `templates/someip.arxml.tpl`.  It is ordinary XML with a few directives:
`${expr}` substitutes a value, `t-foreach="events as ev"` repeats an element,
`t-if` drops one, `t-def`/`t-call` define and expand a reusable fragment.
Copy it to a second `.tpl` for a project variant and select it with the *ARXML
template* field on the Project tab, or `--template` on the CLI.

## Scope

Handles: any number of services and workbooks, provider and consumer roles,
several events per group, several event groups per service **including groups
that go to different ECUs**, nested structs, enums, and both DataStructures
sheet layouts.

Not handled yet - the validator reports an error rather than writing a wrong
file: **TCP transport** (only `UDP-TP` sockets are generated) and SOME/IP
**methods / fields** (the workbook format only describes events).
`StaticMulticast` sets `ACTIVATION-MULTICAST` but does not build a multicast
event socket.

## Files

| File | Purpose |
|---|---|
| `someip_model.py` | the data model - the single source of truth |
| `excel_io.py` | reads the customer workbooks |
| `naming.py` | short name and topology derivation rules |
| `view_model.py` | flattens the model into the template context |
| `template_engine.py` | the `t-foreach` / `t-if` / `${}` XML templating |
| `templates/*.arxml.tpl` | **the ARXML structure** - edit this to change the output |
| `arxml_gen.py` | glues view model + template together |
| `resolve.py` | nearest-declaration and carry-over rules |
| `arxml_io.py` | ARXML → model (open an existing file) |
| `validate.py` | consistency checks |
| `gui.py` | the Tkinter application |
| `someip_cli.py` | batch front end |
| `bootstrap_Template.py` | workbooks + existing ARXML → `*.someip.json` + ARXML |
| `MAPPING.md` | **the Excel → ARXML rules**, field by field |

## Regenerating the Template project from scratch

```
python someip_tool\bootstrap_Template.py
```

Picks up every workbook in the project directory, uses `ZA_someip.arxml` (or a
base you pass as the first argument) for what the workbooks cannot express, and
writes `ZA_someip.someip.json` + `ZA_someip.generated.arxml`.  Every adjustment
it makes is printed.

## Building an executable for a machine without Python

```
build.bat                 # or: python build_exe.py
build.bat --onedir        # a folder per exe instead of one file - starts faster
build.bat --clean         # discard the previous build first
```

Everything lands in `dist/`, and that whole folder is what you hand over:

| | |
|---|---|
| `SomeIpTool.exe` | the window, no console behind it |
| `someip-cli.exe` | the batch front end |
| `templates/` | a loose copy of the ARXML templates |
| `README.txt` | how to run it, for whoever receives the folder |

The templates are bundled inside each exe as well.  `arxml_gen` looks beside the
executable first, so a variant dropped into `dist/templates/` is used without a
rebuild; delete the folder and the built-in copy takes over again.

PyInstaller and `openpyxl` are installed by the script if they are missing.  The
result runs on 64-bit Windows of the same or a newer version than the machine
that built it - build on the oldest Windows you need to support.  The exe is
unsigned, so SmartScreen may ask for **More info → Run anyway** the first time.

## Licensing

Importing workbooks, opening ARXML or JSON, editing and validating need no
licence.  **Generating ARXML and saving the project JSON do.**  The window shows
`[UNLICENSED]` in its title and greys those two out; the CLI refuses `build`
with exit code 3 while `show`, `check` and `templates` keep working.

A licence names one machine by MAC address and one expiry instant, to the
minute, and is signed.  The customer build carries only the public half of the
key, so it can recognise a genuine licence but cannot mint one.

### Issuing (vendor side)

```
python license_tool.py --keygen                    once, ever
python license_tool.py                             the window
python license_tool.py --mac AA-BB-CC-DD-EE-FF        --until "2026-12-31 17:30" --to "Team X" -o license.key
python build_exe.py --license-tool                 build the issuer itself
```

`--keygen` writes two files:

| | |
|---|---|
| `license_private.json` | signs licences. **Committed to this repository by a deliberate decision** - see the note below. |
| `license_pubkey.py` | committed, and compiled into the customer build. |

Regenerating the key invalidates every licence already issued and needs the
customer tool rebuilt, so do it once.

The issuer executable reads `license_private.json` from its own folder, so keep
the two together and keep both off customer machines.

### Receiving (customer side)

*Help > This machine's address...* gives the MAC to send.  *Help > Install
licence...* takes the file that comes back and stores it under
`%APPDATA%\SomeIpTool\`.  A `license.key` beside the executable works too, and
`SOMEIP_LICENSE` overrides both.

A licence is looked for in three places, nearest first:

1. the path in `SOMEIP_LICENSE`
2. `license.key` beside the program
3. `license.key` under `%APPDATA%\SomeIpTool\`

**The first of these that exists decides**, whether or not it is any good.  It
does not fall through to the next one when a file is broken or expired: a copy
installed months ago would otherwise silently overrule the one you just put
beside the program, and editing that file would appear to do nothing.  *Help >
Licence status...* lists every copy found and marks the one in force, and *Help
> Remove installed licence...* deletes the one under `%APPDATA%`.

Expiry is entered in the issuer's local time and stored as UTC, so it means the
same instant on a machine in another timezone.

### What this does and does not stop

The signing key is committed here, and this repository is public.  That was a
deliberate choice, and it has a consequence worth stating plainly: anyone who
reads the repository can issue a licence for any machine and any date, so the
check stops accidents and honest mistakes rather than determined copying.  Treat
it as a reminder of the terms, not as a lock.

Making it a lock again takes three steps: make the repository private or drop
the key from it, run `license_tool.py --keygen` to mint a key nobody has seen,
and rebuild the customer executables so they carry the new public half.  Every
licence issued under the old key stops working at that point.

Independently of the key, the check is not tamper-proof against someone who
edits the program itself - no client-side check can be.  Nor does it survive a
MAC address being changed by hand, and a network card swap needs a new licence.

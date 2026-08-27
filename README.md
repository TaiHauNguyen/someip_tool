# SOME/IP Config Tool (ZAFL)

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
| `bootstrap_zafl.py` | workbooks + existing ARXML → `*.someip.json` + ARXML |
| `MAPPING.md` | **the Excel → ARXML rules**, field by field |

## Regenerating the ZAFL project from scratch

```
python someip_tool\bootstrap_zafl.py
```

Picks up every workbook in the project directory, uses `ZA_someip.arxml` (or a
base you pass as the first argument) for what the workbooks cannot express, and
writes `ZA_someip.someip.json` + `ZA_someip.generated.arxml`.  Every adjustment
it makes is printed.

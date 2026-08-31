"""Issue licences for the SOME/IP Config Tool.  Vendor side - do not ship.

    python license_tool.py                       the window
    python license_tool.py --keygen              create the signing key, once
    python license_tool.py --mac AA-BB-CC-DD-EE-FF --until "2026-12-31 17:30" \\
                           --to "Team ZAFL" -o license.key

The signing key is written to license_private.json and must never leave this
machine or enter the repository: whoever holds it can issue licences.  Its
public half is written to license_pubkey.py, which *is* committed and is what
the customer's build checks against - so regenerating the key invalidates every
licence already issued.

Expiry is entered in this machine's local time, to the minute, and stored as
UTC so it means the same instant on the customer's machine.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import licensing
import theme

HERE = os.path.dirname(os.path.abspath(__file__))
# frozen, __file__ points into the temporary unpack directory that is deleted on
# exit - the key has to be looked for beside the .exe instead
KEY_DIR = licensing.app_dir()
PRIVATE_PATH = os.path.join(KEY_DIR, "license_private.json")
PUBLIC_MODULE = os.path.join(KEY_DIR, "license_pubkey.py")
TITLE = "SOME/IP Tool - Licence Issuer"

_PUBLIC_TEMPLATE = '''"""The public half of the licence signing key - generated, do not edit.

`licensing.py` checks every licence against this.  Replacing it invalidates
every licence issued under the old key.  Written by license_tool.py --keygen.
"""

PUBLIC_KEY = %s
'''


# --------------------------------------------------------------------------
def write_keypair(bits: int = 2048) -> dict:
    """Create the signing key and put its halves where each belongs."""
    kp = licensing.generate_keypair(bits)
    with open(PRIVATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(kp["private"], fh, indent=2)
    with open(PUBLIC_MODULE, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_PUBLIC_TEMPLATE % json.dumps(kp["public"], indent=4))
    if getattr(sys, "frozen", False):
        print("copy %s into the source tree and rebuild the customer tool, or "
              "the new key means nothing to it" % PUBLIC_MODULE)
    return kp


def load_private(path: str = PRIVATE_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        key = json.load(fh)
    if "d" not in key or "n" not in key:
        raise ValueError("%s is not a private key" % os.path.basename(path))
    return key


def parse_until(text: str) -> datetime.datetime:
    """'2026-12-31 17:30' in local time -> an aware datetime."""
    text = (text or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            when = datetime.datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError("expected YYYY-MM-DD HH:MM, got %r" % text)
    if fmt == "%Y-%m-%d":                       # a bare date means end of that day
        when = when.replace(hour=23, minute=59)
    return when.replace(second=0, microsecond=0).astimezone()


# --------------------------------------------------------------------------
class IssuerWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE)
        self.geometry("880x680")
        self.theme_mode = tk.StringVar(value="light")
        self.pal = theme.apply(self, "light")

        self.key: dict | None = None
        self.mac = tk.StringVar()
        self.to = tk.StringVar()
        self.note = tk.StringVar()
        self.date = tk.StringVar()
        self.time = tk.StringVar(value="23:59")
        self.keyinfo = tk.StringVar()

        self._build()
        self._preset_days(30)
        self._load_key_quietly()

    # -- layout ---------------------------------------------------------
    def _build(self) -> None:
        bar = ttk.Frame(self, style="Toolbar.TFrame", padding=(10, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="Load signing key...",
                   command=self.load_key).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Generate new key pair...",
                   command=self.new_key).pack(side="left")
        ttk.Label(bar, textvariable=self.keyinfo,
                  style="Toolbar.TLabel").pack(side="right")

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        row = 0

        ttk.Label(body, text="Machine", style="Section.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 4)); row += 1

        ttk.Label(body, text="MAC address").grid(row=row, column=0, sticky="w", padx=(0, 8))
        mac_row = ttk.Frame(body)
        mac_row.grid(row=row, column=1, sticky="ew", pady=3)
        mac_row.columnconfigure(0, weight=1)
        ttk.Entry(mac_row, textvariable=self.mac).grid(row=0, column=0, sticky="ew")
        ttk.Button(mac_row, text="This machine", command=self.fill_local_mac).grid(
            row=0, column=1, padx=(6, 0))
        row += 1

        ttk.Label(body, text="Licensed to").grid(row=row, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(body, textvariable=self.to).grid(row=row, column=1, sticky="ew", pady=3)
        row += 1
        ttk.Label(body, text="Note").grid(row=row, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(body, textvariable=self.note).grid(row=row, column=1, sticky="ew", pady=3)
        row += 1

        ttk.Label(body, text="Valid until", style="Section.TLabel").grid(
            row=row, column=0, sticky="w", pady=(14, 4)); row += 1

        when = ttk.Frame(body)
        when.grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Label(body, text="Date and time").grid(row=row, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(when, textvariable=self.date, width=14).pack(side="left")
        ttk.Label(when, text=" at ").pack(side="left")
        ttk.Entry(when, textvariable=self.time, width=8).pack(side="left")
        ttk.Label(when, text="  (YYYY-MM-DD  HH:MM, local time)",
                  style="Muted.TLabel").pack(side="left")
        row += 1

        quick = ttk.Frame(body)
        quick.grid(row=row, column=1, sticky="w", pady=(2, 0))
        for label, days in (("+7 days", 7), ("+30 days", 30), ("+90 days", 90),
                            ("+180 days", 180), ("+1 year", 365)):
            ttk.Button(quick, text=label, width=10,
                       command=lambda d=days: self._preset_days(d)).pack(side="left", padx=(0, 4))
        row += 1

        self.preview_when = ttk.Label(body, text="", style="Muted.TLabel")
        self.preview_when.grid(row=row, column=1, sticky="w", pady=(6, 0)); row += 1
        for var in (self.date, self.time):
            var.trace_add("write", lambda *_: self._show_when())

        act = ttk.Frame(body)
        act.grid(row=row, column=0, columnspan=2, sticky="w", pady=(16, 8))
        ttk.Button(act, text="Issue licence", style="Accent.TButton",
                   command=self.issue).pack(side="left")
        ttk.Button(act, text="Save to file...", command=self.save).pack(side="left", padx=6)
        ttk.Button(act, text="Copy", command=self.copy).pack(side="left")
        ttk.Button(act, text="Check a licence...", command=self.check).pack(side="left", padx=6)
        row += 1

        body.rowconfigure(row, weight=1)
        self.out = tk.Text(body, height=12, wrap="none")
        self.out.grid(row=row, column=0, columnspan=2, sticky="nsew")
        theme.style_text(self.out, self.pal)

        self.status = tk.StringVar(value="Load or generate a signing key to start.")
        ttk.Label(self, textvariable=self.status, anchor="w",
                  style="Status.TLabel").pack(fill="x", side="bottom")

    # -- key ------------------------------------------------------------
    def _load_key_quietly(self) -> None:
        if os.path.isfile(PRIVATE_PATH):
            try:
                self.key = load_private()
                self.keyinfo.set("signing key: %s (%d bit)"
                                 % (os.path.basename(PRIVATE_PATH),
                                    self.key.get("bits", 2048)))
                self.status.set("Ready.")
                return
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self.status.set("Cannot use %s: %s" % (PRIVATE_PATH, exc))
        self.keyinfo.set("no signing key loaded")

    def load_key(self) -> None:
        path = filedialog.askopenfilename(title="Signing key",
                                          filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            self.key = load_private(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror(TITLE, str(exc))
            return
        self.keyinfo.set("signing key: %s" % os.path.basename(path))
        self.status.set("Loaded %s" % path)

    def new_key(self) -> None:
        if os.path.isfile(PRIVATE_PATH) and not messagebox.askyesno(
                TITLE,
                "A signing key already exists.\n\nReplacing it will make every "
                "licence already issued stop working, and the customer builds "
                "must be rebuilt with the new public key.\n\nReplace it?"):
            return
        self.status.set("Generating a 2048-bit key, this takes a moment...")
        self.update_idletasks()
        try:
            self.key = write_keypair()["private"]
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(TITLE, "Key generation failed:\n%s" % exc)
            return
        self._load_key_quietly()
        messagebox.showinfo(
            TITLE,
            "Written:\n  %s   keep this secret, back it up\n  %s   commit this, "
            "then rebuild the tool" % (PRIVATE_PATH, PUBLIC_MODULE))

    # -- form -----------------------------------------------------------
    def fill_local_mac(self) -> None:
        macs = licensing.machine_macs()
        if not macs:
            messagebox.showwarning(TITLE, "No MAC address could be read here.")
            return
        self.mac.set(macs[0])
        if len(macs) > 1:
            self.status.set("This machine also has: " + ", ".join(macs[1:]))

    def _preset_days(self, days: int) -> None:
        when = datetime.datetime.now().astimezone() + datetime.timedelta(days=days)
        self.date.set(when.strftime("%Y-%m-%d"))
        self.time.set("23:59")

    def _when(self) -> datetime.datetime:
        return parse_until("%s %s" % (self.date.get().strip(), self.time.get().strip()))

    def _show_when(self) -> None:
        try:
            when = self._when()
        except ValueError as exc:
            self.preview_when.configure(text=str(exc))
            return
        utc = when.astimezone(datetime.timezone.utc)
        left = when - datetime.datetime.now().astimezone()
        mins = int(left.total_seconds() // 60)
        human = ("expired" if mins < 0 else
                 "%d day(s) %d hour(s) %d minute(s) from now"
                 % (mins // 1440, mins % 1440 // 60, mins % 60))
        self.preview_when.configure(
            text="stored as %s UTC  -  %s" % (utc.strftime(licensing.MINUTE), human))

    # -- actions --------------------------------------------------------
    def issue(self) -> None:
        if not self.key:
            messagebox.showerror(TITLE, "Load or generate a signing key first.")
            return
        try:
            mac = licensing.normalise_mac(self.mac.get())
            when = self._when()
        except ValueError as exc:
            messagebox.showerror(TITLE, str(exc))
            return
        if when <= datetime.datetime.now().astimezone() and not messagebox.askyesno(
                TITLE, "That moment has already passed, so the licence will be "
                       "dead on arrival.\n\nIssue it anyway?"):
            return
        token = licensing.issue(self.key, mac, when, self.to.get(), self.note.get())
        text = licensing.wrap(token, licensing.decode(token, self._public()))
        self.out.delete("1.0", "end")
        self.out.insert("1.0", text)
        self.status.set("Issued for %s until %s local time"
                        % (mac, when.strftime("%Y-%m-%d %H:%M")))

    def _public(self) -> dict:
        return {"n": self.key["n"], "e": self.key["e"]}

    def _text(self) -> str:
        return self.out.get("1.0", "end").strip()

    def save(self) -> None:
        text = self._text()
        if not text:
            messagebox.showinfo(TITLE, "Issue a licence first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save licence", defaultextension=".key",
            initialfile=licensing.LICENSE_FILENAME,
            filetypes=[("Licence", "*.key"), ("All files", "*.*")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        self.status.set("Saved %s" % path)

    def copy(self) -> None:
        text = self._text()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.set("Copied - paste it into a mail, or save it as license.key")

    def check(self) -> None:
        """Read back a licence file and say what it grants."""
        path = filedialog.askopenfilename(title="Licence to check",
                                          filetypes=[("Licence", "*.key"),
                                                     ("All files", "*.*")])
        if not path:
            return
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        try:
            payload = licensing.decode(licensing.unwrap(text),
                                       self._public() if self.key else None)
        except licensing.LicenseError as exc:
            messagebox.showerror(TITLE, "Not valid:\n\n%s" % exc)
            return
        st = licensing.Status(True, payload=payload)
        messagebox.showinfo(
            TITLE,
            "Signature is good.\n\nMachine : %s\nExpires : %s local "
            "(%s UTC)\nLicensed: %s\nNote    : %s"
            % (payload.get("mac", ""), st.expires_local, payload.get("exp", ""),
               payload.get("to", "-"), payload.get("note", "-")))


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Issue licences for the SOME/IP Config Tool.")
    ap.add_argument("--keygen", action="store_true", help="create the signing key pair")
    ap.add_argument("--mac", help="MAC address of the machine to license")
    ap.add_argument("--until", help='expiry in local time, "YYYY-MM-DD HH:MM"')
    ap.add_argument("--to", default="", help="who it is for")
    ap.add_argument("--note", default="")
    ap.add_argument("--key", default=PRIVATE_PATH, help="signing key file")
    ap.add_argument("-o", "--out", help="write the licence here instead of stdout")
    args = ap.parse_args(argv)

    if args.keygen:
        write_keypair()
        print("private key -> %s   (secret: never commit or send this)" % PRIVATE_PATH)
        print("public  key -> %s   (commit this, then rebuild the tool)" % PUBLIC_MODULE)
        return 0

    if args.mac or args.until:
        if not (args.mac and args.until):
            ap.error("--mac and --until go together")
        try:
            key = load_private(args.key)
            token = licensing.issue(key, args.mac, parse_until(args.until),
                                    args.to, args.note)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print("error: %s" % exc, file=sys.stderr)
            return 2
        text = licensing.wrap(token, licensing.decode(token, {"n": key["n"], "e": key["e"]}))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
            print("written %s" % args.out)
        else:
            print(text)
        return 0

    IssuerWindow().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

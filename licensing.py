"""Licence checking, and the crypto the issuing tool signs with.

A licence names one machine by MAC address and one expiry instant, and is
signed.  The tool that runs on the customer's machine carries only the *public*
key (`license_pubkey.py`), so it can tell a genuine licence from a forged one
but cannot produce one; only whoever holds the private key can issue.  A shared
secret would have been shorter, but it would sit inside the .exe that every
customer receives, and anyone who found it could issue licences.

    import licensing
    st = licensing.status()
    if st.valid: ...

The signature is RSA with PKCS#1 v1.5 padding over SHA-256, implemented here
because the standard library has no public-key crypto and the tool is meant to
run with nothing installed but openpyxl.

Times are stored as UTC to the minute, so a licence means the same instant
wherever it is read; the tools show local time.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

TOKEN_PREFIX = "SOMEIP1"
LICENSE_FILENAME = "license.key"
APP_DIR_NAME = "SomeIpTool"
MINUTE = "%Y-%m-%dT%H:%M"

# ASN.1 DigestInfo header for SHA-256, per PKCS#1 v1.5
_SHA256_DER = bytes.fromhex("3031300d060960864801650304020105000420")


class LicenseError(Exception):
    """Raised where output is produced without a valid licence."""


# --------------------------------------------------------------------------
# machine identity
# --------------------------------------------------------------------------
_MAC_RE = re.compile(r"\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
_BOGUS = {"00-00-00-00-00-00", "FF-FF-FF-FF-FF-FF"}


def normalise_mac(text: str) -> str:
    """Accept aa:bb:cc:dd:ee:ff, AA-BB-..., or twelve bare hex digits."""
    raw = re.sub(r"[^0-9A-Fa-f]", "", text or "")
    if len(raw) != 12:
        raise ValueError("a MAC address has 12 hex digits, this has %d" % len(raw))
    raw = raw.upper()
    return "-".join(raw[i:i + 2] for i in range(0, 12, 2))


def _quiet_run(cmd: List[str]) -> str:
    kwargs: Dict = {"capture_output": True, "text": True, "timeout": 15}
    if os.name == "nt":
        # without this a console window flashes up out of the windowed build
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, **kwargs).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def machine_macs() -> List[str]:
    """Every MAC this machine owns, so a second network card does not
    invalidate a licence issued against the first."""
    found = set()

    if os.name == "nt":
        for cmd in (["getmac", "/fo", "csv", "/nh"], ["ipconfig", "/all"]):
            for m in _MAC_RE.finditer(_quiet_run(cmd)):
                found.add(normalise_mac(m.group(0)))
            if found:
                break
    else:                                            # pragma: no cover - Windows tool
        base = "/sys/class/net"
        if os.path.isdir(base):
            for nic in sorted(os.listdir(base)):
                try:
                    with open(os.path.join(base, nic, "address")) as fh:
                        found.add(normalise_mac(fh.read().strip()))
                except (OSError, ValueError):
                    pass

    import uuid as _uuid
    node = _uuid.getnode()
    # getnode() invents a random address when it cannot find a real one, and
    # marks it by setting the multicast bit - such a value must not be trusted
    if not (node >> 40) & 1:
        found.add(normalise_mac("%012X" % node))

    return sorted(a for a in found if a not in _BOGUS)


# --------------------------------------------------------------------------
# RSA
# --------------------------------------------------------------------------
def _is_probable_prime(n: int, rounds: int = 48) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _gen_prime(bits: int) -> int:
    while True:
        cand = secrets.randbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(cand):
            return cand


def generate_keypair(bits: int = 2048) -> Dict[str, Dict]:
    """Returns {"public": {...}, "private": {...}}.  Run once, by the vendor."""
    e = 65537
    while True:
        p = _gen_prime(bits // 2)
        q = _gen_prime(bits // 2)
        if p == q:
            continue
        phi = (p - 1) * (q - 1)
        if phi % e == 0:
            continue
        n = p * q
        if n.bit_length() != bits:
            continue
        return {"public": {"n": "%x" % n, "e": e, "bits": bits},
                "private": {"n": "%x" % n, "e": e, "d": "%x" % pow(e, -1, phi),
                            "bits": bits}}


def _key_int(key: Dict, name: str) -> int:
    v = key[name]
    return v if isinstance(v, int) else int(v, 16)


def _pkcs1_v15(digest: bytes, k: int) -> bytes:
    t = _SHA256_DER + digest
    if k < len(t) + 11:
        raise ValueError("key too small for a SHA-256 signature")
    return b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t


def sign(private_key: Dict, data: bytes) -> bytes:
    n, d = _key_int(private_key, "n"), _key_int(private_key, "d")
    k = (n.bit_length() + 7) // 8
    em = _pkcs1_v15(hashlib.sha256(data).digest(), k)
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def verify(public_key: Dict, data: bytes, signature: bytes) -> bool:
    try:
        n, e = _key_int(public_key, "n"), _key_int(public_key, "e")
        k = (n.bit_length() + 7) // 8
        if len(signature) != k:
            return False
        em = pow(int.from_bytes(signature, "big"), e, n).to_bytes(k, "big")
        return secrets.compare_digest(em, _pkcs1_v15(hashlib.sha256(data).digest(), k))
    except (ValueError, KeyError, TypeError):
        return False


# --------------------------------------------------------------------------
# licence tokens
# --------------------------------------------------------------------------
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _canonical(payload: Dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def issue(private_key: Dict, mac: str, expires_utc: datetime.datetime,
          licensee: str = "", note: str = "") -> str:
    """Build a signed licence token.  `expires_utc` is truncated to the minute."""
    payload = {
        "v": 1,
        "mac": normalise_mac(mac),
        "exp": expires_utc.astimezone(datetime.timezone.utc).strftime(MINUTE),
        "iat": datetime.datetime.now(datetime.timezone.utc).strftime(MINUTE),
        "to": licensee.strip(),
        "note": note.strip(),
    }
    raw = _canonical(payload)
    return "%s.%s.%s" % (TOKEN_PREFIX, _b64e(raw), _b64e(sign(private_key, raw)))


def wrap(token: str, payload: Optional[Dict] = None) -> str:
    """The form written to license.key - readable, and safe to paste in mail."""
    head = ["----- BEGIN SOMEIP TOOL LICENSE -----"]
    if payload:
        head += ["# machine : %s" % payload.get("mac", ""),
                 "# expires : %s UTC" % payload.get("exp", "")]
        if payload.get("to"):
            head.append("# licensed: %s" % payload["to"])
    body = [token[i:i + 72] for i in range(0, len(token), 72)]
    return "\n".join(head + body + ["----- END SOMEIP TOOL LICENSE -----", ""])


def unwrap(text: str) -> str:
    """Recover the token from a wrapped file: drop comments and whitespace."""
    keep = [ln.strip() for ln in (text or "").splitlines()
            if ln.strip() and not ln.strip().startswith(("-----", "#"))]
    return "".join(keep)


def decode(token: str, public_key: Optional[Dict] = None) -> Dict:
    """Payload of a token whose signature checks out.  Raises otherwise."""
    key = public_key if public_key is not None else builtin_public_key()
    if not key:
        raise LicenseError("this build carries no public key, so no licence can "
                           "be checked - it was not packaged correctly")
    parts = (token or "").split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise LicenseError("this does not look like a licence")
    try:
        raw, sig = _b64d(parts[1]), _b64d(parts[2])
    except (ValueError, TypeError):
        raise LicenseError("the licence is damaged - it may have been re-wrapped "
                           "by a mail client") from None
    if not verify(key, raw, sig):
        raise LicenseError("the signature does not match; this licence was not "
                           "issued for this tool")
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise LicenseError("the licence contents are unreadable") from None


# --------------------------------------------------------------------------
# where a licence lives
# --------------------------------------------------------------------------
def app_dir() -> str:
    """Beside the executable when frozen, beside this file otherwise."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def user_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME)


def license_paths() -> List[str]:
    """Every place a licence is looked for, in order."""
    out = []
    env = os.environ.get("SOMEIP_LICENSE")
    if env:
        out.append(env)
    out.append(os.path.join(app_dir(), LICENSE_FILENAME))
    out.append(os.path.join(user_dir(), LICENSE_FILENAME))
    return out


def install(text: str) -> str:
    """Store a licence for this user.  Returns where it went."""
    decode(unwrap(text))                       # refuse to store a bad one
    os.makedirs(user_dir(), exist_ok=True)
    dest = os.path.join(user_dir(), LICENSE_FILENAME)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(text if text.lstrip().startswith("-----") else wrap(unwrap(text)))
    return dest


def builtin_public_key() -> Optional[Dict]:
    try:
        import license_pubkey
        key = getattr(license_pubkey, "PUBLIC_KEY", None)
        return key or None
    except ImportError:
        return None


# --------------------------------------------------------------------------
# the check the rest of the tool asks for
# --------------------------------------------------------------------------
@dataclass
class Status:
    valid: bool = False
    reason: str = "No licence found."
    path: str = ""
    payload: Dict = field(default_factory=dict)

    @property
    def expires_local(self) -> str:
        exp = self.payload.get("exp")
        if not exp:
            return ""
        when = datetime.datetime.strptime(exp, MINUTE).replace(
            tzinfo=datetime.timezone.utc).astimezone()
        return when.strftime("%Y-%m-%d %H:%M")

    def summary(self) -> str:
        if not self.valid:
            return "Unlicensed - " + self.reason
        who = self.payload.get("to") or self.payload.get("mac", "")
        return "Licensed to %s until %s" % (who, self.expires_local)


def evaluate(text: str, macs: Optional[List[str]] = None,
             now: Optional[datetime.datetime] = None) -> Status:
    """Judge a licence without touching the filesystem - the testable core."""
    try:
        payload = decode(unwrap(text))
    except LicenseError as exc:
        return Status(False, str(exc))

    macs = machine_macs() if macs is None else macs
    if payload.get("mac") not in macs:
        return Status(False,
                      "issued for machine %s, but this machine is %s."
                      % (payload.get("mac", "?"), ", ".join(macs) or "unknown"),
                      payload=payload)

    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        exp = datetime.datetime.strptime(payload["exp"], MINUTE).replace(
            tzinfo=datetime.timezone.utc)
    except (KeyError, ValueError):
        return Status(False, "the expiry date is unreadable.", payload=payload)
    if now > exp:
        st = Status(False, "", payload=payload)
        return Status(False, "it expired on %s." % st.expires_local, payload=payload)

    return Status(True, "", payload=payload)


def status() -> Status:
    """Look in every known place and report on the first licence found."""
    macs = machine_macs()
    last = Status(False, "No licence found.")
    for path in license_paths():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                st = evaluate(fh.read(), macs=macs)
        except OSError as exc:
            last = Status(False, "cannot read %s: %s" % (path, exc), path=path)
            continue
        st.path = path
        if st.valid:
            return st
        last = st
    return last


def require(action: str = "produce output") -> Status:
    """Gate.  Raises LicenseError unless this machine holds a valid licence."""
    st = status()
    if not st.valid:
        raise LicenseError(
            "A licence is required to %s.\n%s\n\nThis machine: %s\n\n"
            "Send that address to whoever issues licences.  Install what comes "
            "back either with Help > Install licence... in the window, or by "
            "saving it as %s next to the program."
            % (action, st.reason, ", ".join(machine_macs()) or "unknown",
               LICENSE_FILENAME))
    return st

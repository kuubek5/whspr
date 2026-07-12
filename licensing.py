# licensing.py — offline signed-license check. The app ships only the PUBLIC
# key; valid keys can be produced solely with the private key held by the vendor
# (see make_license.py). A key encodes an expiry date and is signed with Ed25519,
# so it cannot be forged or edited without invalidating the signature.
#
# This is client-side DRM: it stops casual sharing and enforces the monthly
# window, but a determined attacker with the binary can bypass it. That is an
# inherent limit of any offline scheme.

import os
import json
import base64
import datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# vendor public key (from `python make_license.py genkey`)
LICENSE_PUBKEY_HEX = "234b21baec0c997b1f0a2198740967d96b64d8f1fe249378d05bf058d2c342c5"


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _pubkey() -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(LICENSE_PUBKEY_HEX))


def verify_key(key: str) -> dict:
    """Return the payload {'e': expiry, 'c': customer} if the signature is valid.
    Raises on any malformed/forged key."""
    key = "".join(key.split())  # strip whitespace/newlines
    payload_b64, sig_b64 = key.split(".", 1)
    payload = _b64u_decode(payload_b64)
    _pubkey().verify(_b64u_decode(sig_b64), payload)  # raises InvalidSignature
    return json.loads(payload)


def _paths(data_dir: str):
    return (os.path.join(data_dir, "license.key"),
            os.path.join(data_dir, ".lastseen"))


def _today_guarded(data_dir: str) -> datetime.date:
    """Effective 'today' that never goes earlier than the last recorded run, so
    winding the system clock back doesn't extend an expired license."""
    _, seen_path = _paths(data_dir)
    today = datetime.date.today()
    try:
        last = datetime.date.fromisoformat(open(seen_path).read().strip())
    except Exception:
        last = today
    eff = max(today, last)
    try:
        with open(seen_path, "w") as f:
            f.write(eff.isoformat())
    except OSError:
        pass
    return eff


def status(data_dir: str) -> dict:
    key_path, _ = _paths(data_dir)
    try:
        key = open(key_path).read().strip()
    except OSError:
        return {"licensed": False, "reason": "no_key", "exp": "", "daysLeft": 0}
    if not key:
        return {"licensed": False, "reason": "no_key", "exp": "", "daysLeft": 0}
    try:
        data = verify_key(key)
    except Exception:
        return {"licensed": False, "reason": "invalid", "exp": "", "daysLeft": 0}
    try:
        exp = datetime.date.fromisoformat(data["e"])
    except Exception:
        return {"licensed": False, "reason": "invalid", "exp": "", "daysLeft": 0}
    days = (exp - _today_guarded(data_dir)).days
    licensed = days >= 0
    return {
        "licensed": licensed,
        "reason": "ok" if licensed else "expired",
        "exp": data["e"],
        "daysLeft": max(0, days),
        "customer": data.get("c", ""),
    }


def activate(data_dir: str, key: str) -> dict:
    try:
        verify_key(key)
    except Exception:
        return {"ok": False, "error": "Недійсний ключ"}
    key_path, _ = _paths(data_dir)
    try:
        with open(key_path, "w") as f:
            f.write(key.strip())
    except OSError as e:
        return {"ok": False, "error": f"Не вдалося зберегти: {e}"}
    st = status(data_dir)
    if not st["licensed"]:
        return {"ok": False, "error": "Ключ прострочений"}
    return {"ok": True, **st}

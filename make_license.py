#!/usr/bin/env python
# make_license.py — VENDOR-ONLY tool. Never ship this or the private key.
#
# One-time setup:
#   python make_license.py genkey
#     -> writes keys/whspr_ed25519.pem (SECRET) and prints the PUBLIC key hex
#        to paste into license.py (LICENSE_PUBKEY_HEX).
#
# Issue a monthly key for a customer:
#   python make_license.py issue --days 30 --id "customer@example.com"
#     -> prints the license key string to send to the buyer.
#
# The app verifies keys with the embedded PUBLIC key only; keys can be issued
# solely by whoever holds the private key here.

import os
import json
import base64
import argparse
import datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

BASE = os.path.dirname(os.path.abspath(__file__))
KEYDIR = os.path.join(BASE, "keys")
PRIV_PATH = os.path.join(KEYDIR, "whspr_ed25519.pem")


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def genkey() -> None:
    os.makedirs(KEYDIR, exist_ok=True)
    if os.path.exists(PRIV_PATH):
        raise SystemExit(f"{PRIV_PATH} already exists — refusing to overwrite")
    priv = Ed25519PrivateKey.generate()
    with open(PRIV_PATH, "wb") as f:
        f.write(priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
    pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    print(f"private key written to {PRIV_PATH}  (KEEP SECRET, never commit)")
    print(f"\nPaste this into license.py:\n\nLICENSE_PUBKEY_HEX = \"{pub.hex()}\"\n")


def issue(days: int, cust: str) -> None:
    with open(PRIV_PATH, "rb") as f:
        priv = serialization.load_pem_private_key(f.read(), password=None)
    exp = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    payload = json.dumps({"e": exp, "c": cust},
                         separators=(",", ":"), sort_keys=True).encode()
    sig = priv.sign(payload)
    key = _b64u(payload) + "." + _b64u(sig)
    print(f"customer : {cust}")
    print(f"expires  : {exp}  ({days} days)")
    print(f"\nlicense key:\n{key}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="whspr license issuer (vendor-only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("genkey")
    p = sub.add_parser("issue")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--id", required=True)
    args = ap.parse_args()
    if args.cmd == "genkey":
        genkey()
    else:
        issue(args.days, args.id)


if __name__ == "__main__":
    main()

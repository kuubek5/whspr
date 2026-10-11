"""Licensing: status, activation and the license gate. Moved verbatim out of flow.py."""

import flow


# ---------------- Licensing ----------------
def license_status() -> dict:
    try:
        import licensing
        flow.state["license"] = licensing.status(flow.DATA_DIR)
    except Exception as e:
        flow.log(f"license check failed ({e.__class__.__name__}: {e})")
        flow.state["license"] = {"licensed": False, "reason": "error",
                            "exp": "", "daysLeft": 0}
    return flow.state["license"]


def activate_license(key: str) -> dict:
    try:
        import licensing
        res = licensing.activate(flow.DATA_DIR, key)
    except Exception as e:
        flow.log(f"activation failed ({e.__class__.__name__}: {e})")
        return {"ok": False, "error": "Помилка активації"}
    license_status()
    return res


def is_licensed() -> bool:
    return bool(flow.state.get("license", {}).get("licensed"))

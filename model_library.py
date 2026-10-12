"""Model library: download progress, the Models page list, install and delete. Moved verbatim out of flow.py."""

import os
import shutil
import threading

import flow


# ---------------- Download progress ----------------
def set_download(active: bool, label: str = "", mb: int = 0,
                 total_mb: int = 0) -> None:
    pct = round(mb / total_mb * 100) if total_mb else None
    flow.state["download"] = {"active": active, "label": label,
                         "mb": mb, "totalMb": total_mb, "pct": pct}


def _dir_size_mb(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total >> 20


def _watch_model_download(label: str, stop: threading.Event) -> None:
    """Report growth of the HF cache dir while a model downloads (its total is
    unknown up front, so we show MB pulled)."""
    cache = os.environ.get("HF_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface")
    base = _dir_size_mb(cache)
    while not stop.is_set():
        grown = _dir_size_mb(cache) - base
        if grown > 3:  # ignore tiny metadata churn
            set_download(True, label, mb=grown)
        stop.wait(0.6)


# ---------------- Model library ----------------
# Models are pulled on demand from the Models page instead of being bundled or
# silently fetched mid-dictation: a 3 GB surprise download while the user waits
# for their first transcript is worse than an explicit button.
def _hf_cache() -> str:
    try:
        from huggingface_hub import constants
        return constants.HF_HUB_CACHE
    except Exception:
        return os.environ.get("HF_HUB_CACHE") or os.path.join(
            os.path.expanduser("~"), ".cache", "huggingface", "hub")


def _repo_cache_dir(repo: str) -> str:
    """Where huggingface_hub keeps a repo: <cache>/models--org--name."""
    return os.path.join(_hf_cache(), "models--" + repo.replace("/", "--"))


def model_installed(repo: str) -> bool:
    d = _repo_cache_dir(repo)
    # a bare dir can linger after a failed pull; require actual weights
    return os.path.isdir(d) and _dir_size_mb(d) > 20


def models_status() -> list[dict]:
    """Registry plus what is actually on disk, for the Models page."""
    active = flow.config.get("model_uk", "stock")
    out = []
    for key, spec in flow.MODELS.items():
        repo = spec["repo"]
        installed = model_installed(repo)
        out.append({
            "id": key, "label": spec["label"], "note": spec.get("note", ""),
            "size": spec["size"], "en": spec.get("en", False), "repo": repo,
            "installed": installed, "active": key == active,
            # real footprint: on Windows the cache keeps blobs *and* snapshot
            # copies, so this runs well above the advertised download size
            "diskMb": _dir_size_mb(_repo_cache_dir(repo)) if installed else 0,
        })
    return out


def download_model(key: str) -> dict:
    """Fetch a model in the background. Returns immediately; progress shows up
    in state['download'] the same way the first-run model pull does.

    key "parakeet" fetches the optional Parakeet engine (not a Whisper model, so
    it is not in MODELS / the model picker): only the files for the quantization
    this machine will actually run, not the whole 3 GB repo."""
    patterns = None
    if key == "parakeet":
        if not flow.parakeet_available():
            return {"ok": False, "error": "не встановлено пакет onnx-asr"}
        quant = flow._parakeet_quant(flow._parakeet_providers()[1])
        spec = {"repo": flow.PARAKEET["repo"], "label": flow.PARAKEET["label"]}
        patterns = flow._parakeet_files(quant)
        if flow.parakeet_installed(quant):
            return {"ok": True, "already": True}
    else:
        spec = flow.MODELS.get(key)
    if spec is None:
        return {"ok": False, "error": "невідома модель"}
    if flow.state.get("downloading"):
        return {"ok": False, "error": "вже качається інша модель"}
    repo = spec["repo"]
    if patterns is None and model_installed(repo):
        return {"ok": True, "already": True}

    def run():
        flow.state["downloading"] = key
        flow.state["download_error"] = None  # clear any error from a previous attempt
        stop = threading.Event()
        threading.Thread(target=_watch_model_download,
                         args=(spec["label"], stop), daemon=True).start()
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id=repo, allow_patterns=patterns)
            flow.log(f"downloaded {repo}")
            if patterns is None:
                flow.ensure_tokenizer(repo)  # repair CT2 repos that ship without one
            elif flow.config.get("local_engine") == "parakeet":
                flow.preload_parakeet()  # already selected: warm it now
        except Exception as e:
            flow.log(f"download failed for {repo} ({e.__class__.__name__}: {e})")
            flow.state["download_error"] = str(e)
        finally:
            stop.set()
            set_download(False)
            flow.state["downloading"] = None

    threading.Thread(target=run, daemon=True).start()
    return {"ok": True}


def delete_model(key: str) -> dict:
    """Remove a downloaded model's cache directory to reclaim disk."""
    spec = flow.MODELS.get(key)
    if spec is None:
        return {"ok": False, "error": "невідома модель"}
    if key == flow.config.get("model_uk", "stock"):
        # deleting the active model would break the next dictation
        return {"ok": False, "error": "спершу оберіть іншу активну модель"}
    if spec["repo"] == flow.MODEL_NAME:
        # the default is the universal fallback: model_name_for() and auto-lang
        # drop to it, so deleting it would trigger a silent 1.5 GB re-download
        # mid-dictation under the model lock
        return {"ok": False, "error": "базову модель видалити не можна"}
    d = _repo_cache_dir(spec["repo"])
    # only ever delete inside the HF cache, and only a dir we generated the
    # name for — never a path that arrived from the UI
    if not os.path.isdir(d) or os.path.dirname(d) != _hf_cache():
        return {"ok": False, "error": "не знайдено на диску"}
    try:
        shutil.rmtree(d)
        flow.state["models"].pop(spec["repo"], None)  # drop any cached instance
        flow.log(f"deleted {spec['repo']}")
        return {"ok": True}
    except Exception as e:
        flow.log(f"delete failed for {spec['repo']} ({e.__class__.__name__}: {e})")
        return {"ok": False, "error": str(e)}

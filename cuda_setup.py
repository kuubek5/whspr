# cuda_setup.py — first-run CUDA runtime provisioning for the installed build.
#
# The installer ships WITHOUT the ~1.9 GB nvidia cuBLAS/cuDNN libraries. On the
# first launch, if an NVIDIA GPU is present, we download the two wheels straight
# from PyPI (they are just zips of DLLs) and extract them into <data>/cuda. No
# GPU -> we skip and the app runs on CPU. Everything here is best-effort: any
# failure leaves the app on CPU, never crashes it.

import os
import json
import zipfile
import tempfile
import subprocess
import urllib.request

# cuBLAS: latest is fine. cuDNN pinned to 9.1.0.70 — newer 9.x builds trigger
# multi-minute runtime kernel compilation with ctranslate2 4.8 on SM86.
PACKAGES = [
    ("nvidia-cublas-cu12", None),
    ("nvidia-cudnn-cu12", "9.1.0.70"),
]


def has_nvidia_gpu() -> bool:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


def _wheel_url(pkg: str, version):
    api = (f"https://pypi.org/pypi/{pkg}/json" if version is None
           else f"https://pypi.org/pypi/{pkg}/{version}/json")
    with urllib.request.urlopen(api, timeout=30) as r:
        data = json.load(r)
    for f in data["urls"]:
        fn = f["filename"]
        if fn.endswith(".whl") and "win_amd64" in fn:
            return f["url"], fn
    raise RuntimeError(f"no win_amd64 wheel for {pkg}")


def _download(url: str, log, progress=None) -> str:
    fd, tmp = tempfile.mkstemp(suffix=".whl")
    os.close(fd)
    with urllib.request.urlopen(url, timeout=900) as r:
        total = int(r.headers.get("Content-Length", 0))
        done = mark = 0
        with open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    try:
                        progress(done, total)
                    except Exception:
                        pass
                if total and done - mark >= (50 << 20):  # log every ~50 MB
                    mark = done
                    log(f"  {done >> 20}/{total >> 20} MB")
    return tmp


def is_ready(data_dir: str) -> bool:
    root = os.path.join(data_dir, "cuda", "nvidia")
    return (os.path.isdir(os.path.join(root, "cublas", "bin"))
            and os.path.isdir(os.path.join(root, "cudnn", "bin")))


def ensure_cuda(data_dir: str, log=print, progress=None) -> bool:
    """Download+extract cuBLAS/cuDNN into <data_dir>/cuda if missing and a GPU
    is present. Returns True if the CUDA runtime is available afterwards.
    `progress(done_bytes, total_bytes)` is called during downloads."""
    if is_ready(data_dir):
        return True
    if not has_nvidia_gpu():
        log("no NVIDIA GPU detected — using CPU")
        return False
    dest = os.path.join(data_dir, "cuda")
    os.makedirs(dest, exist_ok=True)
    log("downloading CUDA runtime (one-time, ~0.9 GB)…")
    for pkg, ver in PACKAGES:
        try:
            url, fn = _wheel_url(pkg, ver)
            log(f"downloading {fn}")
            tmp = _download(url, log, progress)
            log(f"extracting {fn}")
            with zipfile.ZipFile(tmp) as z:
                for m in z.namelist():
                    if m.startswith("nvidia/") and not m.endswith("/"):
                        z.extract(m, dest)
            os.remove(tmp)
        except Exception as e:
            log(f"CUDA setup failed for {pkg} ({e.__class__.__name__}: {e}) — CPU")
            return False
    log("CUDA runtime ready")
    return is_ready(data_dir)

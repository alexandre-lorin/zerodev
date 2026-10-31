"""Support GPU / projets IA : CUDA, ROCm, Vulkan, Metal, fichiers modèles."""
from __future__ import annotations

import platform
import re
import shutil
import subprocess
from pathlib import Path

from .util import read

MODEL_EXT = (".gguf", ".safetensors", ".ckpt", ".pth", ".onnx")


def detect_gpu() -> dict:
    """Retourne {vendor, name, cuda} ; vendor ∈ nvidia|amd|vulkan|apple|None."""
    info = {"vendor": None, "name": None, "cuda": None}
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"CUDA Version:\s*([\d.]+)", out)
            n = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip().splitlines()
            info.update(vendor="nvidia", cuda=m.group(1) if m else None, name=n[0] if n else None)
            return info
        except Exception:
            pass
    if shutil.which("rocm-smi") or Path("/opt/rocm").exists():
        info.update(vendor="amd")
        return info
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        info.update(vendor="apple", name="Apple Silicon (Metal)")
        return info
    if shutil.which("vulkaninfo"):
        info.update(vendor="vulkan")
    return info


def build_env(ai_libs: list[str], gpu: dict) -> dict:
    """Variables d'environnement à injecter pour compiler/installer les libs GPU."""
    env: dict[str, str] = {}
    if "llama-cpp-python" in ai_libs:
        flag = {"nvidia": "-DGGML_CUDA=on", "amd": "-DGGML_HIP=on",
                "vulkan": "-DGGML_VULKAN=on", "apple": "-DGGML_METAL=on"}.get(gpu["vendor"])
        if flag:
            env["CMAKE_ARGS"] = flag
    return env


def model_notes(root: Path) -> list[str]:
    notes = []
    readme = (read(root, "README.md") or "").lower()
    if re.search(r"\.(gguf|safetensors|ckpt)\b|huggingface\.co", readme):
        notes.append("le README mentionne des fichiers modèles à télécharger (non gérés en V0–V4)")
    found = [p.name for p in root.rglob("*") if p.suffix in MODEL_EXT and ".git" not in p.parts][:3]
    if found:
        notes.append(f"modèles présents : {', '.join(found)}")
    return notes


def describe(ai_libs: list[str], gpu: dict) -> list[str]:
    if not ai_libs:
        return []
    lines = []
    if gpu["vendor"]:
        extra = f" (CUDA {gpu['cuda']})" if gpu["cuda"] else ""
        lines.append(f"GPU détecté : {gpu['vendor']}{extra}")
    else:
        lines.append("aucun GPU détecté : roues CPU")
    return lines


REQ_GROUP_PREFERENCE = ("full", "main", "base", "default", "all")        # jeu « complet » avant les variantes allégées
HARDWARE_SUFFIXES = {"nvidia": ("", "_cuda"), "amd": ("_amd", "_rocm"), "vulkan": ("_vulkan", "_cpu_only", "_cpu"),
                     "apple_arm": ("_apple_silicon", "_apple", "_mps"), "apple_intel": ("_apple_intel", "_cpu_only"),
                     None: ("_cpu_only", "_cpu", "")}


def pick_requirements_variant(root: Path, gpu: dict | None = None) -> tuple[str, str] | None:
    """Projets qui rangent leurs dépendances par variante matérielle (text-generation-webui :
    requirements/full/requirements{,_amd,_apple_silicon,_cpu_only,…}.txt) → (chemin relatif, explication).

    Choix d'après le matériel détecté ; sans GPU, la variante CPU si elle existe. Un choix devinable, signalé en note."""
    base = root / "requirements"
    if not base.is_dir():
        return None
    groups = sorted(d for d in base.iterdir() if d.is_dir() and any(d.glob("requirements*.txt")))
    if not groups:
        return None
    group = next((g for pref in REQ_GROUP_PREFERENCE for g in groups if g.name == pref), groups[0])
    gpu = gpu if gpu is not None else detect_gpu()
    vendor = gpu.get("vendor")
    if vendor == "apple":
        vendor = "apple_arm" if platform.machine() == "arm64" else "apple_intel"
    elif platform.system() == "Darwin" and vendor is None:
        vendor = "apple_intel"
    for suffix in HARDWARE_SUFFIXES.get(vendor, HARDWARE_SUFFIXES[None]):
        f = group / f"requirements{suffix}.txt"
        if f.is_file():
            kind = {"nvidia": "NVIDIA/CUDA", "amd": "AMD/ROCm", "vulkan": "Vulkan", "apple_arm": "Apple Silicon",
                    "apple_intel": "Mac Intel", None: "aucun GPU détecté"}[vendor]
            return str(f.relative_to(root)), f"variantes de dépendances par matériel : {f.relative_to(root)} choisi ({kind})"
    return None

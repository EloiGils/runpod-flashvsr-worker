import os
import base64
import time
import uuid
import glob
import copy

import requests
import runpod  # <--- IMPORTANTE


# Config por defecto del contenedor ComfyUI
COMFY_URL = os.getenv("COMFY_URL", "http://127.0.0.1:8188")
COMFY_INPUT_DIR = os.getenv("COMFY_INPUT_DIR", "/comfyui/input")
COMFY_OUTPUT_DIR = os.getenv("COMFY_OUTPUT_DIR", "/comfyui/output")
WORKFLOW_TIMEOUT_SECONDS = int(os.getenv("FLASHVSR_TIMEOUT", "3600"))


# Plantilla de tu workflow FlashVSR (API export)
FLASHVSR_WORKFLOW_TEMPLATE = {
    "1": {
        "inputs": {
            "video": "input/Abundance_10.mp4",
            "force_rate": 0,
            "custom_width": 0,
            "custom_height": 0,
            "frame_load_cap": 0,
            "skip_first_frames": 0,
            "select_every_nth": 1,
            "format": "AnimateDiff"
        },
        "class_type": "VHS_LoadVideoPath",
        "_meta": {
            "title": "Load Video (Path) 🎥🅥🅗🅢"
        }
    },
    "2": {
        "inputs": {
            "model": "FlashVSR-v1.1",
            "mode": "tiny",
            "scale": 2,
            "tiled_vae": True,
            "tiled_dit": True,
            "unload_dit": False,
            "seed": 33833989687976,
            "frames": ["1", 0]
        },
        "class_type": "FlashVSRNode",
        "_meta": {
            "title": "FlashVSR Ultra-Fast"
        }
    },
    "3": {
        "inputs": {
            "frame_rate": 30,
            "loop_count": 0,
            "filename_prefix": "flashvsr_test",
            "format": "video/h264-mp4",
            "pix_fmt": "yuv420p",
            "crf": 19,
            "save_metadata": True,
            "trim_to_audio": False,
            "pingpong": False,
            "save_output": True,
            "images": ["2", 0],
            "audio": ["1", 2]
        },
        "class_type": "VHS_VideoCombine",
        "_meta": {
            "title": "Video Combine 🎥🅥🅗🅢"
        }
    }
}


def _ensure_dirs():
    os.makedirs(COMFY_INPUT_DIR, exist_ok=True)
    os.makedirs(COMFY_OUTPUT_DIR, exist_ok=True)


def _save_video_to_input(video_name: str, video_b64: str) -> str:
    """Guarda el vídeo base64 en /comfyui/input/<video_name>."""
    _ensure_dirs()

    # Quitar prefijo tipo "data:video/mp4;base64,..."
    if "," in video_b64:
        video_b64 = video_b64.split(",", 1)[1]

    data = base64.b64decode(video_b64)
    path = os.path.join(COMFY_INPUT_DIR, video_name)

    with open(path, "wb") as f:
        f.write(data)

    print(f"[handler] Guardado vídeo en {path}", flush=True)
    return path


def _list_output_mp4_files():
    """Lista todos los .mp4 en /comfyui/output."""
    pattern = os.path.join(COMFY_OUTPUT_DIR, "*.mp4")
    return glob.glob(pattern)


def _run_workflow_in_comfyui(workflow: dict) -> str:
    """Lanza el workflow en ComfyUI vía /prompt y espera el /history."""
    client_id = str(uuid.uuid4())
    payload = {
        "client_id": client_id,
        "prompt": workflow
    }

    print(f"[handler] Enviando prompt a ComfyUI, client_id={client_id}", flush=True)
    r = requests.post(f"{COMFY_URL}/prompt", json=payload, timeout=60)
    r.raise_for_status()

    start = time.time()

    while True:
        if time.time() - start > WORKFLOW_TIMEOUT_SECONDS:
            raise TimeoutError("FlashVSR workflow timed out.")

        time.sleep(5)

        try:
            hr = requests.get(f"{COMFY_URL}/history/{client_id}", timeout=60)
        except Exception:
            continue

        if hr.status_code != 200:
            continue

        try:
            data = hr.json()
        except Exception:
            continue

        history = data.get("history", {})
        if history:
            print("[handler] History encontrado en ComfyUI", flush=True)
            break

    # Pequeña espera para que se escriba el vídeo
    time.sleep(5)

    return client_id


def handler(event):
    """
    Entrada serverless.

    Espera:
    {
      "input": {
        "video_name": "Abundance_3.mp4",
        "video_b64": "<BASE64 DEL VIDEO>",
        "mode": "tiny",
        "scale": 2
      }
    }
    """
    print(f"[handler] Evento recibido: keys={list(event.keys())}", flush=True)

    input_data = event.get("input") or {}

    video_name = input_data.get("video_name", "input_video.mp4")
    video_b64 = input_data.get("video_b64")
    mode = input_data.get("mode", "tiny")
    scale = int(input_data.get("scale", 2))

    if not video_b64:
        raise ValueError("input.video_b64 es obligatorio")

    # 1) Guardar vídeo
    before_files = set(_list_output_mp4_files())
    video_path = _save_video_to_input(video_name, video_b64)

    # 2) Construir workflow
    workflow = copy.deepcopy(FLASHVSR_WORKFLOW_TEMPLATE)
    workflow["1"]["inputs"]["video"] = f"input/{video_name}"
    workflow["2"]["inputs"]["mode"] = mode
    workflow["2"]["inputs"]["scale"] = scale

    print(f"[handler] Lanzando workflow: mode={mode}, scale={scale}", flush=True)
    client_id = _run_workflow_in_comfyui(workflow)

    # 3) Buscar nuevo mp4 en /output
    after_files = set(_list_output_mp4_files())
    new_files = list(after_files - before_files)

    output_path = None
    if new_files:
        output_path = max(new_files, key=lambda p: os.path.getmtime(p))

    output_b64 = None
    if output_path and os.path.exists(output_path):
        with open(output_path, "rb") as f:
            output_b64 = base64.b64encode(f.read()).decode("ascii")

    print(f"[handler] Finalizado. output={output_path}", flush=True)

    return {
        "client_id": client_id,
        "input_video_path": video_path,
        "output_video_path": output_path,
        "output_video_b64": output_b64,
        "mode": mode,
        "scale": scale
    }


# *** CLAVE ***: decirle a RunPod que use esta función.
runpod.serverless.start({"handler": handler})

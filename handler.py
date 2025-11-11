import os
import base64
import time
import uuid
import glob
import copy
import subprocess

import requests
import runpod

# ---------------------------------------
# Configuración rutas / ComfyUI
# ---------------------------------------
COMFY_ROOT = "/comfyui"
COMFY_URL = "http://127.0.0.1:8188"
COMFY_INPUT_DIR = os.path.join(COMFY_ROOT, "input")
COMFY_OUTPUT_DIR = os.path.join(COMFY_ROOT, "output")
WORKFLOW_TIMEOUT_SECONDS = int(os.getenv("FLASHVSR_TIMEOUT", "3600"))

# ---------------------------------------
# Workflow FlashVSR plantilla (API export)
# ---------------------------------------
FLASHVSR_WORKFLOW_TEMPLATE = {
    "1": {
        "inputs": {
            "video": "input/placeholder.mp4",  # lo sobreescribimos
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
            "mode": "tiny",    # lo podemos cambiar por input
            "scale": 2,        # lo podemos cambiar por input
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
            "filename_prefix": "flashvsr_serverless",
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


# ---------------------------------------
# Utilidades
# ---------------------------------------

def _ensure_dirs():
    os.makedirs(COMFY_INPUT_DIR, exist_ok=True)
    os.makedirs(COMFY_OUTPUT_DIR, exist_ok=True)


def _start_comfy_if_needed():
    """
    Arranca ComfyUI si no está ya escuchando en 8188.
    Solo se ejecuta una vez por contenedor.
    """
    if os.environ.get("COMFY_ALREADY_STARTED") == "1":
        return

    # ¿ya responde?
    try:
        requests.get(f"{COMFY_URL}/system_stats", timeout=2)
        os.environ["COMFY_ALREADY_STARTED"] = "1"
        return
    except Exception:
        pass

    # Lanzar ComfyUI en background
    subprocess.Popen(
        ["python3", "main.py", "--listen", "0.0.0.0", "--port", "8188"],
        cwd=COMFY_ROOT
    )

    # Esperar a que levante
    for _ in range(120):
        try:
            requests.get(f"{COMFY_URL}/system_stats", timeout=2)
            os.environ["COMFY_ALREADY_STARTED"] = "1"
            return
        except Exception:
            time.sleep(1)

    raise RuntimeError("ComfyUI no arrancó correctamente.")


def _save_video_to_input(video_name: str, video_b64: str) -> str:
    """
    Guarda el vídeo base64 en /comfyui/input/<video_name>
    y devuelve la ruta absoluta.
    """
    _ensure_dirs()

    # Si viene como "data:video/mp4;base64,AAAA..."
    if "," in video_b64:
        video_b64 = video_b64.split(",", 1)[1]

    data = base64.b64decode(video_b64)
    path = os.path.join(COMFY_INPUT_DIR, video_name)

    with open(path, "wb") as f:
        f.write(data)

    return path


def _list_output_mp4_files():
    pattern = os.path.join(COMFY_OUTPUT_DIR, "*.mp4")
    return glob.glob(pattern)


def _run_workflow_in_comfyui(workflow: dict) -> str:
    """
    Lanza el workflow en ComfyUI vía /prompt y espera a que
    se complete (vía /history/<client_id>).
    """
    client_id = str(uuid.uuid4())
    payload = {
        "client_id": client_id,
        "prompt": workflow
    }

    # Enviar prompt
    r = requests.post(f"{COMFY_URL}/prompt", json=payload, timeout=30)
    r.raise_for_status()

    start = time.time()

    while True:
        if time.time() - start > WORKFLOW_TIMEOUT_SECONDS:
            raise TimeoutError("FlashVSR workflow timed out.")

        time.sleep(5)

        try:
            hr = requests.get(f"{COMFY_URL}/history/{client_id}", timeout=30)
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
            break

    # pequeña espera para que se escriba el vídeo
    time.sleep(5)

    return client_id


# ---------------------------------------
# Handler RunPod
# ---------------------------------------

def handler(event):
    """
    Espera un JSON:
    {
      "input": {
        "video_name": "mi_video.mp4",
        "video_b64": "<BASE64>",
        "mode": "tiny" | "full" | "tiny-long",
        "scale": 2 | 4
      }
    }
    """
    _start_comfy_if_needed()

    input_data = event.get("input") or {}

    video_name = input_data.get("video_name", "input_video.mp4")
    video_b64 = input_data.get("video_b64")
    mode = input_data.get("mode", "tiny")
    scale = int(input_data.get("scale", 2))

    if not video_b64:
        raise ValueError("input.video_b64 es obligatorio")

    # 1) Guardar vídeo en /comfyui/input
    before_files = set(_list_output_mp4_files())
    video_path = _save_video_to_input(video_name, video_b64)

    # 2) Construir workflow FlashVSR a partir de la plantilla
    workflow = copy.deepcopy(FLASHVSR_WORKFLOW_TEMPLATE)

    # Nodo 1: VHS_LoadVideoPath -> apuntar al vídeo que acabamos de guardar
    workflow["1"]["inputs"]["video"] = f"input/{video_name}"

    # Nodo 2: FlashVSRNode -> modo y escala
    workflow["2"]["inputs"]["mode"] = mode
    workflow["2"]["inputs"]["scale"] = scale

    # 3) Lanzar workflow en ComfyUI
    client_id = _run_workflow_in_comfyui(workflow)

    # 4) Buscar el nuevo mp4 generado en /comfyui/output
    after_files = set(_list_output_mp4_files())
    new_files = list(after_files - before_files)

    output_path = None
    if new_files:
        output_path = max(new_files, key=lambda p: os.path.getmtime(p))

    output_b64 = None
    if output_path and os.path.exists(output_path):
        with open(output_path, "rb") as f:
            output_b64 = base64.b64encode(f.read()).decode("ascii")

    # 5) Devolver info a n8n
    return {
        "client_id": client_id,
        "input_video_path": video_path,
        "output_video_path": output_path,
        "output_video_b64": output_b64,
        "mode": mode,
        "scale": scale
    }


# Arrancar loop serverless de RunPod
runpod.serverless.start({"handler": handler})


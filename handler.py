import os
import base64
import time
import uuid
import glob
import copy
import requests
import runpod

# -------------------------------------------------------------------
# CONFIG BÁSICA
# -------------------------------------------------------------------

# ComfyUI corre dentro del contenedor en este puerto (imagen runpod/worker-comfyui)
COMFY_URL = os.getenv("COMFY_URL", "http://127.0.0.1:8188")

# Directorios estándar de ComfyUI según los logs:
# ** ComfyUI Path: /comfyui
# así que el input y output son:
COMFY_INPUT_DIR = os.getenv("COMFY_INPUT_DIR", "/comfyui/input")
COMFY_OUTPUT_DIR = os.getenv("COMFY_OUTPUT_DIR", "/comfyui/output")

# Timeout máximo para un vídeo (en segundos)
WORKFLOW_TIMEOUT_SECONDS = int(os.getenv("FLASHVSR_TIMEOUT", "3600"))


# -------------------------------------------------------------------
# WORKFLOW FLASHVSR (PLANTILLA)
#   -> Es el export API de tu grafo que ya funcionaba en el POD
# -------------------------------------------------------------------

FLASHVSR_WORKFLOW_TEMPLATE = {
    "1": {
        "inputs": {
            # ESTE CAMPO "video" LO SOBREESCRIBIMOS EN RUNTIME
            "video": "Abundance_10.mp4",
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
            "mode": "tiny",        # lo sobreescribimos con input.mode
            "scale": 2,            # lo sobreescribimos con input.scale
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


# -------------------------------------------------------------------
# UTILIDADES
# -------------------------------------------------------------------

def _ensure_dirs():
    os.makedirs(COMFY_INPUT_DIR, exist_ok=True)
    os.makedirs(COMFY_OUTPUT_DIR, exist_ok=True)


def _save_video_to_input(video_name: str, video_b64: str) -> str:
    """
    Guarda el vídeo base64 en /comfyui/input/<video_name>
    y devuelve la ruta absoluta.
    """
    _ensure_dirs()

    # Si viene con "data:video/mp4;base64,..." lo cortamos
    if "," in video_b64:
        video_b64 = video_b64.split(",", 1)[1]

    data = base64.b64decode(video_b64)
    path = os.path.join(COMFY_INPUT_DIR, video_name)

    with open(path, "wb") as f:
        f.write(data)

    print(f"[FlashVSR handler] Saved input video at: {path}", flush=True)
    return path


def _list_output_mp4_files():
    """
    Lista todos los mp4 en el directorio de salida de ComfyUI.
    """
    pattern = os.path.join(COMFY_OUTPUT_DIR, "*.mp4")
    files = glob.glob(pattern)
    return files


def _run_workflow_in_comfyui(workflow: dict) -> str:
    """
    Lanza el workflow en ComfyUI vía /prompt y espera
    a que se complete usando /history/<client_id>.
    """
    client_id = str(uuid.uuid4())

    payload = {
        "client_id": client_id,
        "prompt": workflow
    }

    print(f"[FlashVSR handler] Sending prompt to ComfyUI, client_id={client_id}", flush=True)

    # Enviar prompt
    r = requests.post(f"{COMFY_URL}/prompt", json=payload, timeout=60)
    r.raise_for_status()

    start = time.time()

    # Polling /history
    while True:
        elapsed = time.time() - start
        if elapsed > WORKFLOW_TIMEOUT_SECONDS:
            raise TimeoutError("FlashVSR workflow timed out.")

        time.sleep(5)

        try:
            hr = requests.get(f"{COMFY_URL}/history/{client_id}", timeout=30)
        except Exception as e:
            print(f"[FlashVSR handler] Error checking history: {e}", flush=True)
            continue

        if hr.status_code != 200:
            continue

        try:
            data = hr.json()
        except Exception:
            continue

        history = data.get("history", {})
        if history:
            print(f"[FlashVSR handler] Workflow finished in ComfyUI (history found).", flush=True)
            break

    # Espera extra a que el vídeo se escriba a disco
    time.sleep(5)

    return client_id


# -------------------------------------------------------------------
# HANDLER PRINCIPAL (lo que llama RunPod)
# -------------------------------------------------------------------

def handler(event):
    """
    Entrada Serverless de RunPod.

    Espera un JSON como:

    {
      "input": {
        "video_name": "Abundance_3.mp4",
        "video_b64": "<BASE64>",
        "mode": "tiny" | "full" | "tiny-long",
        "scale": 2 | 3 | 4
      }
    }
    """

    print("[FlashVSR handler] Event received", flush=True)

    input_data = event.get("input") or {}

    video_name = input_data.get("video_name", "input_video.mp4")
    video_b64 = input_data.get("video_b64")
    mode = input_data.get("mode", "tiny")
    scale = int(input_data.get("scale", 2))

    if not video_b64:
        raise ValueError("input.video_b64 es obligatorio")

    print(f"[FlashVSR handler] video_name={video_name}, mode={mode}, scale={scale}", flush=True)

    # 1) Guardar vídeo en /comfyui/input
    before_files = set(_list_output_mp4_files())
    video_path = _save_video_to_input(video_name, video_b64)

    # 2) Construir workflow desde la plantilla
    workflow = copy.deepcopy(FLASHVSR_WORKFLOW_TEMPLATE)

    # >>> CLAVE: VHS_LoadVideoPath espera un path RELATIVO al directorio de input de ComfyUI.
    # El input_dir de ComfyUI es "input", y nosotros guardamos en /comfyui/input/<video_name>.
    # Por tanto, aquí solo ponemos el nombre del archivo, SIN "input/" delante.
    workflow["1"]["inputs"]["video"] = video_name

    # FlashVSRNode: modo (tiny/full/tiny-long) y escala (2/3/4)
    workflow["2"]["inputs"]["mode"] = mode
    workflow["2"]["inputs"]["scale"] = scale

    print(f"[FlashVSR handler] Workflow video field set to: {workflow['1']['inputs']['video']}", flush=True)

    # 3) Ejecutar workflow en ComfyUI
    client_id = _run_workflow_in_comfyui(workflow)

    # 4) Buscar nuevo mp4 en /comfyui/output
    after_files = set(_list_output_mp4_files())
    new_files = list(after_files - before_files)

    output_path = None
    if new_files:
        # Elegimos el más reciente por fecha
        output_path = max(new_files, key=lambda p: os.path.getmtime(p))

    output_b64 = None
    if output_path and os.path.exists(output_path):
        with open(output_path, "rb") as f:
            output_b64 = base64.b64encode(f.read()).decode("ascii")
        print(f"[FlashVSR handler] Output video found: {output_path}", flush=True)
    else:
        print("[FlashVSR handler] No output video found in /comfyui/output", flush=True)

    # 5) Respuesta para n8n
    return {
        "client_id": client_id,
        "input_video_path": video_path,
        "output_video_path": output_path,
        "output_video_b64": output_b64,
        "mode": mode,
        "scale": scale
    }


# -------------------------------------------------------------------
# ARRANQUE SERVERLESS
# -------------------------------------------------------------------

runpod.serverless.start({"handler": handler})



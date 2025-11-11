# FlashVSR worker - Serverless ComfyUI
FROM runpod/worker-comfyui:5.2.0-base

# 1) Paquetes básicos + compiladores (IMPORTANTE: build-essential + clang)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    ca-certificates \
    build-essential \
    clang \
 && rm -rf /var/lib/apt/lists/*

# Triton por defecto busca CC, le marcamos clang
ENV CC=clang
ENV CXX=clang++

# 2) Custom nodes: FlashVSR + VideoHelperSuite
WORKDIR /comfyui/custom_nodes

# FlashVSR Ultra Fast
RUN git clone https://github.com/lihaoyun6/ComfyUI-FlashVSR_Ultra_Fast.git && \
    python3 -m pip install --no-cache-dir -r ComfyUI-FlashVSR_Ultra_Fast/requirements.txt

# VideoHelperSuite (carga/combina vídeo)
RUN git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    python3 -m pip install --no-cache-dir -r ComfyUI-VideoHelperSuite/requirements.txt

# 3) (Opcional) Modelos FlashVSR — los dejamos, aunque luego ComfyUI
#    también descarga 'FlashVSR-v1.1' automáticamente.
RUN mkdir -p /comfyui/models/FlashVSR
WORKDIR /comfyui/models/FlashVSR

RUN wget -O LQ_proj_in.ckpt "https://huggingface.co/JunhaoZhuang/FlashVSR/resolve/main/LQ_proj_in.ckpt" && \
    wget -O TCDecoder.ckpt "https://huggingface.co/JunhaoZhuang/FlashVSR/resolve/main/TCDecoder.ckpt" && \
    wget -O diffusion_pytorch_model_streaming_dmd.safetensors "https://huggingface.co/JunhaoZhuang/FlashVSR/resolve/main/diffusion_pytorch_model_streaming_dmd.safetensors" && \
    wget -O Wan2.1_VAE.pth "https://huggingface.co/JunhaoZhuang/FlashVSR/resolve/main/Wan2.1_VAE.pth"

# 4) Dependencias extra para el handler
RUN python3 -m pip install --no-cache-dir requests

# 5) Copiamos nuestro handler personalizado
WORKDIR /workspace
COPY handler.py /handler.py

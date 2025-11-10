FROM runpod/worker-comfyui:5.2.0-base
RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /comfyui/custom_nodes
RUN git clone https://github.com/lihaoyun6/ComfyUI-FlashVSR_Ultra_Fast.git && \
    python3 -m pip install --no-cache-dir -r ComfyUI-FlashVSR_Ultra_Fast/requirements.txt
RUN git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    python3 -m pip install --no-cache-dir -r ComfyUI-VideoHelperSuite/requirements.txt
RUN mkdir -p /comfyui/models/FlashVSR
WORKDIR /comfyui/models/FlashVSR
RUN wget -O LQ_proj_in.ckpt "https://huggingface.co/JunhaoZhuang/FlashVSR/resolve/main/LQ_proj_in.ckpt" && \
    wget -O TCDecoder.ckpt "https://huggingface.co/JunhaoZhuang/FlashVSR/resolve/main/TCDecoder.ckpt" && \
    wget -O diffusion_pytorch_model_streaming_dmd.safetensors "https://huggingface.co/JunhaoZhuang/FlashVSR/resolve/main/diffusion_pytorch_model_streaming_dmd.safetensors" && \
    wget -O Wan2.1_VAE.pth "https://huggingface.co/JunhaoZhuang/FlashVSR/resolve/main/Wan2.1_VAE.pth"
WORKDIR /workspace

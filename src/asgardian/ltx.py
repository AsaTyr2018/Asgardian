"""Validated native-60-fps LTX-2.3 image-to-video workflow."""

import math
from typing import Any


def _node(class_type: str, **inputs: Any) -> dict[str, Any]:
    return {"class_type": class_type, "inputs": inputs}


def video_dimensions(width: int, height: int) -> tuple[int, int]:
    """Maximize detail inside the validated 512-square LTX pixel budget.

    LTX's two-stage workflow needs final dimensions divisible by 64.  Searching
    the complete safe grid preserves the source aspect ratio more closely than
    capping only the longer edge at 512 pixels.  Landscape and portrait videos
    therefore gain useful resolution without exceeding the VRAM budget of the
    validated 512 x 512 run.
    """
    if width <= 0 or height <= 0:
        raise ValueError("video source dimensions must be positive")

    pixel_budget = 512 * 512
    source_ratio = width / height
    candidates: list[tuple[float, float, int, int]] = []
    for candidate_width in range(256, 1025, 64):
        for candidate_height in range(256, 1025, 64):
            area = candidate_width * candidate_height
            if area > pixel_budget:
                continue
            ratio_error = abs(math.log((candidate_width / candidate_height) / source_ratio))
            unused_budget = 1 - (area / pixel_budget)
            score = ratio_error + (unused_budget * 0.5)
            candidates.append((score, ratio_error, candidate_width, candidate_height))

    _, _, result_width, result_height = min(candidates)
    return result_width, result_height


def build_native_video_workflow(
    *, source_image: str, prompt: str, seed: int, width: int, height: int, output_prefix: str
) -> dict[str, Any]:
    frames = 721  # 12 seconds at 60 fps, including LTX's terminal frame.
    fps = 60
    checkpoint = "ltx2310eros_v1_FP8.safetensors"
    distilled = "ltx-2.3-22b-distilled-lora-384-1.1.safetensors"
    motion = "mdso/ltx-2-3-60-fps-buttery-smooth-motion-lora-ltx-2-3-.safetensors"
    return {
        "1": _node("LoadImage", image=source_image),
        "2": _node("CheckpointLoaderSimple", ckpt_name=checkpoint),
        "3": _node("LoraLoaderModelOnly", model=["2", 0], lora_name=distilled, strength_model=0.5),
        "4": _node("LoraLoaderModelOnly", model=["3", 0], lora_name=motion, strength_model=1.0),
        "37": _node("LTXVChunkFeedForward", model=["4", 0], chunks=2, dim_threshold=4096),
        "38": _node(
            "LTX2AttentionTunerPatch",
            model=["37", 0],
            blocks="",
            video_scale=1.0,
            audio_scale=1.0,
            audio_to_video_scale=1.0,
            video_to_audio_scale=1.0,
            triton_kernels=True,
        ),
        "5": _node(
            "LTXAVTextEncoderLoader",
            text_encoder="gemma_3_12B_it_fp8_e4m3fn.safetensors",
            ckpt_name=checkpoint,
            device="default",
        ),
        "6": _node("CLIPTextEncode", clip=["5", 0], text=f"buddr, {prompt}"),
        "7": _node(
            "CLIPTextEncode",
            clip=["5", 0],
            text=(
                "static pose, frozen body, duplicated limbs, malformed hands, frame skipping, "
                "temporal jitter, camera cuts, text, watermark"
            ),
        ),
        "8": _node("LTXVConditioning", positive=["6", 0], negative=["7", 0], frame_rate=60.0),
        "9": _node("LTXVAudioVAELoader", ckpt_name=checkpoint),
        "10": _node(
            "EmptyLTXVLatentVideo", width=width // 2, height=height // 2, length=frames, batch_size=1
        ),
        "11": _node(
            "LTXVEmptyLatentAudio", frames_number=frames, frame_rate=fps, batch_size=1, audio_vae=["9", 0]
        ),
        "12": _node(
            "ImageScale", image=["1", 0], upscale_method="lanczos", width=width, height=height, crop="center"
        ),
        "13": _node("LTXVPreprocess", image=["12", 0], img_compression=18),
        "14": _node(
            "LTXVImgToVideoInplace",
            vae=["2", 2],
            image=["13", 0],
            latent=["10", 0],
            strength=0.7,
            bypass=False,
        ),
        "15": _node("LTXVConcatAVLatent", video_latent=["14", 0], audio_latent=["11", 0]),
        "16": _node("RandomNoise", noise_seed=seed),
        "17": _node("CFGGuider", model=["38", 0], positive=["8", 0], negative=["8", 1], cfg=1.0),
        "18": _node("KSamplerSelect", sampler_name="euler_ancestral_cfg_pp"),
        "19": _node(
            "ManualSigmas", sigmas="1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
        ),
        "20": _node(
            "SamplerCustomAdvanced",
            noise=["16", 0],
            guider=["17", 0],
            sampler=["18", 0],
            sigmas=["19", 0],
            latent_image=["15", 0],
        ),
        "21": _node("LTXVSeparateAVLatent", av_latent=["20", 0]),
        "22": _node("LatentUpscaleModelLoader", model_name="ltx-2.3-spatial-upscaler-x2-1.1.safetensors"),
        "23": _node("LTXVLatentUpsampler", samples=["21", 0], upscale_model=["22", 0], vae=["2", 2]),
        "24": _node(
            "LTXVImgToVideoInplace",
            vae=["2", 2],
            image=["13", 0],
            latent=["23", 0],
            strength=1.0,
            bypass=False,
        ),
        "25": _node("LTXVCropGuides", positive=["8", 0], negative=["8", 1], latent=["21", 0]),
        "26": _node("LTXVConcatAVLatent", video_latent=["24", 0], audio_latent=["21", 1]),
        "27": _node("RandomNoise", noise_seed=seed + 1),
        "28": _node("CFGGuider", model=["38", 0], positive=["25", 0], negative=["25", 1], cfg=1.0),
        "29": _node("KSamplerSelect", sampler_name="euler_cfg_pp"),
        "30": _node("ManualSigmas", sigmas="0.85, 0.7250, 0.4219, 0.0"),
        "31": _node(
            "SamplerCustomAdvanced",
            noise=["27", 0],
            guider=["28", 0],
            sampler=["29", 0],
            sigmas=["30", 0],
            latent_image=["26", 0],
        ),
        "32": _node("LTXVSeparateAVLatent", av_latent=["31", 0]),
        "33": _node(
            "VAEDecodeTiled",
            samples=["32", 0],
            vae=["2", 2],
            tile_size=512,
            overlap=64,
            temporal_size=64,
            temporal_overlap=8,
        ),
        "34": _node("LTXVAudioVAEDecode", samples=["32", 1], audio_vae=["9", 0]),
        "35": _node("CreateVideo", images=["33", 0], audio=["34", 0], fps=60.0),
        "36": _node("SaveVideo", video=["35", 0], filename_prefix=output_prefix, format="mp4", codec="h264"),
    }

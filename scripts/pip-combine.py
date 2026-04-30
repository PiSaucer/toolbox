#!/usr/bin/env python3
# pip-combine.py
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.0

# Overlay an OVERLAY video on a BACKGROUND video with audio mix and smooth frame pacing
# Usage: python3 pip-combine.py --overlay Overlay.mp4 --background Background.mp4 [options]

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

CORNER_CHOICES = {
    "tl": ("0", "0"),
    "tr": ("(main_w-overlay_w)", "0"),
    "bl": ("0", "(main_h-overlay_h)"),
    "br": ("(main_w-overlay_w)", "(main_h-overlay_h)"),
}

def ensure_tool(name):
    if not shutil.which(name):
        sys.exit(f"Error: {name} not found in PATH. Install {name} and try again.")

def ffprobe_json(args):
    ensure_tool("ffprobe")
    out = subprocess.check_output(args, stderr=subprocess.STDOUT)
    return json.loads(out.decode("utf-8"))

def ffprobe_has_stream(path: Path, kind: str) -> bool:
    sel = "a" if kind == "audio" else "v"
    try:
        data = ffprobe_json([
            "ffprobe", "-v", "error", "-select_streams", sel,
            "-show_entries", "stream=index", "-of", "json", str(path)
        ])
        return bool(data.get("streams"))
    except subprocess.CalledProcessError:
        return False

def fraction_to_float(s: str) -> float:
    try:
        if "/" in s:
            n, d = s.split("/", 1)
            n = float(n)
            d = float(d)
            return 0.0 if d == 0 else n / d
        return float(s)
    except Exception:
        return 0.0

def ffprobe_fps(path: Path) -> float:
    try:
        data = ffprobe_json([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=avg_frame_rate,r_frame_rate",
            "-of", "json", str(path)
        ])
        s = (data.get("streams") or [{}])[0]
        for key in ("avg_frame_rate", "r_frame_rate"):
            if key in s and s[key]:
                fps = fraction_to_float(s[key])
                if fps > 0:
                    return fps
        return 0.0
    except subprocess.CalledProcessError:
        return 0.0

def prompt_if_missing(args):
    def ask_file(prompt_text, default=None):
        while True:
            p = input(f"{prompt_text}{' [' + default + ']' if default else ''}: ").strip() or (default or "")
            if p:
                return p

    if not args.overlay:
        args.overlay = ask_file("Path to OVERLAY picture-in-picture video", "Overlay.mp4")

    if not args.background:
        args.background = ask_file("Path to BACKGROUND main video", "Background.mp4")

    if not args.corner:
        print("Corner for overlay video: tl=top-left, tr=top-right, bl=bottom-left, br=bottom-right.")
        c = input("Choose corner [tr]: ").strip().lower() or "tr"
        if c not in CORNER_CHOICES:
            print("Unrecognized corner; defaulting to tr.")
            c = "tr"
        args.corner = c

    if not args.overlay_scale and args.scale_rel is None:
        s = input("Shrink OVERLAY video by what factor? [0.5]: ").strip()
        args.scale_rel = float(s) if s else 0.5

    return args

def build_video_chain(args, fps_overlay, fps_background):
    target_fps = float(args.target_fps) if args.target_fps else 30.0
    interp = args.interp

    # Build background chain
    bg_steps = []
    bg_in = "[1:v]"

    if interp != "off" and fps_background > 0 and fps_background < target_fps:
        if interp == "minterpolate":
            bg_steps.append(f"{bg_in}minterpolate=fps={target_fps}[bg_i]")
        else:
            bg_steps.append(f"{bg_in}fps={target_fps}[bg_i]")
        bg_in = "[bg_i]"

    w_bg, h_bg = map(int, args.bg_size.lower().split("x"))
    bg_steps.append(
        f"{bg_in}scale={w_bg}:{h_bg}:force_original_aspect_ratio=increase,"
        f"crop={w_bg}:{h_bg}[bg]"
    )

    # Build overlay chain
    overlay_steps = []
    overlay_in = "[0:v]"

    if interp != "off" and fps_overlay > 0 and fps_overlay < target_fps:
        if interp == "minterpolate":
            overlay_steps.append(f"{overlay_in}minterpolate=fps={target_fps}[overlay_i]")
        else:
            overlay_steps.append(f"{overlay_in}fps={target_fps}[overlay_i]")
        overlay_in = "[overlay_i]"

    # Scale overlay
    if args.overlay_scale:
        scale_value = args.overlay_scale if "x" in args.overlay_scale else f"{args.overlay_scale}:-1"
        overlay_steps.append(f"{overlay_in}scale={scale_value}:flags=lanczos[pip0]")
    else:
        rel = args.scale_rel if args.scale_rel is not None else args.overlay_rel
        overlay_steps.append(f"{overlay_in}scale=iw*{rel}:ih*{rel}:flags=lanczos[pip0]")

    # Corner with optional margin
    x_expr, y_expr = CORNER_CHOICES[args.corner]
    if args.margin and args.margin != 0:
        if x_expr == "0":
            x_expr = str(args.margin)
        elif x_expr == "(main_w-overlay_w)":
            x_expr = f"(main_w-overlay_w-{args.margin})"

        if y_expr == "0":
            y_expr = str(args.margin)
        elif y_expr == "(main_h-overlay_h)":
            y_expr = f"(main_h-overlay_h-{args.margin})"

    # Overlay and final fps normalize
    overlay_filter = f"[bg][pip0]overlay=x={x_expr}:y={y_expr}[vtmp]"
    fps_normalize = f"[vtmp]fps={target_fps}[vout]"

    return ";".join(bg_steps + overlay_steps + [overlay_filter, fps_normalize]), "[vout]"

def build_audio_chain(overlay_has_audio, background_has_audio, added_silence, mix_duration):
    audio_labels = []

    if overlay_has_audio:
        audio_labels.append("[0:a]")

    if background_has_audio:
        audio_labels.append("[1:a]")

    if added_silence:
        audio_labels.append("[2:a]")

    if len(audio_labels) == 0:
        return "[2:a]anull[aout]"

    if len(audio_labels) == 1:
        return f"{audio_labels[0]}aresample=async=1[aout]"

    return (
        f"{''.join(audio_labels)}"
        f"amix=inputs={len(audio_labels)}:duration={mix_duration}:dropout_transition=2,"
        f"aresample=async=1[aout]"
    )

def main():
    parser = argparse.ArgumentParser(description="Overlay an OVERLAY video on a BACKGROUND video with audio mix and smooth frame pacing.")
    parser.add_argument("--overlay", "-i", help="Path to overlay picture-in-picture video.")
    parser.add_argument("--background", "-b", help="Path to background main video.")
    parser.add_argument("--corner", "-c", choices=CORNER_CHOICES.keys(), default="tr", help="Corner: tl, tr, bl, br. Default: tr.")
    parser.add_argument("--overlay-scale", help="Fixed size for overlay, e.g. 640x480 or 640 for width only.")
    parser.add_argument("--scale-rel", type=float, default=None, help="Shrink factor relative to overlay's original size, e.g. 0.33.")
    parser.add_argument("--overlay-rel", type=float, default=0.5, help="Fallback relative scale if no --overlay-scale or --scale-rel.")
    parser.add_argument("--margin", type=int, default=0, help="Margin in pixels from edges. Default: 0.")
    parser.add_argument("--bg-size", default="1920x1080", help='Canvas size, e.g. "1920x1080".')
    parser.add_argument("--mix-duration", default="longest", choices=["first", "shortest", "longest"], help="amix duration behavior.")
    parser.add_argument("--interp", choices=["minterpolate", "dup", "off"], default="dup", help="How to raise low-FPS inputs to target fps. Default: dup.")
    parser.add_argument("--target-fps", type=float, default=30.0, help="Output/normalized FPS. Default: 30.")
    parser.add_argument("--crf", type=int, default=20, help="x264 CRF. Default: 20.")
    parser.add_argument("--preset", default="veryfast", help="x264 preset. Default: veryfast.")
    parser.add_argument("--output", "-o", default="output_overlay.mp4", help="Output filename.")
    parser.add_argument("--shortest", action="store_true",  help="End when the shortest input finishes.")
    parser.add_argument("--silence-rate", default="48000", help="Sample rate for injected silence if needed.")

    args = parser.parse_args()
    args = prompt_if_missing(args)

    if not Path(args.output).suffix:
        args.output += ".mp4"

    overlay_path = Path(args.overlay).expanduser()
    background_path = Path(args.background).expanduser()

    if not overlay_path.exists():
        sys.exit(f"Error: Overlay video not found: {overlay_path}")

    if not background_path.exists():
        sys.exit(f"Error: Background video not found: {background_path}")

    ensure_tool("ffmpeg")

    overlay_has_audio = ffprobe_has_stream(overlay_path, "audio")
    background_has_audio = ffprobe_has_stream(background_path, "audio")

    fps_overlay = ffprobe_fps(overlay_path)
    fps_background = ffprobe_fps(background_path)

    extra_inputs = []
    added_silence = False

    if not overlay_has_audio and not background_has_audio:
        extra_inputs = [
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=stereo:sample_rate={args.silence_rate}"
        ]
        added_silence = True

    v_chain, vout = build_video_chain(args, fps_overlay, fps_background)
    a_chain = build_audio_chain(
        overlay_has_audio,
        background_has_audio,
        added_silence,
        args.mix_duration
    )

    filtergraph = ";".join([v_chain, a_chain])

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(overlay_path),
        "-i", str(background_path),
        *extra_inputs,
        "-filter_complex", filtergraph,
        "-map", vout,
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", args.preset,
        "-crf", str(args.crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
    ]

    if args.shortest or added_silence:
        cmd.append("-shortest")

    cmd.append(str(args.output))

    print("\nRunning:\n", " ".join(cmd), "\n")

    try:
        subprocess.check_call(cmd)
        print(f"Done! Wrote: {args.output}")
    except subprocess.CalledProcessError as e:
        sys.exit(f"ffmpeg failed with exit code {e.returncode}")

if __name__ == "__main__":
    main()
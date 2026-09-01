#!/usr/bin/env python3
# pip_combine.py
# Copyright (c) 2026 PiSaucer
# Licensed under the MIT License
# Version 1.0.1

# Overlay an OVERLAY video on a BACKGROUND video with audio mix and smooth frame pacing
# Usage: python3 pip_combine.py --overlay Overlay.mp4 --background Background.mp4 [options]

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
    """Require an executable to be available on ``PATH``.

    Args:
        name: Executable name to locate.

    Raises:
        SystemExit: If the executable cannot be found.
    """
    if not shutil.which(name):
        sys.exit(f"Error: {name} not found in PATH. Install {name} and try again.")

def ffprobe_json(args):
    """Run ffprobe and decode its JSON output.

    Args:
        args: Complete ffprobe command and argument sequence.

    Returns:
        The decoded JSON value.

    Raises:
        SystemExit: If ffprobe is not available.
        subprocess.CalledProcessError: If ffprobe exits unsuccessfully.
        json.JSONDecodeError: If ffprobe output is not valid JSON.
    """
    ensure_tool("ffprobe")
    out = subprocess.check_output(args, stderr=subprocess.STDOUT)
    return json.loads(out.decode("utf-8"))

def ffprobe_has_stream(path: Path, kind: str) -> bool:
    """Check whether a media file contains an audio or video stream.

    Args:
        path: Media file to inspect.
        kind: ``audio`` to select audio; every other value selects video.

    Returns:
        ``True`` when ffprobe reports at least one selected stream, otherwise
        ``False``.

    Raises:
        SystemExit: If ffprobe is not available.
    """
    # ffprobe uses single-letter stream selectors.
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
    """Convert a number or fractional string to a float.

    Args:
        s: Numeric text such as ``29.97`` or ``30000/1001``.

    Returns:
        The parsed value, or ``0.0`` for invalid input or a zero denominator.
    """
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
    """Read the best available video frame rate from a media file.

    Args:
        path: Media file to inspect.

    Returns:
        A positive frame rate, or ``0.0`` when probing or parsing fails.

    Raises:
        SystemExit: If ffprobe is not available.
    """
    try:
        data = ffprobe_json([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=avg_frame_rate,r_frame_rate",
            "-of", "json", str(path)
        ])
        s = (data.get("streams") or [{}])[0]
        
        # Prefer the average rate; fall back to the declared real/base rate.
        for key in ("avg_frame_rate", "r_frame_rate"):
            if key in s and s[key]:
                fps = fraction_to_float(s[key])
                if fps > 0:
                    return fps
        return 0.0
    except subprocess.CalledProcessError:
        return 0.0

def prompt_if_missing(args):
    """Interactively fill media and layout options missing from parsed arguments.

    Args:
        args: Argparse namespace to update in place.

    Returns:
        The updated namespace.

    Raises:
        EOFError: If interactive input ends before a required answer is given.
        ValueError: If the entered relative scale is not numeric.
    """
    def ask_file(prompt_text, default=None):
        """Prompt until the user supplies a file path.

        Args:
            prompt_text: Label shown before the input field.
            default: Value used when the user submits an empty response.

        Returns:
            A nonempty path string.

        Raises:
            EOFError: If standard input closes while prompting.
        """
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
    """Build the ffmpeg picture-in-picture video filtergraph.

    Args:
        args: Parsed layout, sizing, interpolation, and frame-rate options.
        fps_overlay: Detected overlay input frame rate.
        fps_background: Detected background input frame rate.

    Returns:
        A tuple containing the filtergraph fragment and final video pad label.

    Raises:
        ValueError: If frame-rate or background-size values are invalid.
        KeyError: If the selected corner is not in ``CORNER_CHOICES``.
    """
    target_fps = float(args.target_fps) if args.target_fps else 30.0
    interp = args.interp

    # Build background chain
    bg_steps = []
    bg_in = "[1:v]"

    # Raise only low-frame-rate inputs; the final fps filter normalizes both
    # streams after composition.
    if interp != "off" and fps_background > 0 and fps_background < target_fps:
        if interp == "minterpolate":
            bg_steps.append(f"{bg_in}minterpolate=fps={target_fps}[bg_i]")
        else:
            bg_steps.append(f"{bg_in}fps={target_fps}[bg_i]")
        bg_in = "[bg_i]"

    # Fill the canvas while preserving aspect ratio, then crop any overflow.
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
    """Build the ffmpeg audio-selection and mixing filtergraph.

    Args:
        overlay_has_audio: Whether input zero has an audio stream.
        background_has_audio: Whether input one has an audio stream.
        added_silence: Whether input two is an injected silent audio source.
        mix_duration: ffmpeg ``amix`` duration policy.

    Returns:
        A filtergraph fragment producing the ``[aout]`` audio pad.
    """
    audio_labels = []

    if overlay_has_audio:
        audio_labels.append("[0:a]")

    if background_has_audio:
        audio_labels.append("[1:a]")

    if added_silence:
        audio_labels.append("[2:a]")

    # Input two is the synthetic silence source when neither video has audio.
    if len(audio_labels) == 0:
        return "[2:a]anull[aout]"

    # A single stream still gets asynchronous resampling for timestamp drift.
    if len(audio_labels) == 1:
        return f"{audio_labels[0]}aresample=async=1[aout]"

    return (
        f"{''.join(audio_labels)}"
        f"amix=inputs={len(audio_labels)}:duration={mix_duration}:dropout_transition=2,"
        f"aresample=async=1[aout]"
    )

def main():
    """Parse options and run the picture-in-picture ffmpeg command.

    Raises:
        SystemExit: If dependencies or inputs are missing, or ffmpeg exits
            unsuccessfully.
        EOFError: If interactive input closes while required values are read.
        ValueError: If an interactive or sizing value is invalid.
    """
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

    # Always map an audio output. Inject silence when neither source supplies it.
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

    # Video and audio chains share one filter_complex graph and expose named pads.
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

    # An infinite synthetic silence input must be bounded by the video duration.
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

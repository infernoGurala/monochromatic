"""Ranking video clipper.

Cuts each rank segment, burns:
  - Centered rank number overlay (#10, #9, …, #1) via ffmpeg drawtext
  - Progress indicator (10/10, 9/10, …, 1/10) in top corner
  - Subtitle captions from existing ASS engine

Then concatenates all clips in countdown order into final 9:16 MP4.
"""
import os
import subprocess
import tempfile
from typing import Dict, List, Optional

from ..config import get_local_output_dir


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ratio_to_wh(aspect_ratio: str):
    """Convert '9:16' → (9, 16)."""
    try:
        w, h = aspect_ratio.split(":")
        return int(w), int(h)
    except Exception:
        return 9, 16


def _get_video_dims(video_path: str):
    """Get (width, height) of video via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        video_path
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
        w, h = out.split("x")
        return int(w), int(h)
    except Exception:
        return 1920, 1080


def _center_crop_filter(src_w: int, src_h: int, target_ratio_w: int, target_ratio_h: int) -> str:
    """Build ffmpeg crop filter string for center crop to target aspect ratio."""
    target_ratio = target_ratio_w / target_ratio_h
    if (src_w / src_h) > target_ratio:
        crop_h = src_h
        crop_w = int(crop_h * target_ratio)
    else:
        crop_w = src_w
        crop_h = int(crop_w / target_ratio)
    crop_w = max(2, crop_w - crop_w % 2)
    crop_h = max(2, crop_h - crop_h % 2)
    x = (src_w - crop_w) // 2
    y = (src_h - crop_h) // 2
    return f"crop={crop_w}:{crop_h}:{x}:{y}"


def _cut_clip(source: str, start: float, end: float, out: str) -> str:
    """Cut a subclip from source video."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-i", source,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        out
    ]
    subprocess.run(cmd, check=True)
    return out


# ── ASS subtitle generation (re-used from local/clipper.py pattern) ──────────

def _generate_rank_ass(
    words: List[dict],
    start_offset: float,
    duration: float,
    ass_path: str,
    font_name: str = "Impact",
    font_size: int = 52,
    active_color: str = "yellow",
    text_case: str = "upper",
):
    """Generate ASS subtitle file for a rank clip (re-uses existing engine)."""
    from ..clipper import _generate_ass_file
    _generate_ass_file(
        words, start_offset, duration, ass_path,
        font_name=font_name, font_size=font_size,
        active_color=active_color, text_case=text_case
    )


# ── Rank Overlay ─────────────────────────────────────────────────────────────

def _build_rank_clip(
    source: str,
    segment: Dict,
    total_ranks: int,
    out_path: str,
    aspect_ratio: str,
    overlay_style: str,   # "large" / "minimal" / "none"
    all_words: List[dict],
    ass_path: Optional[str],
    enable_subtitles: bool,
    caption_font: str,
    caption_size: int,
    caption_color: str,
    caption_case: str,
) -> str:
    """Cut one rank segment and burn overlays."""
    rank = segment["rank"]
    start = segment["start_time"]
    end = segment["end_time"]
    duration = end - start
    pos = total_ranks - rank + 1  # countdown position label (1/10 = rank 10)

    # 1. Cut subclip
    cut_path = out_path + ".cut.mp4"
    _cut_clip(source, start, end, cut_path)

    # 2. Build subtitle ASS
    has_ass = False
    if enable_subtitles and all_words and ass_path:
        try:
            _generate_rank_ass(
                all_words, start, duration, ass_path,
                font_name=caption_font, font_size=caption_size,
                active_color=caption_color, text_case=caption_case,
            )
            has_ass = True
        except Exception as e:
            print(f"[ranking/clipper] ASS failed for rank {rank}: {e}", flush=True)

    # 3. Get source dims for crop
    src_w, src_h = _get_video_dims(cut_path)
    ratio_w, ratio_h = _ratio_to_wh(aspect_ratio)
    crop_filter = _center_crop_filter(src_w, src_h, ratio_w, ratio_h)

    # Compute output dims
    if (src_w / src_h) > (ratio_w / ratio_h):
        out_h = src_h
        out_w = int(out_h * ratio_w / ratio_h)
    else:
        out_w = src_w
        out_h = int(out_w * ratio_h / ratio_w)
    out_w = max(2, out_w - out_w % 2)
    out_h = max(2, out_h - out_h % 2)

    # 4. Build ffmpeg filter chain
    filters = [crop_filter, f"scale={out_w}:{out_h}"]

    # Subtitle overlay
    if has_ass:
        escaped = ass_path.replace("\\", "/").replace(":", "\\:")
        filters.append(f"ass={escaped}")

    # Rank number overlay
    if overlay_style in ("large", "minimal"):
        font_sz = 160 if overlay_style == "large" else 90
        rank_text = f"#{rank}"
        rank_y = "h/2-text_h/2" if overlay_style == "large" else "h*0.08"
        filters.append(
            f"drawtext=text='{rank_text}':fontsize={font_sz}:fontcolor=white"
            f":x=(w-text_w)/2:y={rank_y}"
            f":shadowx=5:shadowy=5:shadowcolor=black@0.8"
            f":box=1:boxcolor=black@0.35:boxborderw=12"
        )
        # Progress indicator top-right
        progress_text = f"{pos}/{total_ranks}"
        filters.append(
            f"drawtext=text='{progress_text}':fontsize=36:fontcolor=white@0.9"
            f":x=w-text_w-24:y=32"
            f":shadowx=3:shadowy=3:shadowcolor=black@0.7"
        )

    filter_str = ",".join(filters)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", cut_path,
        "-vf", filter_str,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-r", "60",
        out_path
    ]
    subprocess.run(cmd, check=True)

    if os.path.exists(cut_path):
        os.remove(cut_path)

    return out_path


def _concat_clips(clip_paths: List[str], out_path: str) -> str:
    """Concatenate multiple MP4 clips using ffmpeg concat demuxer."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")
        list_path = f.name

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-r", "60",
        out_path
    ]
    subprocess.run(cmd, check=True)
    os.unlink(list_path)
    return out_path


# ── Public API ────────────────────────────────────────────────────────────────

def crop_ranking_clips(
    source_path: str,
    segments: List[Dict],           # countdown-ordered: #10 → #1
    transcript: Dict,
    aspect_ratio: str = "9:16",
    out_dir: Optional[str] = None,
    overlay_style: str = "large",   # "large" / "minimal" / "none"
    enable_subtitles: bool = True,
    caption_font: str = "Impact",
    caption_size: int = 52,
    caption_color: str = "yellow",
    caption_case: str = "upper",
    max_duration: float = 60.0,
) -> Dict:
    """Build individual rank clips and concatenate into final countdown MP4.

    Returns:
        {
          "clip_url": "/output/ranking_short.mp4",
          "segments": [...],   # processed segments with timecodes
          "total_ranks": N,
          "mode": "ranking"
        }
    """
    out_dir = out_dir or get_local_output_dir()
    os.makedirs(out_dir, exist_ok=True)

    # Gather all word-level timestamps from transcript
    all_words = []
    for s in transcript.get("segments", []):
        all_words.extend(s.get("words", []))

    total_ranks = len(segments)
    clip_paths = []
    processed_segments = []

    for i, seg in enumerate(segments, 1):
        try:
            from app import task_manager
            if task_manager.cancelled:
                raise RuntimeError("Cancelled by user")
        except ImportError:
            pass

        rank = seg["rank"]
        print(f"[ranking/clipper] {i}/{total_ranks} — rank #{rank}", flush=True)

        clip_out = os.path.join(out_dir, f"rank_{rank:03d}.mp4")
        ass_path = os.path.join(out_dir, f"rank_{rank:03d}.ass") if enable_subtitles else None

        try:
            _build_rank_clip(
                source=source_path,
                segment=seg,
                total_ranks=total_ranks,
                out_path=clip_out,
                aspect_ratio=aspect_ratio,
                overlay_style=overlay_style,
                all_words=all_words,
                ass_path=ass_path,
                enable_subtitles=enable_subtitles,
                caption_font=caption_font,
                caption_size=caption_size,
                caption_color=caption_color,
                caption_case=caption_case,
            )
            clip_paths.append(clip_out)
            processed_segments.append({**seg, "clip_url": clip_out})
        except Exception as e:
            print(f"[ranking/clipper] rank #{rank} failed: {e}", flush=True)
            processed_segments.append({**seg, "clip_url": None, "error": str(e)})
        finally:
            if ass_path and os.path.exists(ass_path):
                try:
                    os.remove(ass_path)
                except OSError:
                    pass

    # Concatenate successful clips
    valid_clips = [p for p in clip_paths if os.path.exists(p)]
    final_out = os.path.join(out_dir, "ranking_short.mp4")

    if not valid_clips:
        raise RuntimeError("All ranking clips failed to render.")

    print(f"[ranking/clipper] concatenating {len(valid_clips)} clips…", flush=True)
    _concat_clips(valid_clips, final_out)

    # Cleanup individual rank clips
    for p in valid_clips:
        try:
            os.remove(p)
        except OSError:
            pass

    return {
        "clip_url": final_out,
        "segments": processed_segments,
        "total_ranks": total_ranks,
        "mode": "ranking",
    }

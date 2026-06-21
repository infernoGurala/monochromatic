"""Local clipping: ffmpeg subclip + OpenCV face-aware vertical crop + burn-in subtitles.

Two stages per highlight:
  1. Cut the source video to [start, end] with ffmpeg (re-encoded, audio kept).
  2. Reframe the cut to the target aspect ratio.
     - If face_tracking is enabled: OpenCV face tracking + burn-in subtitles.
     - If face_tracking is disabled: High-speed ffmpeg center crop + burn-in subtitles.
"""
import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple

from .config import get_local_output_dir


def _ratio(aspect_ratio: str) -> float:
    """Parse '9:16' → 9/16, '1:1' → 1.0."""
    try:
        w, h = aspect_ratio.split(":")
        return float(w) / float(h)
    except (ValueError, ZeroDivisionError):
        return 9.0 / 16.0


def _cut_subclip(source_path: str, start: float, end: float, out_path: str) -> str:
    """ffmpeg -ss start -to end → re-encoded mp4 with audio."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", source_path,
        "-ss", f"{start:.3f}",
        "-to", f"{end:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def _format_ass_time(seconds: float) -> str:
    """Format seconds into ASS time format: H:MM:SS.cs"""
    total_cs = max(0, int(round(seconds * 100)))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _generate_ass_file(
    words: List[dict],
    start_offset: float,
    duration: float,
    ass_path: str,
    font_name: str = "Impact",
    font_size: int = 52,
    active_color: str = "yellow",
    text_case: str = "upper",
):
    """Generate an Advanced SubStation Alpha (ASS) file with active word-level coloring."""
    # Filter and adjust word timestamps
    clip_words = []
    for w in words:
        w_start = w["start"] - start_offset
        w_end = w["end"] - start_offset
        if w_start >= -0.5 and w_end <= duration + 0.5:
            clip_words.append({
                "start": max(0.0, w_start),
                "end": min(duration, w_end),
                "word": w["word"]
            })

    # Group words into chunks of up to 3 words
    chunks = []
    current_chunk = []
    for w in clip_words:
        if len(current_chunk) >= 3:
            chunks.append(current_chunk)
            current_chunk = [w]
        elif current_chunk and (w["start"] - current_chunk[-1]["end"]) > 0.8:
            chunks.append(current_chunk)
            current_chunk = [w]
        else:
            current_chunk.append(w)
    if current_chunk:
        chunks.append(current_chunk)

    # Active word color lookup
    color_map = {
        "yellow": "&H0000FFFF&",
        "green": "&H0000FF00&",
        "cyan": "&H00FFFF00&",
        "red": "&H000000FF&",
        "purple": "&H00FF007F&",
        "white": "&H00FFFFFF&"
    }
    active_color_ass = color_map.get(active_color.lower(), "&H0000FFFF&")

    # Sanitize font inputs
    font_name_clean = "".join(c for c in font_name if c.isalnum() or c in " -_").strip() or "Impact"
    font_size_val = max(10, min(120, font_size))

    # Build dialogue lines
    dialogue_lines = []
    for chunk_idx, chunk in enumerate(chunks):
        chunk_start = chunk[0]["start"]
        if chunk_idx < len(chunks) - 1:
            chunk_end = chunks[chunk_idx + 1][0]["start"]
        else:
            chunk_end = max(chunk[-1]["end"], duration)

        for w_idx, active_word in enumerate(chunk):
            frame_start = chunk_start if w_idx == 0 else active_word["start"]
            if w_idx < len(chunk) - 1:
                frame_end = chunk[w_idx + 1]["start"]
            else:
                frame_end = chunk_end

            text_parts = []
            for other_w in chunk:
                word_str = other_w['word']
                if text_case == "upper":
                    word_str = word_str.upper()

                if other_w == active_word:
                    text_parts.append(f"{{\\c{active_color_ass}}}{word_str}{{\\c}}")
                else:
                    text_parts.append(word_str)

            subtitle_text = " ".join(text_parts)
            start_fmt = _format_ass_time(frame_start)
            end_fmt = _format_ass_time(frame_end)
            dialogue_lines.append(f"Dialogue: 0,{start_fmt},{end_fmt},Default,,0,0,0,,{subtitle_text}")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name_clean},{font_size_val},&H00FFFFFF,&H0000FFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,0,2,30,30,520,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header)
        for line in dialogue_lines:
            f.write(line + "\n")


def _reframe_vertical(in_path: str, out_path: str, aspect_ratio: str, ass_path: Optional[str] = None) -> str:
    """Crop the cut clip to the target aspect ratio, tracking faces if possible."""
    try:
        import cv2  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "opencv-python is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    target_ratio = _ratio(aspect_ratio)
    cap = cv2.VideoCapture(in_path)
    if not cap.isOpened():
        raise RuntimeError(f"could not open {in_path}")

    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    # Compute the largest crop that fits inside the frame at the target ratio.
    if target_ratio < src_w / src_h:
        crop_h = src_h
        crop_w = int(crop_h * target_ratio)
    else:
        crop_w = src_w
        crop_h = int(crop_w / target_ratio)
    crop_w = max(2, crop_w - (crop_w % 2))
    crop_h = max(2, crop_h - (crop_h % 2))

    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    silent_path = out_path + ".silent.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(silent_path, fourcc, fps, (crop_w, crop_h))

    last_center: Optional[Tuple[int, int]] = None
    smoothing = 0.15  # how aggressively to chase a new face position
    while True:
        from .config import is_cancelled
        if is_cancelled():
            raise RuntimeError("Vertical reframing cancelled by user.")
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        if len(faces) > 0:
            # Pick the largest face — usually the speaker.
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            cx = x + w // 2
            cy = y + h // 2
            if last_center is None:
                last_center = (cx, cy)
            else:
                lx, ly = last_center
                last_center = (
                    int(lx + (cx - lx) * smoothing),
                    int(ly + (cy - ly) * smoothing),
                )
        if last_center is None:
            last_center = (src_w // 2, src_h // 2)

        cx, cy = last_center
        x0 = max(0, min(src_w - crop_w, cx - crop_w // 2))
        y0 = max(0, min(src_h - crop_h, cy - crop_h // 2))
        cropped = frame[y0:y0 + crop_h, x0:x0 + crop_w]
        writer.write(cropped)

    cap.release()
    writer.release()

    # Mux audio and burn in subtitles if ASS file is available
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", silent_path,
        "-i", in_path,
    ]
    if ass_path and os.path.exists(ass_path):
        cmd.extend(["-vf", f"ass={ass_path}"])

    cmd.extend([
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-map", "0:v:0", "-map", "1:a:0?",
        "-shortest",
        out_path,
    ])
    
    subprocess.run(cmd, check=True)
    os.remove(silent_path)
    return out_path


def _reframe_center_ffmpeg(in_path: str, out_path: str, aspect_ratio: str, ass_path: Optional[str] = None) -> str:
    """High-speed center crop via ffmpeg (avoids OpenCV and prevents segmentation faults)."""
    target_ratio = _ratio(aspect_ratio)
    
    src_w, src_h = 1280, 720
    try:
        import cv2  # type: ignore
        cap = cv2.VideoCapture(in_path)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if w > 0 and h > 0:
                src_w, src_h = w, h
        cap.release()
    except Exception:
        pass

    if target_ratio < src_w / src_h:
        crop_h = src_h
        crop_w = int(crop_h * target_ratio)
    else:
        crop_w = src_w
        crop_h = int(crop_w / target_ratio)
        
    crop_w = max(2, crop_w - (crop_w % 2))
    crop_h = max(2, crop_h - (crop_h % 2))
    
    x = (src_w - crop_w) // 2
    y = (src_h - crop_h) // 2
    
    filters = [f"crop={crop_w}:{crop_h}:{x}:{y}"]
    if ass_path and os.path.exists(ass_path):
        filters.append(f"ass={ass_path}")
        
    filter_str = ",".join(filters)
    
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", in_path,
        "-vf", filter_str,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        out_path
    ]
    subprocess.run(cmd, check=True)
    return out_path


def crop_clip_local(
    source_path: str,
    start_time: float,
    end_time: float,
    aspect_ratio: str,
    out_path: str,
    ass_path: Optional[str] = None,
    face_tracking: bool = False,
) -> str:
    """Cut + reframe one highlight, returning the local mp4 path."""
    cut_path = out_path + ".cut.mp4"
    try:
        _cut_subclip(source_path, start_time, end_time, cut_path)
        if face_tracking:
            _reframe_vertical(cut_path, out_path, aspect_ratio, ass_path=ass_path)
        else:
            _reframe_center_ffmpeg(cut_path, out_path, aspect_ratio, ass_path=ass_path)
    finally:
        if os.path.exists(cut_path):
            os.remove(cut_path)
    return out_path


def crop_highlights_local(
    source_path: str,
    highlights: List[Dict],
    transcript: Dict,
    aspect_ratio: str = "9:16",
    out_dir: Optional[str] = None,
    face_tracking: bool = False,
    caption_font: str = "Impact",
    caption_size: int = 52,
    caption_color: str = "yellow",
    caption_case: str = "upper",
    enable_subtitles: bool = True,
) -> List[Dict]:
    out_dir = out_dir or get_local_output_dir()
    os.makedirs(out_dir, exist_ok=True)

    # Gather all words from transcript segments
    all_words = []
    for s in transcript.get("segments", []):
        all_words.extend(s.get("words", []))

    results: List[Dict] = []
    for i, h in enumerate(highlights, 1):
        from .config import is_cancelled
        if is_cancelled():
            raise RuntimeError("Clipping cancelled by user.")
        out_path = os.path.join(out_dir, f"short_{i:02d}.mp4")
        ass_path = os.path.join(out_dir, f"short_{i:02d}.ass")
        print(f"[clip/local] {i}/{len(highlights)}: {h.get('title', '(untitled)')}", flush=True)

        has_subtitles = False
        if enable_subtitles and all_words:
            try:
                _generate_ass_file(
                    all_words,
                    float(h["start_time"]),
                    float(h["end_time"]) - float(h["start_time"]),
                    ass_path,
                    font_name=caption_font,
                    font_size=caption_size,
                    active_color=caption_color,
                    text_case=caption_case
                )
                has_subtitles = True
            except Exception as e:
                print(f"[clip/local] failed to generate ASS for clip {i}: {e}", flush=True)

        try:
            crop_clip_local(
                source_path,
                float(h["start_time"]),
                float(h["end_time"]),
                aspect_ratio,
                out_path,
                ass_path=ass_path if has_subtitles else None,
                face_tracking=face_tracking
            )
            results.append({**h, "clip_url": out_path})
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[clip/local] {i} failed: {e}", flush=True)
            results.append({**h, "clip_url": None, "error": str(e)})
        finally:
            if os.path.exists(ass_path):
                try:
                    os.remove(ass_path)
                except OSError:
                    pass
    return results

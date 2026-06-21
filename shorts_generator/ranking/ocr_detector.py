"""OCR-based rank number detection from video frames.

Samples 1 frame per second, runs EasyOCR to detect patterns like:
  #10  #9  10/20  No.10  Rank 10

Returns a list of {rank, frame_time} detections that are then merged
into time-ranges by the builder module.
"""
import re
import os
import subprocess
import tempfile
from typing import List, Dict, Optional

# Regex patterns to detect ranking numbers in OCR text
_RANK_PATTERNS = [
    r"#\s*(\d{1,3})",           # #10  # 5
    r"(?:no|rank|place|position)\.?\s*(\d{1,3})",  # No.10 Rank 5
    r"(\d{1,3})\s*/\s*\d{1,3}",  # 10/20
    r"^(\d{1,3})$",              # bare number on its own line
    r"\b(\d{1,3})\s*(?:th|st|nd|rd)\b",  # 10th 1st 2nd
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _RANK_PATTERNS]


def _extract_rank_from_text(text: str) -> Optional[int]:
    """Return the first rank number found in OCR text, or None."""
    for pat in _COMPILED:
        m = pat.search(text)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 500:   # sanity filter
                return val
    return None


def _sample_frame(video_path: str, timestamp: float, out_path: str) -> bool:
    """Extract a single frame from video at timestamp seconds via ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{timestamp:.3f}",
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        out_path
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0 and os.path.exists(out_path)


def _get_video_duration(video_path: str) -> float:
    """Get video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def detect_ranks_ocr(
    video_path: str,
    sample_interval: float = 1.0,
    max_rank: int = 100,
) -> List[Dict]:
    """Detect rank numbers in video frames using EasyOCR.

    Args:
        video_path: Path to source video file.
        sample_interval: Sample one frame every N seconds (default 1.0).
        max_rank: Maximum rank number to consider valid.

    Returns:
        List of {rank: int, frame_time: float} sorted by frame_time.
        Falls back to empty list if EasyOCR is not installed.
    """
    try:
        import easyocr  # type: ignore
    except ImportError:
        print("[ranking/ocr] easyocr not installed — install with: pip install easyocr", flush=True)
        return []

    duration = _get_video_duration(video_path)
    if duration <= 0:
        print(f"[ranking/ocr] could not determine duration of {video_path}", flush=True)
        return []

    print(f"[ranking/ocr] initializing EasyOCR reader…", flush=True)
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)

    detections: List[Dict] = []
    n_frames = max(1, int(duration / sample_interval))

    print(f"[ranking/ocr] scanning {n_frames} frames over {duration:.0f}s…", flush=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        for i in range(n_frames):
            try:
                from app import task_manager
                if task_manager.cancelled:
                    raise RuntimeError("Cancelled by user")
            except ImportError:
                pass

            ts = i * sample_interval
            frame_path = os.path.join(tmp_dir, f"frame_{i:05d}.jpg")

            if not _sample_frame(video_path, ts, frame_path):
                continue

            try:
                results = reader.readtext(frame_path, detail=0, paragraph=False)
                text_block = " ".join(str(r) for r in results)
                rank = _extract_rank_from_text(text_block)
                if rank is not None and rank <= max_rank:
                    detections.append({"rank": rank, "frame_time": ts})
            except Exception as e:
                pass  # silently skip failed frames

    print(f"[ranking/ocr] found {len(detections)} rank detections", flush=True)
    return sorted(detections, key=lambda x: x["frame_time"])


def group_rank_detections(detections: List[Dict], gap_threshold: float = 3.0) -> List[Dict]:
    """Merge consecutive frame detections of the same rank into time ranges.

    Args:
        detections: Sorted list of {rank, frame_time} from detect_ranks_ocr.
        gap_threshold: Max seconds gap to consider same rank segment.

    Returns:
        List of {rank, start_time, end_time} for each unique rank occurrence.
    """
    if not detections:
        return []

    groups: List[Dict] = []
    current = {
        "rank": detections[0]["rank"],
        "start_time": detections[0]["frame_time"],
        "end_time": detections[0]["frame_time"],
    }

    for det in detections[1:]:
        if det["rank"] == current["rank"] and (det["frame_time"] - current["end_time"]) <= gap_threshold:
            current["end_time"] = det["frame_time"]
        else:
            # Extend end_time by a small margin
            current["end_time"] = min(current["end_time"] + 1.0, current["end_time"] + gap_threshold * 0.5)
            groups.append(current)
            current = {
                "rank": det["rank"],
                "start_time": det["frame_time"],
                "end_time": det["frame_time"],
            }

    current["end_time"] = current["end_time"] + 1.0
    groups.append(current)

    # Deduplicate: keep only first occurrence of each rank
    seen = {}
    unique = []
    for g in sorted(groups, key=lambda x: x["rank"]):
        if g["rank"] not in seen:
            seen[g["rank"]] = g
            unique.append(g)

    return sorted(unique, key=lambda x: x["rank"], reverse=True)  # highest rank first

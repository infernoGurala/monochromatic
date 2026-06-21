"""Viral scoring engine for movie scenes.

Calculates a composite 0–100 viral score per scene based on:
  Audio Energy (25%) + Motion Score (25%) + Face Count (20%)
  + Dialogue Density (10%) + Visual Variety (10%) + Length Penalty (10%)
"""
import os
import subprocess
import math
from typing import Dict, List, Optional

try:
    import numpy as np  # type: ignore
    _HAS_NP = True
except ImportError:
    _HAS_NP = False

try:
    import cv2  # type: ignore
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


# ── Audio Energy ──────────────────────────────────────────────────────────────

def _score_audio_energy(video_path: str, start: float, end: float) -> float:
    """Calculate normalized RMS audio energy for a scene window (0–1)."""
    duration = end - start
    if duration <= 0:
        return 0.0
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-i", video_path,
        "-af", "astats=metadata=1:reset=1,ametadata=print:file=-:key=lavfi.astats.Overall.RMS_level",
        "-f", "null", "-"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        lines = result.stderr + result.stdout
        rms_vals = []
        for line in lines.split("\n"):
            if "RMS_level" in line and "=" in line:
                try:
                    val = float(line.split("=")[-1].strip())
                    if not math.isinf(val) and not math.isnan(val):
                        rms_vals.append(val)
                except ValueError:
                    pass
        if not rms_vals:
            return 0.3  # neutral default
        avg_rms = sum(rms_vals) / len(rms_vals)
        # RMS_level is in dBFS, typically -60 to 0. Normalize.
        normalized = (avg_rms + 60.0) / 60.0
        return max(0.0, min(1.0, normalized))
    except Exception:
        return 0.3


# ── Motion Score ──────────────────────────────────────────────────────────────

def _score_motion(video_path: str, start: float, end: float, sample_fps: float = 2.0) -> float:
    """OpenCV optical flow mean magnitude normalized to 0–1."""
    if not _HAS_CV2 or not _HAS_NP:
        return 0.3
    try:
        cap = cv2.VideoCapture(video_path)
        vid_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        step = max(1, int(vid_fps / sample_fps))
        start_frame = int(start * vid_fps)
        end_frame = int(end * vid_fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        prev_gray = None
        magnitudes = []
        frame_idx = start_frame

        while frame_idx <= end_frame:
            ret, frame = cap.read()
            if not ret:
                break
            if (frame_idx - start_frame) % step == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if prev_gray is not None:
                    flow = cv2.calcOpticalFlowFarneback(
                        prev_gray, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0
                    )
                    mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                    magnitudes.append(float(np.mean(mag)))
                prev_gray = gray
            frame_idx += 1

        cap.release()
        if not magnitudes:
            return 0.3
        avg_mag = sum(magnitudes) / len(magnitudes)
        # Clamp: typical motion 0–15 pixels/frame
        return max(0.0, min(1.0, avg_mag / 15.0))
    except Exception:
        return 0.3


# ── Face Detection ─────────────────────────────────────────────────────────────

def _score_faces(video_path: str, start: float, end: float) -> float:
    """Sample a single frame and count faces via Haar cascade (0–1)."""
    if not _HAS_CV2:
        return 0.3
    try:
        cap = cv2.VideoCapture(video_path)
        mid = (start + end) / 2.0
        vid_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(mid * vid_fps))
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return 0.2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)
        faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(30, 30))
        n = len(faces)
        # Score: 0 faces = 0.1, 1 face = 0.6, 2+ faces = 0.9
        if n == 0:
            return 0.15
        elif n == 1:
            return 0.65
        else:
            return min(1.0, 0.65 + (n - 1) * 0.1)
    except Exception:
        return 0.3


# ── Dialogue Density ──────────────────────────────────────────────────────────

def _score_dialogue(transcript: Dict, start: float, end: float) -> float:
    """Count transcript segments in window — dense dialogue = higher score (0–1)."""
    window = end - start
    if window <= 0:
        return 0.0
    segs_in = 0
    total_words = 0
    for seg in transcript.get("segments", []):
        s, e = float(seg.get("start", 0)), float(seg.get("end", 0))
        if e >= start and s <= end:
            segs_in += 1
            total_words += len((seg.get("text") or "").split())
    words_per_sec = total_words / window
    # Target: 2.5 words/sec = 1.0 score
    return max(0.0, min(1.0, words_per_sec / 2.5))


# ── Visual Variety ────────────────────────────────────────────────────────────

def _score_visual_variety(video_path: str, start: float, end: float) -> float:
    """Sample 3 frames and measure color histogram distance (0–1)."""
    if not _HAS_CV2 or not _HAS_NP:
        return 0.5
    try:
        cap = cv2.VideoCapture(video_path)
        vid_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        timestamps = [start, (start + end) / 2, end - 0.5]
        hists = []
        for ts in timestamps:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * vid_fps))
            ret, frame = cap.read()
            if ret:
                hist = cv2.calcHist([frame], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
                cv2.normalize(hist, hist)
                hists.append(hist.flatten())
        cap.release()
        if len(hists) < 2:
            return 0.5
        dists = []
        for i in range(len(hists) - 1):
            d = float(np.linalg.norm(hists[i] - hists[i + 1]))
            dists.append(d)
        avg_dist = sum(dists) / len(dists)
        return max(0.0, min(1.0, avg_dist / 5.0))
    except Exception:
        return 0.5


# ── Length Penalty ────────────────────────────────────────────────────────────

def _score_length(duration: float, ideal_min: float = 15.0, ideal_max: float = 55.0) -> float:
    """Score scene duration — ideal window 15–55 seconds (0–1)."""
    if ideal_min <= duration <= ideal_max:
        return 1.0
    elif duration < ideal_min:
        return max(0.1, duration / ideal_min)
    else:
        # Penalty for very long scenes
        return max(0.1, 1.0 - (duration - ideal_max) / 60.0)


# ── Composite Scorer ──────────────────────────────────────────────────────────

_WEIGHTS = {
    "audio": 0.25,
    "motion": 0.25,
    "faces": 0.20,
    "dialogue": 0.10,
    "variety": 0.10,
    "length": 0.10,
}


def score_scene(
    video_path: str,
    scene: Dict,
    transcript: Dict,
) -> Dict:
    """Calculate viral score for one scene.

    Args:
        video_path: Source video file.
        scene: {scene_id, start_time, end_time, duration}.
        transcript: Whisper transcript.

    Returns:
        scene dict augmented with viral_score and component scores.
    """
    start = scene["start_time"]
    end = scene["end_time"]
    dur = scene["duration"]

    scores = {
        "audio": _score_audio_energy(video_path, start, end),
        "motion": _score_motion(video_path, start, end),
        "faces": _score_faces(video_path, start, end),
        "dialogue": _score_dialogue(transcript, start, end),
        "variety": _score_visual_variety(video_path, start, end),
        "length": _score_length(dur),
    }

    viral_score = sum(_WEIGHTS[k] * v for k, v in scores.items()) * 100.0

    return {
        **scene,
        "viral_score": round(viral_score, 1),
        "score_breakdown": {k: round(v * 100, 1) for k, v in scores.items()},
        "score": round(viral_score),  # alias for compatibility with existing card system
    }


def score_all_scenes(
    video_path: str,
    scenes: List[Dict],
    transcript: Dict,
    max_scenes_to_score: int = 100,
) -> List[Dict]:
    """Score all detected scenes and return sorted by viral_score descending.

    Args:
        video_path: Source video file.
        scenes: List of scene dicts.
        transcript: Whisper transcript.
        max_scenes_to_score: Limit processing time by capping scenes scored.

    Returns:
        Scenes list sorted by viral_score descending.
    """
    to_score = scenes[:max_scenes_to_score]
    print(f"[movie/viral] scoring {len(to_score)} scenes…", flush=True)
    scored = []
    for i, scene in enumerate(to_score, 1):
        try:
            from app import task_manager
            if task_manager.cancelled:
                raise RuntimeError("Cancelled by user")
        except ImportError:
            pass
        if i % 10 == 0 or i == len(to_score):
            print(f"[movie/viral] scored {i}/{len(to_score)} scenes", flush=True)
        scored.append(score_scene(video_path, scene, transcript))

    return sorted(scored, key=lambda s: s.get("viral_score", 0), reverse=True)

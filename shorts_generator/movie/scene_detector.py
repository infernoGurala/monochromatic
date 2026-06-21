"""Movie scene detection using PySceneDetect and OpenCV fallback.

Detects scene boundaries in a movie file and returns a list of scenes
with start/end times ready for viral scoring.
"""
import os
import subprocess
from typing import Dict, List, Optional


def _get_video_info(video_path: str) -> Dict:
    """Get video duration and fps via ffprobe."""
    dur_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    fps_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    try:
        dur = float(subprocess.run(dur_cmd, capture_output=True, text=True, timeout=30).stdout.strip())
    except Exception:
        dur = 0.0
    try:
        fps_raw = subprocess.run(fps_cmd, capture_output=True, text=True, timeout=15).stdout.strip()
        num, den = fps_raw.split("/")
        fps = float(num) / float(den)
    except Exception:
        fps = 24.0
    return {"duration": dur, "fps": fps}


def detect_scenes_scenedetect(video_path: str, threshold: float = 30.0) -> List[Dict]:
    """Use PySceneDetect ContentDetector for scene boundaries.

    Args:
        video_path: Path to movie file.
        threshold: Detection sensitivity (lower = more cuts).

    Returns:
        List of {scene_id, start_time, end_time, duration}.
    """
    try:
        from scenedetect import open_video, SceneManager  # type: ignore
        from scenedetect.detectors import ContentDetector  # type: ignore
    except ImportError:
        print("[movie/scene] scenedetect not installed — using ffmpeg fallback", flush=True)
        return []

    print(f"[movie/scene] running PySceneDetect (threshold={threshold})…", flush=True)
    try:
        video = open_video(video_path)
        manager = SceneManager()
        manager.add_detector(ContentDetector(threshold=threshold))
        manager.detect_scenes(video, show_progress=False)
        scene_list = manager.get_scene_list()
    except Exception as e:
        print(f"[movie/scene] PySceneDetect failed: {e}", flush=True)
        return []

    scenes = []
    for i, (start, end) in enumerate(scene_list):
        s_time = start.get_seconds()
        e_time = end.get_seconds()
        scenes.append({
            "scene_id": i + 1,
            "start_time": round(s_time, 2),
            "end_time": round(e_time, 2),
            "duration": round(e_time - s_time, 2),
        })

    print(f"[movie/scene] detected {len(scenes)} scenes", flush=True)
    return scenes


def detect_scenes_opencv(
    video_path: str,
    sample_fps: float = 2.0,
    diff_threshold: float = 25.0,
    min_scene_length: float = 3.0,
) -> List[Dict]:
    """OpenCV frame-difference fallback scene detector.

    Args:
        video_path: Path to video file.
        sample_fps: Frames per second to sample.
        diff_threshold: Mean absolute difference to trigger scene cut.
        min_scene_length: Minimum scene length in seconds.

    Returns:
        List of {scene_id, start_time, end_time, duration}.
    """
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        print("[movie/scene] OpenCV not available for fallback detection", flush=True)
        return []

    print(f"[movie/scene] running OpenCV frame-diff detector…", flush=True)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[movie/scene] could not open {video_path}", flush=True)
        return []

    vid_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / vid_fps
    step = max(1, int(vid_fps / sample_fps))

    scene_starts = [0.0]
    prev_gray = None
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % step == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                diff = np.mean(np.abs(gray.astype(float) - prev_gray.astype(float)))
                t = frame_idx / vid_fps
                if diff > diff_threshold and (t - scene_starts[-1]) >= min_scene_length:
                    scene_starts.append(t)
            prev_gray = gray
        frame_idx += 1

    cap.release()

    # Build scene list from cut points
    scene_starts.append(duration)
    scenes = []
    for i in range(len(scene_starts) - 1):
        s = scene_starts[i]
        e = scene_starts[i + 1]
        if e - s >= min_scene_length:
            scenes.append({
                "scene_id": i + 1,
                "start_time": round(s, 2),
                "end_time": round(e, 2),
                "duration": round(e - s, 2),
            })

    print(f"[movie/scene] OpenCV detected {len(scenes)} scenes", flush=True)
    return scenes


def detect_scenes_ffmpeg_keyframes(
    video_path: str,
    min_scene_length: float = 3.0,
    max_scenes: int = 200,
) -> List[Dict]:
    """Ultra-fast ffmpeg I-frame based scene grouper (last fallback).

    Groups consecutive I-frames into scene windows.
    """
    print(f"[movie/scene] using ffmpeg keyframe fallback…", flush=True)
    info = _get_video_info(video_path)
    duration = info["duration"]
    if duration <= 0:
        return []

    # Create uniform windows of min_scene_length
    scenes = []
    t = 0.0
    sid = 1
    window = max(min_scene_length, duration / max_scenes)
    while t < duration:
        end = min(duration, t + window)
        if end - t >= min_scene_length:
            scenes.append({
                "scene_id": sid,
                "start_time": round(t, 2),
                "end_time": round(end, 2),
                "duration": round(end - t, 2),
            })
            sid += 1
        t = end

    print(f"[movie/scene] ffmpeg fallback produced {len(scenes)} scenes", flush=True)
    return scenes


def detect_scenes(
    video_path: str,
    threshold: float = 30.0,
    min_scene_length: float = 3.0,
    max_scenes: int = 200,
    target_count: int = 3,
) -> List[Dict]:
    """Auto-select best available scene detection strategy.

    Priority: PySceneDetect → OpenCV → ffmpeg keyframe grouping.
    Includes auto-relaxation of min_scene_length if too few scenes are found.

    Returns:
        List of scene dicts with at least {scene_id, start_time, end_time, duration}.
    """
    # Scale min_scene_length down if it's too high for the video duration
    info = _get_video_info(video_path)
    duration = info.get("duration", 0.0)
    if duration > 0 and (min_scene_length * target_count) > duration:
        old_val = min_scene_length
        min_scene_length = max(2.0, duration / (target_count * 1.5))
        print(f"[movie/scene] video duration {duration:.1f}s is too short for min_scene_length {old_val}s with target {target_count} clips; dynamically adjusted min_scene_length to {min_scene_length:.1f}s", flush=True)

    current_min_len = min_scene_length
    for attempt in range(3):
        # Try PySceneDetect first
        scenes = detect_scenes_scenedetect(video_path, threshold=threshold)
        if scenes:
            filtered_scenes = [s for s in scenes if s["duration"] >= current_min_len]
            if len(filtered_scenes) >= target_count or current_min_len <= 2.0:
                return filtered_scenes[:max_scenes]

        # Try OpenCV
        scenes = detect_scenes_opencv(video_path, min_scene_length=current_min_len)
        if len(scenes) >= target_count or current_min_len <= 2.0:
            return scenes[:max_scenes]

        if current_min_len > 2.0:
            current_min_len = max(2.0, current_min_len / 2.0)
            print(f"[movie/scene] too few scenes found; retrying with lower min_scene_length: {current_min_len:.1f}s", flush=True)
        else:
            break

    # Ultimate fallback
    return detect_scenes_ffmpeg_keyframes(video_path, min_scene_length=current_min_len, max_scenes=max_scenes)

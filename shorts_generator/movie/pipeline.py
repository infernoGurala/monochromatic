"""Movie → Viral Shorts pipeline orchestrator.

Runs: Validate → Scene Detect → Transcribe → Viral Score → Clip → Return
"""
import os
import time
from typing import Dict, Optional


_SUPPORTED_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv"}


def validate_video_file(filepath: str) -> str:
    """Validate that the file exists and is a supported video format.

    Handles:
      - Absolute local paths
      - file:// URIs
      - YouTube URLs (raises RuntimeError — use standard pipeline instead)

    Returns the resolved absolute path.
    """
    # Strip file:// prefix
    if filepath.startswith("file://"):
        filepath = filepath[7:]

    if filepath.startswith("http://") or filepath.startswith("https://"):
        raise ValueError(
            "Movie Mode requires a local file path (MP4, MKV, MOV). "
            "For YouTube videos use Standard Shorts or Ranking Mode."
        )

    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Movie file not found: {filepath}")

    ext = os.path.splitext(filepath)[1].lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported movie file format: {ext}. "
            f"Supported: {', '.join(sorted(_SUPPORTED_EXTENSIONS))}"
        )

    return os.path.abspath(filepath)


def generate_movie_shorts(
    filepath: str,
    num_clips: int = 5,
    aspect_ratio: str = "9:16",
    language: Optional[str] = None,
    face_tracking: bool = True,
    enable_subtitles: bool = True,
    caption_font: str = "Impact",
    caption_size: int = 52,
    caption_color: str = "yellow",
    caption_case: str = "upper",
    scene_threshold: float = 30.0,
    min_scene_length: float = 10.0,
) -> Dict:
    """Full movie → viral shorts pipeline.

    Args:
        filepath: Local path to movie file (MP4, MKV, MOV, etc.).
        num_clips: Number of viral shorts to generate.
        aspect_ratio: Output aspect ratio, default "9:16".
        language: Whisper language code or None for auto.
        face_tracking: Enable OpenCV face tracking during reframe.
        enable_subtitles: Whether to burn subtitle captions.
        caption_*/scene_threshold/min_scene_length: Tuning params.

    Returns:
        {
          "mode": "movie",
          "source_video_url": str,
          "transcript": {...},
          "scenes_found": N,
          "avg_viral_score": float,
          "top_scene_timestamp": float,
          "processing_time": float,
          "shorts": [...],
        }
    """
    from ..transcriber import transcribe_local
    from .scene_detector import detect_scenes
    from .viral_scorer import score_all_scenes
    from .clipper import crop_movie_clips

    t0 = time.time()

    # Step 1: Validate
    print(f"[movie/pipeline] validating file: {filepath}", flush=True)
    source_path = validate_video_file(filepath)

    # Step 2: Scene detection
    print(f"[movie/pipeline] [scene] detecting scenes…", flush=True)
    scenes = detect_scenes(
        source_path,
        threshold=scene_threshold,
        min_scene_length=min_scene_length,
        max_scenes=300,
        target_count=num_clips,
    )
    if not scenes:
        raise RuntimeError("Could not detect any scenes. Try lowering the scene threshold.")

    print(f"[movie/pipeline] found {len(scenes)} scenes", flush=True)

    # Step 3: Transcribe (for subtitle + dialogue scoring)
    print(f"[movie/pipeline] [transcribe] transcribing audio…", flush=True)
    transcript = transcribe_local(source_path, language=language)

    # Step 4: Viral scoring
    print(f"[movie/pipeline] [viral] calculating viral scores…", flush=True)
    scored_scenes = score_all_scenes(source_path, scenes, transcript)

    avg_viral = (
        sum(s.get("viral_score", 0) for s in scored_scenes) / len(scored_scenes)
        if scored_scenes else 0.0
    )
    top_scene = scored_scenes[0] if scored_scenes else {}
    top_scene_ts = top_scene.get("start_time", 0.0)

    print(f"[movie/pipeline] avg viral score: {avg_viral:.1f} | top: {top_scene.get('viral_score', 0):.1f} at {top_scene_ts:.1f}s", flush=True)

    # Step 5: Select top N and render
    top_scenes = scored_scenes[:num_clips]
    print(f"[movie/pipeline] [clip] rendering {len(top_scenes)} clips…", flush=True)
    shorts = crop_movie_clips(
        source_path=source_path,
        scenes=top_scenes,
        transcript=transcript,
        aspect_ratio=aspect_ratio,
        face_tracking=face_tracking,
        enable_subtitles=enable_subtitles,
        caption_font=caption_font,
        caption_size=caption_size,
        caption_color=caption_color,
        caption_case=caption_case,
    )

    processing_time = round(time.time() - t0, 1)
    print(f"[movie/pipeline] completed in {processing_time}s", flush=True)

    return {
        "mode": "movie",
        "source_video_url": source_path,
        "transcript": transcript,
        "scenes_found": len(scenes),
        "avg_viral_score": round(avg_viral, 1),
        "top_scene_timestamp": top_scene_ts,
        "processing_time": processing_time,
        "highlights": scored_scenes[:20],  # top 20 for display
        "shorts": shorts,
    }

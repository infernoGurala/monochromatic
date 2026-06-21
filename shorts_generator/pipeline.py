"""End-to-end orchestrator for local/offline video processing.

Runs yt-dlp + faster-whisper + OpenAI/Gemini/Ollama/Groq + ffmpeg/opencv.
"""
from typing import Dict, List, Optional

from .clipper import crop_highlights_local
from .downloader import download_youtube_local
from .llm import call_local_llm
from .highlights import get_highlights
from .transcriber import transcribe_local


def parse_time_to_seconds(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    value_str = str(value).strip()
    if not value_str:
        return None
    if ":" in value_str:
        parts = value_str.split(":")
        try:
            if len(parts) == 2:  # MM:SS
                return float(parts[0]) * 60 + float(parts[1])
            elif len(parts) == 3:  # HH:MM:SS
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        except ValueError:
            pass
    try:
        return float(value_str)
    except ValueError:
        return None


def generate_shorts(
    youtube_url: str,
    num_clips: int = 3,
    aspect_ratio: str = "9:16",
    download_format: str = "720",
    language: Optional[str] = None,
    face_tracking: bool = False,
    clip_duration: str = "auto",
    crop_start: Optional[str] = None,
    crop_end: Optional[str] = None,
    caption_font: str = "Impact",
    caption_size: int = 52,
    caption_color: str = "yellow",
    caption_case: str = "upper",
    min_duration: float = 0.0,
    enable_subtitles: bool = True,
    mode: Optional[str] = None,
) -> Dict:
    """Run the full pipeline and return a structured result.

    Args:
        youtube_url: source URL or local path.
        num_clips: how many shorts to render.
        aspect_ratio: e.g. "9:16", "1:1".
        download_format: source resolution ("360" / "480" / "720" / "1080").
        language: ISO-639-1 to force Whisper language detection.
        face_tracking: enable OpenCV Haar-cascade smart face tracking.
        clip_duration: target duration preference ("auto", "30", "60", "90").
        crop_start: start time for cropping/filtering (e.g. "01:30" or "90").
        crop_end: end time for cropping/filtering (e.g. "02:30" or "150").
        caption_font: Font name for burn-in subtitles.
        caption_size: Font size for burn-in subtitles.
        caption_color: Highlight color for active word.
        caption_case: Casing style.
        min_duration: Minimum clip duration.
        enable_subtitles: Enable burn-in subtitles.
        mode: Ignored (legacy, retained for compatibility).

    Returns:
        {
          "mode": "local",
          "source_video_url": str,
          "transcript": {...},
          "highlights": [...],
          "shorts": [...],
        }
    """
    source_path = download_youtube_local(youtube_url, fmt=download_format)

    transcript = transcribe_local(source_path, language=language)
    if not transcript["segments"]:
        raise RuntimeError(
            "Whisper produced no segments. The video may have no detectable speech."
        )

    if crop_start or crop_end:
        start_sec = parse_time_to_seconds(crop_start) or 0.0
        end_sec = parse_time_to_seconds(crop_end) or float('inf')
        if start_sec > end_sec:
            raise ValueError(f"Start time ({crop_start}) cannot be after end time ({crop_end}).")
        
        print(f"[pipeline] Filtering transcript to range: {start_sec}s - {end_sec}s", flush=True)
        filtered_segments = []
        for s in transcript.get("segments", []):
            if s["start"] >= start_sec and s["end"] <= end_sec:
                filtered_segments.append(s)
        if not filtered_segments:
            raise RuntimeError(
                f"No transcript segments found in the specified range {crop_start} - {crop_end}."
            )
        transcript["segments"] = filtered_segments
        transcript["duration"] = end_sec if end_sec != float('inf') else transcript.get("duration", 0.0)

    highlights_result = get_highlights(transcript, num_clips=num_clips, llm_fn=call_local_llm, clip_duration=clip_duration, min_duration=min_duration)
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    print(f"[pipeline/local] cropping {len(top)} of {len(all_highlights)} candidates", flush=True)

    shorts = crop_highlights_local(
        source_path,
        top,
        transcript,
        aspect_ratio=aspect_ratio,
        face_tracking=face_tracking,
        caption_font=caption_font,
        caption_size=caption_size,
        caption_color=caption_color,
        caption_case=caption_case,
        enable_subtitles=enable_subtitles
    )

    return {
        "mode": "local",
        "source_video_url": source_path,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
    }

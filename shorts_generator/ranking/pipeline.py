"""Ranking Video pipeline orchestrator.

Runs: Download → Transcribe → OCR Rank Detection → Segment Build → Clip + Overlay → Concat
"""
from typing import Dict, Optional


def generate_ranking_short(
    youtube_url: str,
    num_ranks: int = 10,
    aspect_ratio: str = "9:16",
    download_format: str = "1080",
    language: Optional[str] = None,
    overlay_style: str = "large",
    enable_subtitles: bool = True,
    caption_font: str = "Impact",
    caption_size: int = 52,
    caption_color: str = "yellow",
    caption_case: str = "upper",
    ocr_enabled: bool = True,
    target_clip_length: float = 5.0,
    max_duration: float = 60.0,
) -> Dict:
    """Full ranking video → countdown short pipeline.

    Args:
        youtube_url: YouTube URL or local file path.
        num_ranks: How many ranks to include (e.g., top 10 from a top 20 video).
        aspect_ratio: Output aspect ratio, default "9:16".
        download_format: Video quality for download.
        language: Whisper language code or None for auto.
        overlay_style: "large" / "minimal" / "none".
        enable_subtitles: Whether to burn subtitle captions.
        caption_font/size/color/case: Subtitle styling.
        ocr_enabled: Use EasyOCR for rank detection; falls back to heuristic split.
        target_clip_length: Target seconds per rank clip (3–6).
        max_duration: Maximum total output duration (60s).

    Returns:
        {
          "mode": "ranking",
          "source_video_url": str,
          "transcript": {...},
          "segments": [...],
          "clip_url": "/output/ranking_short.mp4",
          "total_ranks": N,
          "shorts": [{"clip_url": ..., "rank": ..., "title": ...}]
        }
    """
    from ..downloader import download_youtube_local
    from ..transcriber import transcribe_local
    from .ocr_detector import detect_ranks_ocr, group_rank_detections
    from .builder import (
        build_rank_segments,
        build_rank_segments_from_transcript_only,
        select_top_ranks,
    )
    from .clipper import crop_ranking_clips

    print(f"[ranking/pipeline] starting for: {youtube_url}", flush=True)

    # Step 1: Download
    print(f"[ranking/pipeline] [download] downloading source video…", flush=True)
    source_path = download_youtube_local(youtube_url, fmt=download_format)

    # Step 2: Transcribe with word timestamps
    print(f"[ranking/pipeline] [transcribe] transcribing audio…", flush=True)
    transcript = transcribe_local(source_path, language=language)
    if not transcript["segments"]:
        raise RuntimeError("Whisper produced no segments — video may have no speech.")

    video_duration = transcript["duration"]

    # Step 3: OCR Rank Detection
    ocr_groups = []
    if ocr_enabled:
        print(f"[ranking/pipeline] [ocr] scanning video frames for rank numbers…", flush=True)
        detections = detect_ranks_ocr(source_path, sample_interval=1.0, max_rank=500)
        ocr_groups = group_rank_detections(detections, gap_threshold=3.0)
        print(f"[ranking/pipeline] [ocr] detected {len(ocr_groups)} unique ranks", flush=True)

    # Step 4: Build rank segments
    print(f"[ranking/pipeline] building rank segments…", flush=True)
    if ocr_groups:
        segments = build_rank_segments(
            transcript, ocr_groups, video_duration,
            target_clip_length=target_clip_length,
        )
    else:
        # Fallback: equal-split heuristic
        print(f"[ranking/pipeline] OCR found no ranks — using heuristic split", flush=True)
        segments = build_rank_segments_from_transcript_only(
            transcript, num_ranks, video_duration,
            target_clip_length=target_clip_length,
        )

    if not segments:
        raise RuntimeError("Could not extract any rank segments from the video.")

    # Step 5: Select top N ranks (e.g., top 10 from top 20)
    top_segments = select_top_ranks(segments, num_ranks)
    print(f"[ranking/pipeline] selected top {len(top_segments)} ranks for countdown", flush=True)

    # Step 6: Trim target duration — if too many clips would exceed max_duration
    per_clip_budget = max_duration / max(len(top_segments), 1)
    if per_clip_budget < target_clip_length:
        target_clip_length = max(2.0, per_clip_budget)

    # Step 7 & 8: Clip + overlay + concat
    print(f"[ranking/pipeline] [clip] rendering countdown clips…", flush=True)
    result = crop_ranking_clips(
        source_path=source_path,
        segments=top_segments,
        transcript=transcript,
        aspect_ratio=aspect_ratio,
        overlay_style=overlay_style,
        enable_subtitles=enable_subtitles,
        caption_font=caption_font,
        caption_size=caption_size,
        caption_color=caption_color,
        caption_case=caption_case,
        max_duration=max_duration,
    )

    # Build shorts list compatible with existing result card system
    shorts = [{
        "clip_url": result["clip_url"],
        "title": f"Ranking Countdown #{top_segments[-1]['rank']}–#{top_segments[0]['rank']}",
        "hook": f"Countdown from #{top_segments[0]['rank']} to #{top_segments[-1]['rank']}",
        "virality_reason": "Ranking countdown format — high retention hook-based content",
        "score": 90,
        "start_time": top_segments[-1]["start_time"] if top_segments else 0,
        "end_time": top_segments[0]["end_time"] if top_segments else 0,
        "rank_range": [top_segments[-1]["rank"], top_segments[0]["rank"]],
        "total_ranks": len(top_segments),
        "mode": "ranking",
    }]

    return {
        "mode": "ranking",
        "source_video_url": source_path,
        "transcript": transcript,
        "segments": result["segments"],
        "clip_url": result["clip_url"],
        "total_ranks": len(top_segments),
        "shorts": shorts,
    }

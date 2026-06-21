"""Movie clipper — reuses existing local/clipper.py reframing + subtitle engine."""
import os
from typing import Dict, List, Optional

from ..config import LOCAL_OUTPUT_DIR


def crop_movie_clips(
    source_path: str,
    scenes: List[Dict],      # top scenes sorted by viral_score
    transcript: Dict,
    aspect_ratio: str = "9:16",
    out_dir: Optional[str] = None,
    face_tracking: bool = True,
    enable_subtitles: bool = True,
    caption_font: str = "Impact",
    caption_size: int = 52,
    caption_color: str = "yellow",
    caption_case: str = "upper",
) -> List[Dict]:
    """Reframe top movie scenes to vertical format with subtitles.

    Delegates entirely to the existing crop_highlights_local() engine
    by converting scenes to the highlights format it expects.

    Returns:
        List of scene dicts with clip_url added.
    """
    from ..clipper import crop_highlights_local

    # Convert scene dicts to highlights format
    highlights = []
    for scene in scenes:
        highlights.append({
            "start_time": scene["start_time"],
            "end_time": scene["end_time"],
            "title": f"Scene {scene.get('scene_id', '?')} — Viral Score {scene.get('viral_score', 0):.0f}",
            "hook": scene.get("title", ""),
            "virality_reason": "Movie scene selected by viral intelligence engine",
            "score": scene.get("viral_score", 0),
        })

    print(f"[movie/clipper] rendering {len(highlights)} movie clips…", flush=True)
    results = crop_highlights_local(
        source_path=source_path,
        highlights=highlights,
        transcript=transcript,
        aspect_ratio=aspect_ratio,
        out_dir=out_dir,
        face_tracking=face_tracking,
        caption_font=caption_font,
        caption_size=caption_size,
        caption_color=caption_color,
        caption_case=caption_case,
        enable_subtitles=enable_subtitles,
    )

    # Merge viral scoring metadata back into clip results
    merged = []
    for i, (scene, result) in enumerate(zip(scenes, results)):
        merged.append({
            **scene,
            "clip_url": result.get("clip_url"),
            "title": f"Movie Clip #{i+1} — Viral {scene.get('viral_score', 0):.0f}/100",
            "hook": result.get("hook", ""),
            "virality_reason": "Movie scene selected by viral intelligence engine",
            "score": scene.get("viral_score", 0),
            "mode": "movie",
        })

    return merged

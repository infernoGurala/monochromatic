"""Ranking segment builder.

Merges Whisper transcript segments with OCR-detected rank time ranges
to produce structured ranking data:
  [{rank, start_time, end_time, text, score}, ...]
"""
from typing import Dict, List, Optional


def _find_transcript_text(transcript: Dict, start: float, end: float) -> str:
    """Collect Whisper segment text within [start, end] time window."""
    parts = []
    for seg in transcript.get("segments", []):
        seg_start = float(seg.get("start", 0))
        seg_end = float(seg.get("end", 0))
        # Overlap check
        if seg_end >= start and seg_start <= end:
            text = (seg.get("text") or "").strip()
            if text:
                parts.append(text)
    return " ".join(parts)


def build_rank_segments(
    transcript: Dict,
    ocr_groups: List[Dict],
    video_duration: float,
    target_clip_length: float = 5.0,
    min_clip_length: float = 2.0,
) -> List[Dict]:
    """Merge OCR rank groups with transcript to create structured segments.

    Each segment:
      {rank, start_time, end_time, text, score}

    Args:
        transcript: Whisper transcript dict with segments list.
        ocr_groups: Output of group_rank_detections() — [{rank, start_time, end_time}].
        video_duration: Total video duration in seconds.
        target_clip_length: Preferred clip length in seconds (3–6).
        min_clip_length: Minimum clip length before padding.

    Returns:
        Sorted list of rank segments (highest rank first for countdown order).
    """
    segments = []

    for group in ocr_groups:
        rank = group["rank"]
        raw_start = float(group["start_time"])
        raw_end = float(group["end_time"])

        # Pad or trim to target length
        actual_len = raw_end - raw_start
        if actual_len < min_clip_length:
            # Extend end
            raw_end = min(video_duration, raw_start + target_clip_length)
        elif actual_len > target_clip_length * 2:
            # Trim to reasonable window centered on detection
            center = (raw_start + raw_end) / 2
            raw_start = max(0.0, center - target_clip_length / 2)
            raw_end = min(video_duration, center + target_clip_length / 2)

        # Get transcript context
        text = _find_transcript_text(transcript, raw_start, raw_end)

        segments.append({
            "rank": rank,
            "start_time": round(raw_start, 2),
            "end_time": round(raw_end, 2),
            "text": text,
            "score": rank,  # Higher rank = higher score for selection
        })

    # Sort countdown: highest rank number first (e.g., #10 before #1)
    return sorted(segments, key=lambda s: s["rank"], reverse=True)


def build_rank_segments_from_transcript_only(
    transcript: Dict,
    num_ranks: int,
    video_duration: float,
    target_clip_length: float = 5.0,
) -> List[Dict]:
    """Fallback when OCR fails: heuristically split video into N equal segments.

    Uses LLM-style heuristic: divide video into num_ranks equal windows and
    label them #num_ranks downto #1 (assuming video starts with lowest rank
    and ends with highest, which is the standard format).

    Args:
        transcript: Whisper transcript dict.
        num_ranks: Number of rank segments to create.
        video_duration: Total video duration.
        target_clip_length: Target length per clip.

    Returns:
        List of rank segments from highest to lowest rank.
    """
    if video_duration <= 0 or num_ranks <= 0:
        return []

    # Assign equal time windows
    window = video_duration / num_ranks
    segments = []

    for i in range(num_ranks):
        rank = num_ranks - i  # rank #num_ranks first, then down to #1
        raw_start = i * window
        raw_end = min(video_duration, raw_start + min(target_clip_length, window))
        text = _find_transcript_text(transcript, raw_start, raw_end)

        segments.append({
            "rank": rank,
            "start_time": round(raw_start, 2),
            "end_time": round(raw_end, 2),
            "text": text,
            "score": rank,
        })

    return sorted(segments, key=lambda s: s["rank"], reverse=True)


def select_top_ranks(segments: List[Dict], num_ranks: int) -> List[Dict]:
    """Select the top N highest ranks (lowest rank numbers = most important).

    In a countdown video, rank #1 is the winner. If we want top 10 from
    a top 20 video, we take ranks #10 through #1.

    Args:
        segments: Full list of ranked segments.
        num_ranks: How many to keep.

    Returns:
        Top N segments still sorted highest-rank-first for countdown.
    """
    # Sort by rank ascending to find lowest rank numbers (= highest importance)
    by_importance = sorted(segments, key=lambda s: s["rank"])
    top = by_importance[:num_ranks]
    # Return in countdown order (high rank number → low rank number)
    return sorted(top, key=lambda s: s["rank"], reverse=True)

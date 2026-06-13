"""Find the most viral-worthy highlights in a transcript.

Logic ported from ViralVadoo's transcript_analysis/highlight_generator.py:
  - content-type / density detection
  - chunking for long videos with overlap
  - virality-criteria prompt
  - score-based dedupe with overlap suppression

The LLM call is pluggable via the `llm_fn` argument so the same prompts can
drive either MuAPI (default, --mode api) or a direct local LLM client
(--mode local).
"""
import json
import re
from typing import Callable, Dict, List, Optional

from .llm import call_local_llm


LLMFn = Callable[[str], str]


CONTENT_TYPE_PROMPT = """Analyze this video transcript sample and classify the content type.
Choose one: podcast, interview, tutorial, lecture, commentary, debate, vlog, other.
Also estimate content density: low (mostly filler/chit-chat), medium, or high (dense info/stories).
Respond with JSON only: {"content_type": "...", "density": "..."}"""


VIRALITY_CRITERIA = """
Virality signals to prioritize (ranked by impact):
1. HOOK MOMENTS — statements that create immediate curiosity ("The secret is...", "Nobody talks about...", "I was completely wrong about...")
2. EMOTIONAL PEAKS — genuine surprise, laughter, anger, vulnerability, excitement; raw unscripted reactions
3. OPINION BOMBS — strong, polarizing or counter-intuitive statements that trigger agree/disagree
4. REVELATION MOMENTS — surprising facts, stats, or confessions that reframe how the viewer thinks
5. CONFLICT/TENSION — disagreement, pushback, or a problem being confronted head-on
6. QUOTABLE ONE-LINERS — a sentence that works as a standalone quote card
7. STORY PEAKS — the climax or twist of an anecdote; the payoff moment
8. PRACTICAL VALUE — a concrete tip, hack, or insight the viewer can immediately apply
"""


HIGHLIGHT_SYSTEM_PROMPT = """You are an elite short-form video editor who has studied thousands of viral clips on TikTok, Instagram Reels, and YouTube Shorts. You know exactly what makes viewers stop scrolling, watch to the end, and share.

{virality_criteria}

Content type: {content_type} | Density: {density}

Your task: identify the most viral-worthy highlights from the transcript.

Rules:
- HOOK START: Start every highlight at an engaging, impulsive, or high-energy sentence (e.g. exclamations, surprising statements, exciting setups) within the first 3 seconds.
- RESOLVED ENDING: Choose an ending that leaves the viewer with a satisfying, resolved thought, punchline, or a natural cliffhanger. Do NOT cut off mid-thought.
- {duration_instruction}
- CRITICAL: A highlight must span multiple consecutive transcript segments to build up a duration matching the target length instructions (e.g., at least 45-90 seconds for auto). Do NOT output short clips of only 5-15 seconds; calculate the `end_time` by looking ahead in the transcript.
- Never cut mid-sentence or mid-thought — each clip must feel complete and self-contained
- Clips must not overlap significantly with each other
- Score 0-100 on viral potential (not general quality)
- {num_clips_instruction}
- For each highlight, identify the single best "hook_sentence" — the opening line that would make someone stop scrolling
- Explain in one sentence why this clip is viral ("virality_reason")

Respond ONLY with valid JSON (no markdown, no explanation):
{{"highlights":[{{"title":"string","start_time":float,"end_time":float,"score":int,"hook_sentence":"string","virality_reason":"string"}}]}}"""


CHUNK_SIZE_SECONDS = 1200       # 20-min chunks for long videos
LONG_VIDEO_THRESHOLD = 1800     # chunk videos longer than 30 min
CHUNK_OVERLAP_SECONDS = 60
GPT_CALL_TIMEOUT_SECONDS = 300  # cap LLM polls at 5 min — a wedged call should fail fast
MAX_HIGHLIGHT_API_ATTEMPTS = 3


# Removed call_muapi_llm


def _parse_json_loose(raw: str) -> Dict:
    """gpt-5-4 sometimes wraps JSON in markdown fences — strip and parse."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Pre-clean unquoted time values like 13:30 or 1:30:15
    text = re.sub(r':\s*(\d+(?::\d+)+)(?=\s*(?:,|\s*\}|\s*\]))', r': "\1"', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt to clean unescaped quotes in known string fields
    def escape_inside(match):
        key = match.group(1)
        val = match.group(2)
        val_clean = val.replace('\\"', '"').replace('"', '\\"')
        return f'"{key}": "{val_clean}"'

    cleaned_text = text
    keys = ["title", "hook_sentence", "virality_reason", "content_type", "density"]
    for key in keys:
        pattern = r'"(' + key + r')"\s*:\s*"(.*?)"(?=\s*(?:,\s*"[a-zA-Z0-9_]+"\s*:|\s*\}))'
        cleaned_text = re.sub(pattern, escape_inside, cleaned_text, flags=re.DOTALL)

    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError:
        start = cleaned_text.find("{")
        end = cleaned_text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(cleaned_text[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise


def _coerce_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, str):
        value_str = value.strip()
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
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _sanitize_highlights(
    raw_highlights: object,
    duration: float,
    clip_duration: str = "auto",
    transcript: Optional[Dict] = None,
) -> List[Dict]:
    """Normalize model output into the expected shape; skip invalid entries."""
    if not isinstance(raw_highlights, list):
        return []

    # Map clip duration settings to min and target seconds
    if clip_duration == "30":
        min_dur = 15.0
        target_dur = 30.0
    elif clip_duration == "60":
        min_dur = 45.0
        target_dur = 60.0
    elif clip_duration == "90":
        min_dur = 75.0
        target_dur = 90.0
    else:  # "auto"
        min_dur = 35.0  # Let it be slightly flexible for auto, but default to 45s target
        target_dur = 45.0

    max_end = duration if duration > 0 else float("inf")
    cleaned: List[Dict] = []
    segments = transcript.get("segments", []) if transcript else []

    for item in raw_highlights:
        if not isinstance(item, dict):
            continue

        # Flexible start_time lookup
        start_val = None
        for key in ("start_time", "start", "startTime", "start_sec", "start_seconds", "time", "timestamp", "at"):
            if key in item and item[key] is not None:
                start_val = item[key]
                break
        start = _coerce_float(start_val, default=-1.0)

        # Flexible end_time lookup
        end_val = None
        for key in ("end_time", "end", "endTime", "end_sec", "end_seconds"):
            if key in item and item[key] is not None:
                end_val = item[key]
                break
        end = _coerce_float(end_val, default=-1.0)

        if start < 0:
            continue

        # Segment-aware alignment and duration extension
        if segments:
            # Find closest segment index for start
            start_idx = 0
            min_start_diff = float("inf")
            for idx, s in enumerate(segments):
                diff = abs(s["start"] - start)
                if diff < min_start_diff:
                    min_start_diff = diff
                    start_idx = idx

            # Find closest segment index for end
            end_idx = start_idx
            min_end_diff = float("inf")
            for idx, s in enumerate(segments):
                diff = abs(s["end"] - end)
                if diff < min_end_diff:
                    min_end_diff = diff
                    end_idx = idx

            if end_idx < start_idx:
                end_idx = start_idx

            # Extend to target duration if too short by checking consecutive segments
            while end_idx < len(segments) - 1:
                current_dur = segments[end_idx]["end"] - segments[start_idx]["start"]
                if current_dur >= min_dur and (end_val is not None and end > start):
                    # Only stop if it meets user/model specified end or target minimums
                    break
                if current_dur >= target_dur:
                    break
                end_idx += 1

            start = segments[start_idx]["start"]
            end = segments[end_idx]["end"]
        else:
            # Fallback without transcript
            current_dur = end - start
            if end <= start or current_dur < min_dur:
                end = start + target_dur

        if max_end != float("inf"):
            start = min(start, max_end)
            end = min(end, max_end)
            if end <= start:
                continue

        # Flexible score lookup
        score_val = 0
        for key in ("score", "rating", "virality_score", "viral_score"):
            if key in item and item[key] is not None:
                score_val = _coerce_int(item[key], default=0)
                break
        if score_val <= 0:
            score_val = 80  # Default reasonable score if LLM omitted it

        # Flexible hook_sentence lookup
        hook_val = ""
        for key in ("hook_sentence", "text", "hook", "sentence"):
            if key in item and item[key] is not None:
                hook_val = str(item[key]).strip()
                break

        # Flexible virality_reason lookup
        reason_val = ""
        for key in ("virality_reason", "reason", "description", "explanation"):
            if key in item and item[key] is not None:
                reason_val = str(item[key]).strip()
                break

        # Flexible title lookup
        title_val = "Untitled Highlight"
        for key in ("title", "name", "headline"):
            if key in item and item[key] is not None:
                title_val = str(item[key]).strip()
                break

        cleaned.append(
            {
                "title": title_val,
                "start_time": start,
                "end_time": end,
                "score": max(0, min(100, score_val)),
                "hook_sentence": hook_val,
                "virality_reason": reason_val,
            }
        )

    return cleaned


def detect_content_type(transcript: Dict, llm_fn: Optional[LLMFn] = None) -> Dict[str, str]:
    llm_fn = llm_fn or call_local_llm
    segments = transcript.get("segments", [])
    sample = " ".join(s["text"] for s in segments[:25])[:3000]
    prompt = f"{CONTENT_TYPE_PROMPT}\n\nTranscript sample:\n{sample}"
    try:
        raw = llm_fn(prompt)
        return _parse_json_loose(raw)
    except Exception:
        return {"content_type": "other", "density": "medium"}


def build_transcript_text(transcript: Dict) -> str:
    segments = transcript.get("segments", [])
    return "\n".join(f"[{s['start']:.1f}s] {s['text'].strip()}" for s in segments)


def chunk_transcript(transcript: Dict) -> List[Dict]:
    segments = transcript.get("segments", [])
    duration = transcript.get("duration", segments[-1]["end"] if segments else 0)
    chunks = []
    start = 0
    while start < duration:
        end = min(start + CHUNK_SIZE_SECONDS, duration)
        chunk_segs = [
            s for s in segments
            if s["start"] >= start and s["end"] <= end + CHUNK_OVERLAP_SECONDS
        ]
        if chunk_segs:
            chunk = dict(transcript)
            chunk["segments"] = chunk_segs
            chunk["duration"] = end - start
            chunk["_offset"] = start
            chunks.append(chunk)
        start += CHUNK_SIZE_SECONDS - CHUNK_OVERLAP_SECONDS
    return chunks


def call_highlight_api(
    transcript_text: str,
    content_info: Dict,
    duration: float,
    num_clips: int,
    is_chunk: bool = False,
    llm_fn: Optional[LLMFn] = None,
    clip_duration: str = "auto",
    transcript: Optional[Dict] = None,
) -> Dict:
    # Ask for ~2× the user's target so dedupe has headroom, but cap so the model
    # doesn't have to generate a huge JSON payload (which times out gpt-5-mini).
    llm_fn = llm_fn or call_local_llm
    target = max(num_clips * 2, 5)
    natural_max = max(2 if is_chunk else 3, int(duration / 90))
    min_clips = min(target, natural_max, 8)

    if clip_duration == "30":
        duration_instruction = "Duration sweet spot: 15-40 seconds. Target exactly ~30 seconds per clip."
    elif clip_duration == "60":
        duration_instruction = "Duration sweet spot: 45-70 seconds. Target exactly ~60 seconds per clip."
    elif clip_duration == "90":
        duration_instruction = "Duration sweet spot: 75-105 seconds. Target exactly ~90 seconds per clip."
    else:
        duration_instruction = "Duration sweet spot: 45-90 seconds. Go shorter (20-44s) only for a perfect standalone one-liner. Go longer (91-180s) only when a story arc needs full context to land."

    system = HIGHLIGHT_SYSTEM_PROMPT.format(
        virality_criteria=VIRALITY_CRITERIA,
        content_type=content_info.get("content_type", "other"),
        density=content_info.get("density", "medium"),
        duration_instruction=duration_instruction,
        num_clips_instruction=f"Generate at least {min_clips} highlights",
    )
    base_prompt = f"{system}\n\nTranscript:\n{transcript_text}"
    prompt = base_prompt
    last_error = "unknown"

    for attempt in range(1, MAX_HIGHLIGHT_API_ATTEMPTS + 1):
        raw = llm_fn(prompt)
        print(f"[highlights] Raw LLM Response (Attempt {attempt}):\n{raw}\n", flush=True)
        try:
            parsed = _parse_json_loose(raw)
            if isinstance(parsed, list):
                raw_highlights = parsed
            elif isinstance(parsed, dict):
                raw_highlights = parsed.get("highlights")
            else:
                raw_highlights = None
            highlights = _sanitize_highlights(raw_highlights, duration=duration, clip_duration=clip_duration, transcript=transcript)
            if highlights:
                return {"highlights": highlights}
            last_error = "no valid highlights in response"
        except Exception as e:
            last_error = str(e)

        if attempt < MAX_HIGHLIGHT_API_ATTEMPTS:
            print(
                f"[highlights] invalid model output on attempt {attempt}/{MAX_HIGHLIGHT_API_ATTEMPTS}; retrying",
                flush=True,
            )
            prompt = (
                base_prompt
                + "\n\nIMPORTANT: Return ONLY valid JSON with a top-level 'highlights' array."
                + " Each item must include: title, start_time, end_time, score, hook_sentence, virality_reason."
                + " No markdown fences, no commentary."
            )

    raise RuntimeError(
        f"Highlight generator produced invalid output after {MAX_HIGHLIGHT_API_ATTEMPTS} attempts: {last_error}"
    )


def dedupe_highlights(highlights: List[Dict]) -> List[Dict]:
    """Drop a highlight if it overlaps >50% with a higher-scoring one already kept."""
    highlights = sorted(highlights, key=lambda x: int(x.get("score", 0)), reverse=True)
    kept: List[Dict] = []
    for h in highlights:
        h_start = float(h["start_time"])
        h_end = float(h["end_time"])
        h_dur = h_end - h_start
        overlapping = False
        for k in kept:
            latest_start = max(h_start, float(k["start_time"]))
            earliest_end = min(h_end, float(k["end_time"]))
            overlap = earliest_end - latest_start
            if overlap > 0 and overlap > 0.5 * h_dur:
                overlapping = True
                break
        if not overlapping:
            kept.append(h)
    return kept


def get_highlights(
    transcript: Dict,
    num_clips: int = 3,
    llm_fn: Optional[LLMFn] = None,
    clip_duration: str = "auto",
) -> Dict:
    """Main entry point — returns {highlights: [...]} sorted by score.

    `llm_fn` swaps the underlying LLM. Defaults to configured local LLM.
    """
    llm_fn = llm_fn or call_local_llm
    duration = transcript.get("duration", 0)
    content_info = detect_content_type(transcript, llm_fn=llm_fn)
    print(f"[highlights] content={content_info.get('content_type')} density={content_info.get('density')} duration={duration:.0f}s", flush=True)

    if duration >= LONG_VIDEO_THRESHOLD:
        chunks = chunk_transcript(transcript)
        print(f"[highlights] long video — splitting into {len(chunks)} chunks", flush=True)
        all_highlights: List[Dict] = []
        for i, chunk in enumerate(chunks):
            offset = chunk.get("_offset", 0)
            text = build_transcript_text(chunk)
            print(f"[highlights] chunk {i + 1}/{len(chunks)} (offset {offset:.0f}s)", flush=True)
            result = call_highlight_api(text, content_info, chunk["duration"], num_clips=num_clips, is_chunk=True, llm_fn=llm_fn, clip_duration=clip_duration, transcript=chunk)
            for h in result.get("highlights", []):
                h["start_time"] = float(h["start_time"]) + offset
                h["end_time"] = float(h["end_time"]) + offset
                all_highlights.append(h)
        highlights = dedupe_highlights(all_highlights)
    else:
        text = build_transcript_text(transcript)
        result = call_highlight_api(text, content_info, duration, num_clips=num_clips, llm_fn=llm_fn, clip_duration=clip_duration, transcript=transcript)
        highlights = dedupe_highlights(result.get("highlights", []))

    return {"highlights": highlights}

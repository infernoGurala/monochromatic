import os
import sys
import json
import threading
import traceback
from flask import Flask, jsonify, request, send_from_directory, redirect
from flask_cors import CORS

app = Flask(__name__, static_folder='static')
CORS(app)

# Ensure local outputs directory exists
OUTPUT_DIR = os.environ.get("LOCAL_OUTPUT_DIR", "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

class ThreadSafeLogger:
    def __init__(self):
        self.logs = []
        self.lock = threading.Lock()
        self.status = "idle"  # idle, downloading, transcribing, analyzing, cropping, ocr, scene_detect, viral_score, completed, failed
        self.progress = 0
        self.results = None
        self.error_message = None
        self.cancelled = False

    def reset(self):
        with self.lock:
            self.status = "idle"
            self.progress = 0
            self.logs = []
            self.results = None
            self.error_message = None
            self.cancelled = False

    def cancel(self):
        with self.lock:
            if self.status not in ("idle", "completed", "failed"):
                self.cancelled = True
                self.status = "failed"
                self.error_message = "Generation cancelled by user."
                self.logs.append("\n❌ Generation Cancelled by User.\n")


    def add_log(self, text):
        with self.lock:
            self.logs.append(text)
            # Detect step changes based on print statements
            lower_text = text.lower()
            if "[download]" in lower_text or "[downloader]" in lower_text or "downloading_local" in lower_text:
                self.status = "downloading"
                self.progress = 10
            elif "[transcribe]" in lower_text or "transcribing_local" in lower_text:
                self.status = "transcribing"
                self.progress = 30
            elif "[ranking/ocr]" in lower_text or "[ocr]" in lower_text:
                self.status = "ocr"
                self.progress = 50
            elif "[movie/scene]" in lower_text or "[scene]" in lower_text:
                self.status = "scene_detect"
                self.progress = 45
            elif "[movie/viral]" in lower_text or "[viral]" in lower_text:
                self.status = "viral_score"
                self.progress = 65
            elif "[highlights]" in lower_text or "building rank" in lower_text:
                self.status = "analyzing"
                self.progress = 65
            elif "[clip]" in lower_text or "[clipper]" in lower_text or "cropping" in lower_text or "crop_highlights" in lower_text or "rendering" in lower_text or "concatenating" in lower_text:
                self.status = "cropping"
                self.progress = 85

    def get_status(self):
        with self.lock:
            return {
                "status": self.status,
                "progress": self.progress,
                "logs": "".join(self.logs),
                "error_message": self.error_message,
                "has_results": self.results is not None
            }

    def get_results(self):
        with self.lock:
            return self.results

    def run_generation(self, url, num_clips, aspect_ratio, download_format, language, face_tracking=False,
                       clip_duration="auto", crop_start=None, crop_end=None, mode="local",
                       caption_font="Impact", caption_size=52, caption_color="yellow", caption_case="upper", min_duration=0.0, enable_subtitles=True,
                       gen_mode="standard", ranking_overlay="large", ocr_enabled=True, target_clip_length=5.0, max_duration=60.0,
                       scene_threshold=30.0, min_scene_length=10.0):
        self.reset()
        with self.lock:
            self.status = "downloading"
            self.progress = 5
            self.logs = [f"Starting shorts generation for: {url}\n"]

        class LogRedirector:
            def __init__(self, logger_instance):
                self.logger_instance = logger_instance
                self.stdout = sys.stdout
                self.stderr = sys.stderr

            def write(self, message):
                if message:
                    self.logger_instance.add_log(message)
                self.stdout.write(message)

            def flush(self):
                self.stdout.flush()

        try:
            redirector = LogRedirector(self)
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = redirector
            sys.stderr = redirector

            # Overwrite environment variables from updated .env file
            from dotenv import load_dotenv
            load_dotenv(override=True)

            try:
                result = None

                if gen_mode == "ranking":
                    from shorts_generator.ranking.pipeline import generate_ranking_short
                    result = generate_ranking_short(
                        youtube_url=url,
                        num_ranks=num_clips,
                        aspect_ratio=aspect_ratio,
                        download_format=download_format,
                        language=language,
                        overlay_style=ranking_overlay,
                        enable_subtitles=enable_subtitles,
                        caption_font=caption_font,
                        caption_size=caption_size,
                        caption_color=caption_color,
                        caption_case=caption_case,
                        ocr_enabled=ocr_enabled,
                        target_clip_length=target_clip_length,
                        max_duration=max_duration,
                    )
                    # Serve local files
                    if result.get("clip_url") and not result["clip_url"].startswith("/output/"):
                        result["clip_url"] = f"/output/{os.path.basename(result['clip_url'])}"
                    for short in result.get("shorts", []):
                        if short.get("clip_url") and not str(short["clip_url"]).startswith("/output/"):
                            short["clip_url"] = f"/output/{os.path.basename(short['clip_url'])}"

                elif gen_mode == "movie":
                    from shorts_generator.movie.pipeline import generate_movie_shorts
                    result = generate_movie_shorts(
                        filepath=url,
                        num_clips=num_clips,
                        aspect_ratio=aspect_ratio,
                        language=language,
                        face_tracking=face_tracking,
                        enable_subtitles=enable_subtitles,
                        caption_font=caption_font,
                        caption_size=caption_size,
                        caption_color=caption_color,
                        caption_case=caption_case,
                        scene_threshold=scene_threshold,
                        min_scene_length=min_scene_length,
                    )
                    # Serve local files
                    for short in result.get("shorts", []):
                        if short.get("clip_url") and not str(short["clip_url"]).startswith("/output/"):
                            short["clip_url"] = f"/output/{os.path.basename(short['clip_url'])}"

                else:
                    # Standard shorts pipeline
                    from shorts_generator import generate_shorts
                    result = generate_shorts(
                        youtube_url=url,
                        num_clips=num_clips,
                        aspect_ratio=aspect_ratio,
                        download_format=download_format,
                        language=language,
                        face_tracking=face_tracking,
                        clip_duration=clip_duration,
                        crop_start=crop_start,
                        crop_end=crop_end,
                        caption_font=caption_font,
                        caption_size=caption_size,
                        caption_color=caption_color,
                        caption_case=caption_case,
                        min_duration=min_duration,
                        enable_subtitles=enable_subtitles
                    )
                    # Format clip URLs for static serving in local mode
                    if "shorts" in result:
                        for short in result["shorts"]:
                            if short.get("clip_url"):
                                filename = os.path.basename(short["clip_url"])
                                short["clip_url"] = f"/output/{filename}"

                with self.lock:
                    self.status = "completed"
                    self.progress = 100
                    self.results = result
                    self.logs.append("\n🎉 Generation Completed Successfully!\n")
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

        except Exception as e:
            traceback.print_exc()
            with self.lock:
                self.status = "failed"
                self.progress = 100
                self.error_message = str(e)
                self.logs.append(f"\n❌ Generation Failed: {e}\n{traceback.format_exc()}\n")

# Global background task manager
task_manager = ThreadSafeLogger()

def read_env():
    config = {}
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    # Clean inline comments
                    if "#" in v:
                        v = v.split("#", 1)[0]
                    v = v.strip().strip('"').strip("'")
                    config[k.strip()] = v
    return config

def write_env(new_config):
    lines = []
    keys_written = set()
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            lines = f.readlines()
            
    updated_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, v = stripped.split("=", 1)
            k = k.strip()
            if k in new_config:
                comment = ""
                if "#" in v:
                    comment_parts = v.split("#", 1)
                    if len(comment_parts) > 1:
                        comment = "  #" + comment_parts[1]
                updated_lines.append(f"{k}={new_config[k]}{comment}\n")
                keys_written.add(k)
                continue
        updated_lines.append(line)
        
    for k, v in new_config.items():
        if k not in keys_written:
            if updated_lines and not updated_lines[-1].endswith("\n"):
                updated_lines[-1] = updated_lines[-1] + "\n"
            updated_lines.append(f"{k}={v}\n")
            keys_written.add(k)
            
    with open(".env", "w") as f:
        f.writelines(updated_lines)

# Routes
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/output/<path:filename>')
def serve_output(filename):
    # Dynamically look up current output directory
    env = read_env()
    out_dir = env.get("LOCAL_OUTPUT_DIR", "output")
    return send_from_directory(out_dir, filename)

@app.route('/api/config', methods=['GET'])
def get_config():
    config = read_env()
    if os.path.exists("API.txt"):
        with open("API.txt", "r") as f:
            config["GROQ_KEYS"] = f.read()
    return jsonify(config)

@app.route('/api/config', methods=['POST'])
def save_config():
    data = request.json or {}
    if "GROQ_KEYS" in data:
        groq_keys = data.pop("GROQ_KEYS")
        with open("API.txt", "w") as f:
            f.write(groq_keys)
    write_env(data)
    # Reload environment
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    config = read_env()
    if os.path.exists("API.txt"):
        with open("API.txt", "r") as f:
            config["GROQ_KEYS"] = f.read()
    return jsonify({"status": "success", "config": config})

@app.route('/api/generate', methods=['POST'])
def start_generation():
    status_info = task_manager.get_status()
    if status_info["status"] not in ("idle", "completed", "failed"):
        return jsonify({"error": "A generation task is already running."}), 409

    from shorts_generator.config import reset_cancel
    reset_cancel()

    data = request.json or {}
    url = data.get("url")
    if not url:
        return jsonify({"error": "Video URL is required."}), 400

    mode = data.get("mode", "local")
    gen_mode = data.get("gen_mode", "standard")  # standard | ranking | movie
    num_clips = int(data.get("num_clips", 3))
    aspect_ratio = data.get("aspect_ratio", "9:16")
    download_format = data.get("format", "720")
    language = data.get("language") or None
    face_tracking = bool(data.get("face_tracking", False))

    clip_duration = data.get("clip_duration", "auto")
    crop_start = data.get("crop_start") or None
    crop_end = data.get("crop_end") or None
    caption_font = data.get("caption_font", "Impact")
    try:
        caption_size = int(data.get("caption_size", 52))
    except (TypeError, ValueError):
        caption_size = 52
    caption_color = data.get("caption_color", "yellow")
    caption_case = data.get("caption_case", "upper")

    try:
        min_duration = float(data.get("min_duration", 0.0))
    except (TypeError, ValueError):
        min_duration = 0.0

    enable_subtitles = bool(data.get("enable_subtitles", True))

    # Ranking mode params
    ranking_overlay = data.get("ranking_overlay", "large")  # large | minimal | none
    ocr_enabled = bool(data.get("ocr_enabled", True))
    try:
        target_clip_length = float(data.get("target_clip_length", 5.0))
    except (TypeError, ValueError):
        target_clip_length = 5.0
    try:
        max_duration = float(data.get("max_duration", 60.0))
    except (TypeError, ValueError):
        max_duration = 60.0

    # Movie mode params
    try:
        scene_threshold = float(data.get("scene_threshold", 30.0))
    except (TypeError, ValueError):
        scene_threshold = 30.0
    try:
        min_scene_length = float(data.get("min_scene_length", 10.0))
    except (TypeError, ValueError):
        min_scene_length = 10.0

    # Start generation thread
    thread = threading.Thread(
        target=task_manager.run_generation,
        kwargs=dict(
            url=url, mode=mode, num_clips=num_clips, aspect_ratio=aspect_ratio,
            download_format=download_format, language=language, face_tracking=face_tracking,
            clip_duration=clip_duration, crop_start=crop_start, crop_end=crop_end,
            caption_font=caption_font, caption_size=caption_size, caption_color=caption_color,
            caption_case=caption_case, min_duration=min_duration, enable_subtitles=enable_subtitles,
            gen_mode=gen_mode, ranking_overlay=ranking_overlay, ocr_enabled=ocr_enabled,
            target_clip_length=target_clip_length, max_duration=max_duration,
            scene_threshold=scene_threshold, min_scene_length=min_scene_length,
        )
    )
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started", "gen_mode": gen_mode})

@app.route('/api/terminate', methods=['POST'])
def terminate_generation():
    from shorts_generator.config import cancel_generation
    cancel_generation()

    # Kill any child processes (like ffmpeg/yt-dlp)
    import os
    import subprocess
    try:
        pid = os.getpid()
        subprocess.run(["pkill", "-P", str(pid)])
    except Exception as e:
        print(f"Error terminating child processes: {e}")

    task_manager.status = "failed"
    task_manager.error_message = "Generation terminated by user."
    task_manager.progress = 100
    task_manager.logs.append("\n🛑 Generation Terminated by User!\n")

    return jsonify({"status": "terminated"})

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify(task_manager.get_status())

@app.route('/api/cancel', methods=['POST'])
def cancel_generation():
    task_manager.cancel()
    return jsonify({"status": "cancelled"})

@app.route('/api/results', methods=['GET'])
def get_results():
    results = task_manager.get_results()
    if results is None:
        return jsonify({"error": "No results available."}), 404
    return jsonify(results)

# ── Groq AI Metadata Generation ──────────────────────────────────────────────
@app.route('/api/groq/generate-metadata', methods=['POST'])
def groq_generate_metadata():
    """Use Groq LLM to produce an optimised YouTube title + description."""
    data = request.json or {}
    
    # Robust mapping to handle incoming keys
    transcript = data.get('transcript') or data.get('hook') or ''
    video_topic = data.get('video_topic') or data.get('title') or ''
    video_summary = data.get('video_summary') or data.get('virality_reason') or ''
    keywords = data.get('keywords') or f"{data.get('title', '')} {data.get('hook', '')}".strip()

    # Pull Groq key from .env at runtime
    env = read_env()
    groq_key = env.get('GROQ_API_KEY', '').strip()
    if not groq_key:
        return jsonify({'error': 'GROQ_API_KEY not configured. Add it in API Settings.'}), 400

    system_prompt = """ROLE:
You are not a title generator.
You are an elite YouTube Shorts Growth Strategist, CTR Psychologist, Retention Expert, and Viral Content Analyst.
Your job is to generate:
1. Title
2. Description
3. Hashtags
for every YouTube Short.

Your objective is NOT accuracy.
Your objective is NOT creativity.
Your objective is:
MAXIMUM CLICKS
MAXIMUM RETENTION
MAXIMUM CURIOSITY
MAXIMUM DISCOVERABILITY
while remaining relevant to the video.

---
TITLE RULES
Titles are the most important output.
The title must create at least one of:
* Curiosity
* Suspense
* Shock
* Surprise
* FOMO
* Mystery

The viewer should think:
"What happened?"
or
"I need to know more."

---
TITLE REQUIREMENTS
Maximum:
60 characters

Ideal:
35-55 characters

Use:
1-2 emojis maximum

Examples:
😳 Nobody Expected This...
🤯 Scientists Just Discovered This
👀 Look What Happened Next
💀 One Mistake Changed Everything
🔥 This Changes Everything
🚨 They Didn't See This Coming

---
FORBIDDEN TITLE WORDS
Never use:
Amazing
Awesome
Interesting
Great
Cool
Wonderful
Best Ever

These words reduce CTR.

---
DESCRIPTION RULES
Description must:
* Explain the video
* Expand curiosity
* Improve SEO
* Encourage engagement

Include:
* Short summary
* Call to action
* Relevant keywords

Structure:
Hook
Summary
Question
CTA

Example:
🤯 Could antigravity change humanity forever?
In this short, we explore the science behind antigravity and what could happen if humans learn to control gravity.
What would you do if gravity disappeared for 10 seconds?
Subscribe for more science, technology, AI, and future content.

---
HASHTAG RULES
Generate:
10-15 hashtags

Mix:
* Broad hashtags
* Niche hashtags
* Topic hashtags
* Discovery hashtags

Example:
#Science
#Physics
#FutureTech
#Technology
#Antigravity
#Engineering
#Space
#Innovation
#ScienceFacts
#DidYouKnow
#Future
#AI
#Shorts
#Viral
#Facts

---
PSYCHOLOGY ENGINE
Before generating the title ask:
Which title would make a human stop scrolling?
Reject titles that do not create curiosity.
Reject titles that feel robotic.
Reject titles that sound like AI.
Reject titles that sound like a school project.
Generate titles that feel human.

---
EMOJI RULES
Use only:
😳
🤯
👀
💀
🔥
🚨
⚠️
🧠
🚀

Maximum:
2 emojis
Never spam emojis.

---
RELEVANCE RULE
The title, description, and hashtags must always be related to the video.
Never use trending keywords that are unrelated.
Never create misleading metadata.
Curiosity is allowed.
Irrelevance is forbidden.

---
OUTPUT FORMAT
Return ONLY valid JSON.
{
"title": "",
"description": "",
"hashtags": [
"",
"",
""
]
}"""

    user_prompt = f"""INPUT
You will receive:
* Transcript: {transcript}
* Video Topic: {video_topic}
* Video Summary: {video_summary}
* Detected Keywords: {keywords}

Analyze all information before generating metadata.
Never create generic outputs.
Every output must be specifically related to the video.
"""

    try:
        import requests as req
        resp = req.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {groq_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                'temperature': 0.7,
                'max_tokens': 512,
                'response_format': {'type': 'json_object'}
            },
            timeout=20
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content']
        import json as _json
        parsed = _json.loads(content)
        
        title = parsed.get('title', '')
        desc = parsed.get('description', '')
        tags = parsed.get('hashtags', [])
        
        if tags:
            tag_string = " ".join(tags)
            desc = f"{desc}\n\n{tag_string}"

        return jsonify({
            'title': title,
            'description': desc
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



# YouTube Integration Routes
from youtube_uploader import (
    get_all_connected_accounts,
    start_upload_job,
    get_upload_status
)

@app.route('/api/youtube/status', methods=['GET'])
def youtube_status():
    accounts = get_all_connected_accounts()
    return jsonify({
        "accounts": accounts
    })

@app.route('/api/youtube/upload', methods=['POST'])
def youtube_upload():
    data = request.json or {}
    clip_url = data.get("clip_url")
    account_id = data.get("account_id")
    
    if not clip_url:
        return jsonify({"error": "clip_url is required."}), 400
    if account_id is None:
        return jsonify({"error": "account_id is required."}), 400
        
    try:
        account_id = int(account_id)
    except ValueError:
        return jsonify({"error": "Invalid account_id."}), 400
        
    title = data.get("title", "AI YouTube Short")
    description = data.get("description", "")
    privacy_status = data.get("privacy_status", "private")
    upload_type = data.get("upload_type", "short")
    
    # Resolve file path
    if clip_url.startswith("/output/"):
        filename = os.path.basename(clip_url)
        env = read_env()
        out_dir = env.get("LOCAL_OUTPUT_DIR", "output")
        filepath = os.path.join(out_dir, filename)
    else:
        filepath = clip_url # Remote URL or local path directly
        
    try:
        job_id = start_upload_job(account_id, filepath, title, description, privacy_status, upload_type)
        return jsonify({"status": "success", "job_id": job_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/youtube/upload/status/<job_id>', methods=['GET'])
def youtube_upload_status(job_id):
    status = get_upload_status(job_id)
    if not status:
        return jsonify({"error": "Upload job not found."}), 404
    return jsonify(status)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

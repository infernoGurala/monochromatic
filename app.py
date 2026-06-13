import os
import sys
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
        self.status = "idle"  # idle, downloading, transcribing, analyzing, cropping, completed, failed
        self.progress = 0
        self.results = None
        self.error_message = None

    def reset(self):
        with self.lock:
            self.status = "idle"
            self.progress = 0
            self.logs = []
            self.results = None
            self.error_message = None

    def add_log(self, text):
        with self.lock:
            self.logs.append(text)
            # Detect step changes based on print statements
            lower_text = text.lower()
            if "[download]" in lower_text or "[downloader]" in lower_text or "downloading_local" in lower_text:
                self.status = "downloading"
                self.progress = 15
            elif "[transcribe]" in lower_text or "transcribing_local" in lower_text:
                self.status = "transcribing"
                self.progress = 40
            elif "[highlights]" in lower_text:
                self.status = "analyzing"
                self.progress = 65
            elif "[clip]" in lower_text or "[clipper]" in lower_text or "cropping" in lower_text or "crop_highlights" in lower_text:
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

    def run_generation(self, url, mode, num_clips, aspect_ratio, download_format, language, face_tracking=False):
        self.reset()
        with self.lock:
            self.status = "downloading"
            self.progress = 5
            self.logs = [f"Starting shorts generation for: {url} (mode: {mode})\n"]

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

        # Run pipeline
        from shorts_generator import generate_shorts

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
                result = generate_shorts(
                    youtube_url=url,
                    num_clips=num_clips,
                    aspect_ratio=aspect_ratio,
                    download_format=download_format,
                    language=language,
                    mode=mode,
                    face_tracking=face_tracking
                )

                # Format clip URLs for static serving in local mode
                if mode == "local" and "shorts" in result:
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
            updated_lines.append(f"{k}={v}\n")
            
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
    return jsonify(read_env())

@app.route('/api/config', methods=['POST'])
def save_config():
    data = request.json or {}
    write_env(data)
    # Reload environment
    from dotenv import load_dotenv
    load_dotenv(override=True)
    return jsonify({"status": "success", "config": read_env()})

@app.route('/api/generate', methods=['POST'])
def start_generation():
    status_info = task_manager.get_status()
    if status_info["status"] not in ("idle", "completed", "failed"):
        return jsonify({"error": "A generation task is already running."}), 409

    data = request.json or {}
    url = data.get("url")
    if not url:
        return jsonify({"error": "Video URL is required."}), 400

    mode = data.get("mode", "api")
    num_clips = int(data.get("num_clips", 3))
    aspect_ratio = data.get("aspect_ratio", "9:16")
    download_format = data.get("format", "720")
    language = data.get("language") or None
    face_tracking = bool(data.get("face_tracking", False))

    # Start generation thread
    thread = threading.Thread(
        target=task_manager.run_generation,
        args=(url, mode, num_clips, aspect_ratio, download_format, language, face_tracking)
    )
    thread.daemon = True
    thread.start()

    return jsonify({"status": "started"})

@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify(task_manager.get_status())

@app.route('/api/results', methods=['GET'])
def get_results():
    results = task_manager.get_results()
    if results is None:
        return jsonify({"error": "No results available."}), 404
    return jsonify(results)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

import os
import json
import logging
import threading
from typing import Dict, Optional, Tuple
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import requests

# Logger configuration
logger = logging.getLogger("youtube_uploader")
logger.setLevel(logging.INFO)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

# Thread-safe global jobs dictionary to track upload progress
# job_id -> { "status": "pending|uploading|completed|failed", "progress": int, "video_id": str, "error": str }
upload_jobs = {}
jobs_lock = threading.Lock()

def get_token_file_path(account_id: int) -> str:
    """Get the path to the token file for the given account ID."""
    # Support both hidden (.youtube_token_X.json) and visible (youtube_token_X.json) files
    dot_path = f".youtube_token_{account_id}.json"
    no_dot_path = f"youtube_token_{account_id}.json"
    if os.path.exists(dot_path):
        return dot_path
    elif os.path.exists(no_dot_path):
        return no_dot_path
    return dot_path  # Default to dot path

def get_youtube_credentials(account_id: int) -> Optional[Credentials]:
    """Load credentials from the specified account token file if available, and refresh them if expired."""
    token_file = get_token_file_path(account_id)
    if not os.path.exists(token_file):
        return None

    creds = None
    try:
        with open(token_file, "r") as f:
            info = json.load(f)
        creds = Credentials.from_authorized_user_info(info, SCOPES)
    except Exception as e:
        logger.error(f"Error loading token file {token_file}: {e}")
        return None

    # Refresh expired credentials if refresh token is available
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Save refreshed credentials
            with open(token_file, "w") as f:
                f.write(creds.to_json())
        except Exception as e:
            logger.error(f"Error refreshing credentials for account {account_id}: {e}")
            return None

    return creds if creds and creds.valid else None

def get_channel_info(account_id: int) -> Optional[Dict]:
    """Retrieve title and thumbnail of the authorized YouTube channel for a specific account."""
    creds = get_youtube_credentials(account_id)
    if not creds:
        return None
    try:
        youtube = build("youtube", "v3", credentials=creds)
        req = youtube.channels().list(part="snippet", mine=True)
        res = req.execute()
        if "items" in res and len(res["items"]) > 0:
            snippet = res["items"][0]["snippet"]
            return {
                "title": snippet.get("title", "Unknown Channel"),
                "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", "")
            }
    except Exception as e:
        logger.error(f"Error retrieving channel info for account {account_id}: {e}")
    return None

def get_all_connected_accounts() -> list:
    """Scan and return status for preset accounts (Account 1 and Account 2)."""
    accounts = []
    for account_id in [1, 2]:
        creds = get_youtube_credentials(account_id)
        if creds:
            channel = get_channel_info(account_id)
            accounts.append({
                "account_id": account_id,
                "connected": True,
                "channel": channel
            })
        else:
            accounts.append({
                "account_id": account_id,
                "connected": False,
                "channel": None
            })
    return accounts

def upload_video_thread(job_id: str, account_id: int, filepath: str, title: str, description: str, privacy_status: str, upload_type: str = "short"):
    """Background task for uploading video to YouTube with progress tracking for a specific account."""
    if privacy_status not in ["private", "public", "unlisted"]:
        privacy_status = "private"

    creds = get_youtube_credentials(account_id)
    if not creds:
        with jobs_lock:
            upload_jobs[job_id] = {
                "status": "failed",
                "progress": 0,
                "video_id": None,
                "error": f"YouTube credentials for Account {account_id} not connected or expired."
            }
        return

    temp_filepath = None
    try:
        # Check if filepath is a remote URL (for cloud API mode)
        if filepath.startswith("http://") or filepath.startswith("https://"):
            logger.info(f"Downloading remote video for upload: {filepath}")
            with jobs_lock:
                upload_jobs[job_id] = {
                    "status": "uploading",
                    "progress": 5,
                    "video_id": None,
                    "error": None
                }
            
            # Download to a temporary file
            temp_filepath = f"output/temp_upload_{job_id}.mp4"
            os.makedirs("output", exist_ok=True)
            
            # Determine base URL if we need to fetch local output route
            download_url = filepath
            if filepath.startswith("/output/"):
                download_url = f"http://127.0.0.1:5000{filepath}"
                
            response = requests.get(download_url, stream=True)
            response.raise_for_status()
            with open(temp_filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            filepath = temp_filepath

        # Verify file exists
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Video file not found at: {filepath}")

        # Build service
        youtube = build("youtube", "v3", credentials=creds)

        # Prepare body and media upload
        if upload_type == "short":
            if "#shorts" not in title.lower():
                title = f"{title} #shorts"
            tags = ["shorts", "youtube-shorts", "AI-shorts"]
        else:
            tags = ["video", "monochromatic", "AI-video"]

        body = {
            "snippet": {
                "title": title[:100],  # YouTube max title size
                "description": description,
                "tags": tags,
                "categoryId": "22"  # People & Blogs
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False
            }
        }

        media = MediaFileUpload(filepath, chunksize=1024 * 1024, resumable=True, mimetype="video/mp4")
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )

        logger.info(f"Starting resumable upload for {filepath} using Account {account_id}...")
        response = None
        
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress_percent = int(status.progress() * 100)
                progress_val = min(max(10, progress_percent), 99)
                with jobs_lock:
                    upload_jobs[job_id] = {
                        "status": "uploading",
                        "progress": progress_val,
                        "video_id": None,
                        "error": None
                    }
                logger.info(f"Upload job {job_id} progress: {progress_val}%")

        video_id = response.get("id")
        logger.info(f"Upload complete! Video ID: {video_id}")
        
        with jobs_lock:
            upload_jobs[job_id] = {
                "status": "completed",
                "progress": 100,
                "video_id": video_id,
                "error": None
            }

    except Exception as e:
        logger.error(f"Error uploading video: {e}")
        with jobs_lock:
            upload_jobs[job_id] = {
                "status": "failed",
                "progress": 0,
                "video_id": None,
                "error": str(e)
            }
    finally:
        # Clean up temp file if downloaded
        if temp_filepath and os.path.exists(temp_filepath):
            try:
                os.remove(temp_filepath)
            except Exception as ex:
                logger.error(f"Failed to delete temp file {temp_filepath}: {ex}")

def start_upload_job(account_id: int, filepath: str, title: str, description: str, privacy_status: str, upload_type: str = "short") -> str:
    """Initialize and start a background upload job, returning its unique job ID."""
    import uuid
    job_id = str(uuid.uuid4())
    
    with jobs_lock:
        upload_jobs[job_id] = {
            "status": "pending",
            "progress": 0,
            "video_id": None,
            "error": None
        }

    thread = threading.Thread(
        target=upload_video_thread,
        args=(job_id, account_id, filepath, title, description, privacy_status, upload_type)
    )
    thread.daemon = True
    thread.start()
    
    return job_id

def get_upload_status(job_id: str) -> Optional[Dict]:
    """Retrieve status of the specified upload job."""
    with jobs_lock:
        return upload_jobs.get(job_id)

import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import subprocess
from dotenv import load_dotenv

load_dotenv()

class YouTubeStreamer:
    def __init__(self):
        self.client_id = os.getenv('YOUTUBE_CLIENT_ID')
        self.client_secret = os.getenv('YOUTUBE_CLIENT_SECRET')
        self.scopes = ['https://www.googleapis.com/auth/youtube.force-ssl']
        self.api_name = "youtube"
        self.api_version = "v3"

    def authenticate(self):
        """Authenticate with YouTube API"""
        client_config = {
            "installed": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [
                    "https://ytstream-py.onrender.com/oauth2callback",
                    "http://localhost:10000/oauth2callback"
                ]
            }
        }
        
        flow = InstalledAppFlow.from_client_config(
            client_config,
            self.scopes,
            redirect_uri="https://ytstream-py.onrender.com/oauth2callback"
        )
        credentials = flow.run_local_server(
            port=0,
            prompt='consent',
            access_type='offline',
            success_message='Authentication successful! You can close this window.'
        )
        return build(self.api_name, self.api_version, credentials=credentials)

    def create_broadcast(self, youtube, title, description):
        """Create YouTube broadcast"""
        broadcast_insert_response = youtube.liveBroadcasts().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": title,
                    "description": description,
                    "scheduledStartTime": "2024-02-07T00:00:00.000Z"
                },
                "status": {
                    "privacyStatus": "private"
                }
            }
        ).execute()
        
        return broadcast_insert_response["id"]

    def create_stream(self, youtube):
        """Create YouTube stream"""
        stream_insert_response = youtube.liveStreams().insert(
            part="snippet,cdn",
            body={
                "snippet": {
                    "title": "New Stream"
                },
                "cdn": {
                    "frameRate": "30fps",
                    "ingestionType": "rtmp",
                    "resolution": "1080p"
                }
            }
        ).execute()
        
        return stream_insert_response["id"]

    def bind_broadcast(self, youtube, broadcast_id, stream_id):
        """Bind broadcast to stream"""
        youtube.liveBroadcasts().bind(
            part="id,contentDetails",
            id=broadcast_id,
            streamId=stream_id
        ).execute()

    def get_stream_url(self, youtube, stream_id):
        """Get stream URL"""
        stream = youtube.liveStreams().list(
            part="cdn",
            id=stream_id
        ).execute()
        
        return stream["items"][0]["cdn"]["ingestionInfo"]["ingestionAddress"]

    def stream_video(self, video_path, stream_url):
        """Stream video using FFmpeg"""
        command = [
            'ffmpeg',
            '-re',  # Read input at native frame rate
            '-i', video_path,  # Input file
            '-c:v', 'libx264',  # Video codec
            '-preset', 'veryfast',  # Encoding preset
            '-maxrate', '2500k',
            '-bufsize', '5000k',
            '-pix_fmt', 'yuv420p',
            '-g', '60',  # Keyframe interval
            '-c:a', 'aac',  # Audio codec
            '-b:a', '128k',  # Audio bitrate
            '-ar', '44100',  # Audio sample rate
            '-f', 'flv',  # Output format
            stream_url  # Stream URL
        ]
        
        subprocess.run(command)
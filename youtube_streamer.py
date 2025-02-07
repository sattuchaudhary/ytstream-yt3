import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import subprocess
from dotenv import load_dotenv
import logging
from flask import redirect

load_dotenv()

logger = logging.getLogger(__name__)

class YouTubeStreamer:
    def __init__(self):
        self.client_id = os.getenv('YOUTUBE_CLIENT_ID')
        self.client_secret = os.getenv('YOUTUBE_CLIENT_SECRET')
        self.scopes = ['https://www.googleapis.com/auth/youtube.force-ssl']
        self.api_name = "youtube"
        self.api_version = "v3"

    def authenticate(self):
        """Authenticate with YouTube API"""
        try:
            client_config = {
                "installed": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost:10000/oauth2callback"]  # Simplified redirect
                }
            }
            
            if not self.client_id or not self.client_secret:
                raise ValueError("YouTube credentials not found. Please check your environment variables.")

            flow = InstalledAppFlow.from_client_config(
                client_config,
                self.scopes
            )
            # Use credentials directly instead of local server
            credentials = Credentials(
                None,
                client_id=self.client_id,
                client_secret=self.client_secret,
                token_uri="https://oauth2.googleapis.com/token",
                scopes=self.scopes
            )
            return build(self.api_name, self.api_version, credentials=credentials)
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            raise Exception(f"Authentication failed: {str(e)}")

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

    def get_auth_url(self):
        """Get YouTube authentication URL"""
        flow = InstalledAppFlow.from_client_config(
            self.client_config,
            self.scopes,
            redirect_uri="https://ytstream-py.onrender.com/auth/callback"
        )
        return flow.authorization_url(prompt='consent')[0]

    def get_credentials_from_code(self, code):
        """Get credentials from authorization code"""
        flow = InstalledAppFlow.from_client_config(
            self.client_config,
            self.scopes,
            redirect_uri="https://ytstream-py.onrender.com/auth/callback"
        )
        flow.fetch_token(code=code)
        return redirect('https://ytsattu.netlify.app')

    def get_channel_info(self, youtube):
        """Get authenticated user's channel info"""
        channels = youtube.channels().list(
            part="snippet,contentDetails",
            mine=True
        ).execute()
        
        if channels['items']:
            channel = channels['items'][0]
            return {
                'id': channel['id'],
                'title': channel['snippet']['title'],
                'thumbnail': channel['snippet']['thumbnails']['default']['url']
            }
        return None
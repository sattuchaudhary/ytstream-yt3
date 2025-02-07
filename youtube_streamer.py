import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import subprocess
from dotenv import load_dotenv
import logging
from flask import redirect
import json
import secrets
from requests_oauthlib import OAuth2Session

load_dotenv()

logger = logging.getLogger(__name__)

class YouTubeStreamer:
    def __init__(self):
        self.client_id = os.getenv('YOUTUBE_CLIENT_ID')
        self.client_secret = os.getenv('YOUTUBE_CLIENT_SECRET')
        self.scopes = ['https://www.googleapis.com/auth/youtube']
        self.redirect_uri = "https://ytstream-py.onrender.com/auth/callback"

    def get_auth_url(self):
        """Get YouTube authentication URL"""
        try:
            if not self.client_id or not self.client_secret:
                raise ValueError("YouTube credentials not found")
            
            flow = InstalledAppFlow.from_client_config({
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri]
                }
            }, self.scopes)
            
            auth_url = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent'
            )[0]  # Only return the URL, not state
            
            return auth_url
            
        except Exception as e:
            logger.error(f"Auth URL error: {str(e)}")
            raise

    def get_credentials(self, auth_code):
        """Get credentials from auth code"""
        try:
            flow = InstalledAppFlow.from_client_config({
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri]
                }
            }, self.scopes)
            
            flow.fetch_token(code=auth_code)
            return flow.credentials
        except Exception as e:
            logger.error(f"Credentials error: {str(e)}")
            raise

    def get_channel_info(self, credentials):
        """Get channel info"""
        try:
            youtube = build('youtube', 'v3', credentials=credentials)
            request = youtube.channels().list(
                part="snippet",
                mine=True
            )
            response = request.execute()
            
            if response['items']:
                channel = response['items'][0]
                return {
                    'id': channel['id'],
                    'title': channel['snippet']['title'],
                    'thumbnail': channel['snippet']['thumbnails']['default']['url']
                }
            return None
        except Exception as e:
            logger.error(f"Channel info error: {str(e)}")
            raise

    def start_stream(self, credentials, video_path, title):
        """Start a YouTube stream"""
        try:
            youtube = build('youtube', 'v3', credentials=credentials)
            
            # Create broadcast
            broadcast = youtube.liveBroadcasts().insert(
                part="snippet,status",
                body={
                    "snippet": {
                        "title": title,
                        "scheduledStartTime": "2024-02-07T00:00:00.000Z"
                    },
                    "status": {
                        "privacyStatus": "private"
                    }
                }
            ).execute()

            # Create stream
            stream = youtube.liveStreams().insert(
                part="snippet,cdn",
                body={
                    "snippet": {
                        "title": title
                    },
                    "cdn": {
                        "frameRate": "30fps",
                        "ingestionType": "rtmp",
                        "resolution": "1080p"
                    }
                }
            ).execute()

            # Bind broadcast to stream
            youtube.liveBroadcasts().bind(
                part="id,contentDetails",
                id=broadcast['id'],
                streamId=stream['id']
            ).execute()

            # Get stream URL
            stream_url = stream['cdn']['ingestionInfo']['ingestionAddress']
            
            # Start FFmpeg stream
            command = [
                'ffmpeg',
                '-re',
                '-i', video_path,
                '-c:v', 'libx264',
                '-preset', 'veryfast',
                '-maxrate', '2500k',
                '-bufsize', '5000k',
                '-pix_fmt', 'yuv420p',
                '-g', '60',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-ar', '44100',
                '-f', 'flv',
                stream_url
            ]
            
            subprocess.Popen(command)  # Run in background
            
            return {
                'broadcast_url': f'https://youtube.com/watch?v={broadcast["id"]}',
                'stream_url': stream_url
            }
            
        except Exception as e:
            logger.error(f"Stream error: {str(e)}")
            raise

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

    def get_youtube_service(self, credentials_json):
        """Get YouTube service from stored credentials"""
        try:
            credentials = Credentials.from_authorized_user_info(
                json.loads(credentials_json),
                self.scopes
            )
            return build(self.api_name, self.api_version, credentials=credentials)
        except Exception as e:
            logger.error(f"Error getting service: {str(e)}")
            raise Exception(f"Failed to get YouTube service: {str(e)}")
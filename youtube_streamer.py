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
        self.scopes = ['https://www.googleapis.com/auth/youtube.force-ssl']
        self.api_name = "youtube"
        self.api_version = "v3"
        self.redirect_uri = "https://ytstream-py.onrender.com/auth/callback"
        self.client_config = {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self.redirect_uri],
                "javascript_origins": [
                    "https://ytsattu.netlify.app",
                    "https://ytstream-py.onrender.com"
                ]
            }
        }

    def get_auth_url(self):
        """Get YouTube authentication URL"""
        try:
            if not self.client_id or not self.client_secret:
                raise ValueError("YouTube credentials not found")
            
            flow = InstalledAppFlow.from_client_config(self.client_config, self.scopes)
            
            auth_url = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent'
            )[0]
            
            return auth_url
            
        except Exception as e:
            logger.error(f"Auth URL error: {str(e)}")
            raise

    def get_credentials(self, auth_code):
        """Get credentials from auth code"""
        try:
            if not auth_code:
                raise ValueError("Authorization code is missing")
            
            flow = InstalledAppFlow.from_client_config(self.client_config, self.scopes)
            
            flow.fetch_token(code=auth_code)
            return flow.credentials
        except Exception as e:
            logger.error(f"Credentials error: {str(e)}")
            raise

    def get_channel_info(self, youtube):
        """Get channel info"""
        try:
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
            if not os.path.exists(video_path):
                raise ValueError("Video file not found")

            youtube = build('youtube', 'v3', credentials=credentials)
            
            # Create broadcast
            broadcast_id = self.create_broadcast(youtube, title, f"Stream of {os.path.basename(video_path)}")
            logger.info(f"Created broadcast with ID: {broadcast_id}")
            
            # Create stream
            stream_id = self.create_stream(youtube)
            logger.info(f"Created stream with ID: {stream_id}")
            
            # Bind broadcast to stream
            youtube.liveBroadcasts().bind(
                part="id,contentDetails",
                id=broadcast_id,
                streamId=stream_id
            ).execute()
            logger.info("Bound broadcast to stream")
            
            # Get stream URL
            stream_url = self.get_stream_url(youtube, stream_id)
            logger.info(f"Got stream URL: {stream_url}")
            
            # Start FFmpeg in background
            try:
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
                
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                # Check if process started successfully
                if process.poll() is not None:
                    raise Exception("Failed to start FFmpeg process")
                    
                logger.info("Started FFmpeg process")
                
                return {
                    'success': True,
                    'broadcast_url': f'https://youtube.com/watch?v={broadcast_id}',
                    'stream_url': stream_url
                }
                
            except Exception as e:
                logger.error(f"FFmpeg error: {str(e)}")
                # Try to cleanup
                try:
                    youtube.liveBroadcasts().delete(id=broadcast_id).execute()
                    youtube.liveStreams().delete(id=stream_id).execute()
                except:
                    pass
                raise Exception(f"Failed to start stream: {str(e)}")
            
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
            return build('youtube', 'v3', credentials=credentials)
        except Exception as e:
            logger.error(f"Error getting service: {str(e)}")
            raise
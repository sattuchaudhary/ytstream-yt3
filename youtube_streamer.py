import os
from google_auth_oauthlib.flow import Flow
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
import datetime
import sys

load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_format)
logger.addHandler(console_handler)

# File handler
file_handler = logging.FileHandler('youtube_stream.log')
file_handler.setLevel(logging.DEBUG)
file_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_format)
logger.addHandler(file_handler)

class YouTubeStreamError(Exception):
    """Base exception for YouTube streaming errors"""
    pass

class AuthenticationError(YouTubeStreamError):
    """Raised when authentication fails"""
    pass

class BroadcastError(YouTubeStreamError):
    """Raised when broadcast creation/transition fails"""
    pass

class StreamError(YouTubeStreamError):
    """Raised when stream creation/setup fails"""
    pass

class FFmpegError(YouTubeStreamError):
    """Raised when FFmpeg process fails"""
    pass

class YouTubeStreamer:
    def __init__(self):
        self.client_id = os.getenv('YOUTUBE_CLIENT_ID')
        self.client_secret = os.getenv('YOUTUBE_CLIENT_SECRET')
        self.scopes = ['https://www.googleapis.com/auth/youtube.force-ssl']
        self.api_name = "youtube"
        self.api_version = "v3"
        self.redirect_uri = "https://ytstream-py.onrender.com/auth/callback"

    def get_auth_url(self):
        """Get YouTube authentication URL"""
        try:
            if not self.client_id or not self.client_secret:
                raise ValueError("YouTube credentials not found")
            
            # Add state parameter for security
            state = secrets.token_urlsafe(32)
            
            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": self.client_id,
                        "project_id": "ytstream-py",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "client_secret": self.client_secret,
                        "redirect_uris": [self.redirect_uri],
                        "javascript_origins": [
                            "https://ytsattu.netlify.app",
                            "https://ytstream-py.onrender.com"
                        ]
                    }
                },
                scopes=self.scopes,
                redirect_uri=self.redirect_uri,
                state=state  # Add state to flow
            )
            
            auth_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent'
            )
            
            return auth_url, state  # Return both URL and state
            
        except Exception as e:
            logger.error(f"Auth URL error: {str(e)}")
            raise

    def get_credentials(self, auth_code, state=None):
        """Get credentials from auth code"""
        try:
            if not auth_code:
                raise ValueError("Authorization code is missing")
            
            flow = Flow.from_client_config(
                {
                    "web": {
                        "client_id": self.client_id,
                        "project_id": "ytstream-py",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "client_secret": self.client_secret,
                        "redirect_uris": [self.redirect_uri],
                        "javascript_origins": [
                            "https://ytsattu.netlify.app",
                            "https://ytstream-py.onrender.com"
                        ]
                    }
                },
                scopes=self.scopes,
                redirect_uri=self.redirect_uri,
                state=state  # Add state to flow
            )
            
            try:
                flow.fetch_token(code=auth_code)
                return flow.credentials
            except Exception as e:
                raise ValueError(f"Failed to exchange code: {str(e)}")
            
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
                raise StreamError(f"Video file not found: {video_path}")

            try:
                youtube = build('youtube', 'v3', credentials=credentials)
            except Exception as e:
                raise AuthenticationError(f"Failed to create YouTube service: {str(e)}")
            
            try:
                # Create broadcast
                broadcast_id = self.create_broadcast(youtube, title, f"Stream of {os.path.basename(video_path)}")
                logger.info(f"Created broadcast with ID: {broadcast_id}")
            except Exception as e:
                raise BroadcastError(f"Failed to create broadcast: {str(e)}")
            
            try:
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
            except Exception as e:
                # Cleanup broadcast if stream setup fails
                try:
                    youtube.liveBroadcasts().delete(id=broadcast_id).execute()
                except:
                    pass
                raise StreamError(f"Failed to setup stream: {str(e)}")
            
            # Start FFmpeg
            try:
                process = self.start_ffmpeg(video_path, stream_url)
                logger.info("Started FFmpeg process")
                
                return {
                    'success': True,
                    'broadcast_url': f'https://youtube.com/watch?v={broadcast_id}',
                    'stream_url': stream_url
                }
                
            except Exception as e:
                # Cleanup on FFmpeg failure
                try:
                    youtube.liveBroadcasts().delete(id=broadcast_id).execute()
                    youtube.liveStreams().delete(id=stream_id).execute()
                except:
                    pass
                raise FFmpegError(f"Failed to start FFmpeg: {str(e)}")
            
        except YouTubeStreamError as e:
            logger.error(str(e))
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            raise YouTubeStreamError(f"Stream failed: {str(e)}")

    def create_broadcast(self, youtube, title, description):
        """Create YouTube broadcast"""
        try:
            # Get current time in ISO format
            current_time = datetime.datetime.utcnow().isoformat() + 'Z'
            
            broadcast_insert_response = youtube.liveBroadcasts().insert(
                part="snippet,status,contentDetails",
                body={
                    "snippet": {
                        "title": title,
                        "description": description,
                        "scheduledStartTime": current_time,
                        "actualStartTime": current_time
                    },
                    "status": {
                        "privacyStatus": "public",
                        "selfDeclaredMadeForKids": False
                    },
                    "contentDetails": {
                        "enableAutoStart": True,
                        "enableAutoStop": False,
                        "enableDvr": True,
                        "enableContentEncryption": True,
                        "enableEmbed": True,
                        "recordFromStart": True,
                        "startWithSlate": False
                    }
                }
            ).execute()
            
            # Transition broadcast to testing state
            youtube.liveBroadcasts().transition(
                broadcastStatus="testing",
                id=broadcast_insert_response["id"],
                part="status"
            ).execute()
            
            # Then transition to live state
            youtube.liveBroadcasts().transition(
                broadcastStatus="live",
                id=broadcast_insert_response["id"],
                part="status"
            ).execute()
            
            return broadcast_insert_response["id"]
            
        except Exception as e:
            logger.error(f"Failed to create broadcast: {str(e)}")
            raise

    def create_stream(self, youtube):
        """Create YouTube stream"""
        try:
            stream_insert_response = youtube.liveStreams().insert(
                part="snippet,cdn,contentDetails",
                body={
                    "snippet": {
                        "title": "Stream"
                    },
                    "cdn": {
                        "frameRate": "variable",
                        "ingestionType": "rtmp",
                        "resolution": "variable",
                        "format": "1080p"
                    },
                    "contentDetails": {
                        "isReusable": True,
                        "enableAutoStop": False
                    }
                }
            ).execute()
            
            return stream_insert_response["id"]
            
        except Exception as e:
            logger.error(f"Failed to create stream: {str(e)}")
            raise

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
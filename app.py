from flask import Flask, request, jsonify, session, redirect
from flask_cors import CORS
from youtube_streamer import YouTubeStreamer, YouTubeStreamError, AuthenticationError, BroadcastError, StreamError, FFmpegError
import os
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import logging
import secrets
import urllib.parse
from datetime import timedelta
import json
from google.oauth2.credentials import Credentials

load_dotenv()  # Load environment variables

app = Flask(__name__)

# Session configuration
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32))
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.permanent_session_lifetime = timedelta(days=1)

# CORS configuration
CORS(app, resources={
    r"/*": {
        "origins": [
            "https://ytsattu.netlify.app",
            "https://ytstream-py.onrender.com"
        ],
        "supports_credentials": True,
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Origin"],
        "expose_headers": ["Content-Type", "Authorization"],
        "max_age": 600
    }
})

# Configuration
UPLOAD_FOLDER = 'temp_uploads'
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mkv', 'mov'}

# Ensure upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.before_request
def log_request_info():
    logger.info('Headers: %s', request.headers)
    logger.info('Body: %s', request.get_data())

@app.before_request
def make_session_permanent():
    session.permanent = True

@app.before_request
def check_session():
    if not session.get('youtube_credentials') and request.endpoint not in ['youtube_auth', 'auth_callback', 'home', 'health_check']:
        return jsonify({
            'authenticated': False,
            'message': 'Session expired'
        }), 401

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def home():
    return jsonify({"status": "healthy", "message": "Server is running"})

@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "port": os.environ.get('PORT', 10000)
    })

@app.route('/start-stream', methods=['POST'])
def start_stream():
    try:
        logger.info("Starting new stream request")
        
        # Check authentication
        credentials_json = session.get('youtube_credentials')
        if not credentials_json:
            return jsonify({
                'success': False,
                'message': 'Not authenticated. Please connect your YouTube account first.',
                'error_type': 'auth_error'
            }), 401
        
        # Check file
        if 'video' not in request.files:
            return jsonify({
                'success': False, 
                'message': 'No video file provided',
                'error_type': 'validation_error'
            }), 400
        
        file = request.files['video']
        title = request.form.get('title', 'Untitled Stream')
        
        if file.filename == '':
            return jsonify({
                'success': False, 
                'message': 'No selected file',
                'error_type': 'validation_error'
            }), 400
            
        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'message': 'Invalid file type. Allowed types: mp4, avi, mkv, mov',
                'error_type': 'validation_error'
            }), 400

        try:
            # Save file temporarily
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            logger.info(f"File saved to {filepath}")
            
            # Start stream
            streamer = YouTubeStreamer()
            credentials = Credentials.from_authorized_user_info(
                json.loads(credentials_json),
                streamer.scopes
            )
            
            result = streamer.start_stream(credentials, filepath, title)
            
            return jsonify({
                'success': True,
                'message': 'Stream started successfully',
                'broadcast_url': result['broadcast_url']
            })
            
        except AuthenticationError as e:
            return jsonify({
                'success': False,
                'message': str(e),
                'error_type': 'auth_error'
            }), 401
            
        except BroadcastError as e:
            return jsonify({
                'success': False,
                'message': str(e),
                'error_type': 'broadcast_error'
            }), 500
            
        except StreamError as e:
            return jsonify({
                'success': False,
                'message': str(e),
                'error_type': 'stream_error'
            }), 500
            
        except FFmpegError as e:
            return jsonify({
                'success': False,
                'message': str(e),
                'error_type': 'ffmpeg_error'
            }), 500
            
        except Exception as e:
            logger.error(f"Streaming error: {str(e)}")
            return jsonify({
                'success': False,
                'message': f"Failed to start stream: {str(e)}",
                'error_type': 'unknown_error'
            }), 500
            
        finally:
            # Cleanup
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Cleaned up file: {filepath}")
                    
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"Server error: {str(e)}",
            'error_type': 'server_error'
        }), 500

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "Internal Server Error",
        "message": str(error)
    }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Not Found",
        "message": "The requested resource was not found"
    }), 404

@app.route('/auth/youtube', methods=['GET'])
def youtube_auth():
    try:
        streamer = YouTubeStreamer()
        auth_url, state = streamer.get_auth_url()  # Get both URL and state
        
        if not auth_url:
            raise Exception("Failed to generate auth URL")
            
        # Store state in session
        session['oauth_state'] = state
            
        return jsonify({
            'success': True,
            'authUrl': auth_url
        })
        
    except Exception as e:
        logger.error(f"Auth error: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

@app.route('/auth/callback')
def auth_callback():
    try:
        code = request.args.get('code')
        state = request.args.get('state')
        
        # Verify state
        if state != session.get('oauth_state'):
            logger.error("State mismatch")
            return redirect('https://ytsattu.netlify.app?error=invalid_state')
            
        if not code:
            logger.error("No authorization code received")
            return redirect('https://ytsattu.netlify.app?error=no_code')
            
        streamer = YouTubeStreamer()
        try:
            credentials = streamer.get_credentials(code, state)  # Pass state
            session['youtube_credentials'] = credentials.to_json()
            
            # Get channel info immediately after auth
            youtube = streamer.get_youtube_service(credentials.to_json())
            channel_info = streamer.get_channel_info(youtube)
            
            if channel_info:
                return redirect('https://ytsattu.netlify.app?auth=success')
            else:
                return redirect('https://ytsattu.netlify.app?error=no_channel')
                
        except Exception as e:
            logger.error(f"Failed to get credentials: {str(e)}")
            return redirect(f'https://ytsattu.netlify.app?error=auth_failed&message={urllib.parse.quote(str(e))}')
            
    except Exception as e:
        logger.error(f"Callback error: {str(e)}")
        return redirect(f'https://ytsattu.netlify.app?error=server_error&message={urllib.parse.quote(str(e))}')

@app.route('/auth/status')
def auth_status():
    try:
        credentials_json = session.get('youtube_credentials')
        if not credentials_json:
            return jsonify({
                'authenticated': False,
                'message': 'Not authenticated'
            })
        
        streamer = YouTubeStreamer()
        youtube = streamer.get_youtube_service(credentials_json)
        channel_info = streamer.get_channel_info(youtube)
        
        if not channel_info:
            # Clear invalid session
            session.pop('youtube_credentials', None)
            return jsonify({
                'authenticated': False,
                'message': 'No channel found'
            })
        
        return jsonify({
            'authenticated': True,
            'channelInfo': channel_info
        })
    except Exception as e:
        logger.error(f"Status check error: {str(e)}")
        # Clear invalid session
        session.pop('youtube_credentials', None)
        return jsonify({
            'authenticated': False,
            'error': str(e)
        })

# Add CORS headers to all responses
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

if __name__ == '__main__':
    # Get port from environment variable or default to 10000
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
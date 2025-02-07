from flask import Flask, request, jsonify, session, redirect
from flask_cors import CORS
from youtube_streamer import YouTubeStreamer
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
app.secret_key = secrets.token_hex(16)  # Add this for session management
app.permanent_session_lifetime = timedelta(days=1)  # Session expires in 1 day
CORS(app, resources={
    r"/*": {
        "origins": [
            "http://localhost:3000",
            "https://ytstream-py.onrender.com",
            "https://ytsattu.netlify.app"  # Add your Netlify domain
        ],
        "supports_credentials": True,
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Origin"]
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
                'message': 'Not authenticated. Please connect your YouTube account first.'
            }), 401
        
        # Check file
        if 'video' not in request.files:
            return jsonify({
                'success': False, 
                'message': 'No video file provided'
            }), 400
        
        file = request.files['video']
        title = request.form.get('title', 'Untitled Stream')
        
        if file.filename == '':
            return jsonify({
                'success': False, 
                'message': 'No selected file'
            }), 400
            
        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'message': 'Invalid file type. Allowed types: mp4, avi, mkv, mov'
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
            
        except Exception as e:
            logger.error(f"Streaming error: {str(e)}")
            return jsonify({
                'success': False,
                'message': f"Failed to start stream: {str(e)}"
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
            'message': f"Server error: {str(e)}"
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
        auth_url = streamer.get_auth_url()  # Now returns only URL
        
        if not auth_url:
            raise Exception("Failed to generate auth URL")
            
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
        if not code:
            return redirect('https://ytsattu.netlify.app?error=' + 
                          urllib.parse.quote('No authorization code received'))
            
        streamer = YouTubeStreamer()
        try:
            credentials = streamer.get_credentials(code)  # Updated method name
            session['youtube_credentials'] = credentials.to_json()
            return redirect('https://ytsattu.netlify.app')
            
        except Exception as e:
            logger.error(f"Failed to get credentials: {str(e)}")
            return redirect('https://ytsattu.netlify.app?error=' + 
                          urllib.parse.quote(f'Authentication failed: {str(e)}'))
            
    except Exception as e:
        logger.error(f"Callback error: {str(e)}")
        return redirect('https://ytsattu.netlify.app?error=' + 
                      urllib.parse.quote(str(e)))

@app.route('/auth/status')
def auth_status():
    try:
        credentials_json = session.get('youtube_credentials')
        if not credentials_json:
            return jsonify({
                'authenticated': False
            })
        
        streamer = YouTubeStreamer()
        youtube = streamer.get_youtube_service(credentials_json)
        channel_info = streamer.get_channel_info(youtube)
        
        return jsonify({
            'authenticated': True,
            'channelInfo': channel_info
        })
    except Exception as e:
        logger.error(f"Status check error: {str(e)}")
        return jsonify({
            'authenticated': False,
            'error': str(e)
        })

if __name__ == '__main__':
    # Get port from environment variable or default to 10000
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
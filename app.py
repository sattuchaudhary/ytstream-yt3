from flask import Flask, request, jsonify, session, redirect
from flask_cors import CORS
from youtube_streamer import YouTubeStreamer
import os
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import logging

load_dotenv()  # Load environment variables

app = Flask(__name__)
CORS(app, resources={
    r"/*": {
        "origins": [
            "http://localhost:3000",  # Local development
            "https://ytstream-py.onrender.com",  # Backend
            "http://localhost:5000"  # Frontend development
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
        
        if 'video' not in request.files:
            logger.error("No video file in request")
            return jsonify({
                'success': False, 
                'message': 'No video file provided'
            }), 400
        
        file = request.files['video']
        title = request.form.get('title', 'Untitled Stream')
        logger.info(f"Received file: {file.filename}, title: {title}")
        
        if file.filename == '':
            logger.error("Empty filename")
            return jsonify({
                'success': False, 
                'message': 'No selected file'
            }), 400
            
        if not allowed_file(file.filename):
            logger.error(f"Invalid file type: {file.filename}")
            return jsonify({
                'success': False,
                'message': 'Invalid file type. Allowed types: mp4, avi, mkv, mov'
            }), 400

        try:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            logger.info(f"File saved to {filepath}")
            
            # Initialize YouTube streamer
            streamer = YouTubeStreamer()
            logger.info("Authenticating with YouTube...")
            youtube = streamer.authenticate()
            
            # Create broadcast and stream
            logger.info("Creating broadcast...")
            broadcast_id = streamer.create_broadcast(youtube, title, f"Stream of {filename}")
            logger.info(f"Broadcast created with ID: {broadcast_id}")
            
            logger.info("Creating stream...")
            stream_id = streamer.create_stream(youtube)
            logger.info(f"Stream created with ID: {stream_id}")
            
            # Bind broadcast to stream
            logger.info("Binding broadcast to stream...")
            streamer.bind_broadcast(youtube, broadcast_id, stream_id)
            
            # Get stream URL and start streaming
            stream_url = streamer.get_stream_url(youtube, stream_id)
            logger.info(f"Starting stream to URL: {stream_url}")
            streamer.stream_video(filepath, stream_url)
            
            return jsonify({
                'success': True,
                'message': 'Stream started successfully',
                'streamUrl': f'https://youtube.com/watch?v={broadcast_id}'
            })
        
        except Exception as e:
            logger.error(f"Streaming error: {str(e)}", exc_info=True)
            return jsonify({
                'success': False,
                'message': f"Failed to start stream: {str(e)}"
            }), 500
        
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Cleaned up file: {filepath}")
                    
    except Exception as e:
        logger.error(f"Server error: {str(e)}", exc_info=True)
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
        auth_url = streamer.get_auth_url()
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
        streamer = YouTubeStreamer()
        credentials = streamer.get_credentials_from_code(code)
        # Store credentials in session or database
        session['youtube_credentials'] = credentials.to_json()
        return redirect('http://localhost:3000')  # Redirect to frontend
    except Exception as e:
        logger.error(f"Callback error: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

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
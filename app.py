from flask import Flask, request, jsonify
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
            "http://localhost:3000",
            "https://your-frontend-domain.com"  # Replace with your frontend domain
        ]
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
        if 'video' not in request.files:
            return jsonify({'success': False, 'message': 'No video file provided'}), 400
        
        file = request.files['video']
        title = request.form.get('title', 'Untitled Stream')
        
        if file.filename == '':
            return jsonify({'success': False, 'message': 'No selected file'}), 400
            
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            try:
                # Initialize YouTube streamer
                streamer = YouTubeStreamer()
                youtube = streamer.authenticate()
                
                # Create broadcast and stream
                broadcast_id = streamer.create_broadcast(youtube, title, f"Stream of {filename}")
                stream_id = streamer.create_stream(youtube)
                
                # Bind broadcast to stream
                streamer.bind_broadcast(youtube, broadcast_id, stream_id)
                
                # Start streaming
                stream_url = streamer.get_stream_url(youtube, stream_id)
                streamer.stream_video(filepath, stream_url)
                
                return jsonify({
                    'success': True,
                    'message': 'Stream started successfully',
                    'streamUrl': f'https://youtube.com/watch?v={broadcast_id}'
                })
            
            finally:
                # Clean up the uploaded file
                if os.path.exists(filepath):
                    os.remove(filepath)
                    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

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

if __name__ == '__main__':
    # Get port from environment variable or default to 10000
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
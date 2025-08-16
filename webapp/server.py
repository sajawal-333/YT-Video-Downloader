import os
import threading
import time
import json
import re
from pathlib import Path
from typing import Optional
import tempfile
import shutil
import logging
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory, send_file, Response, stream_template
from flask_cors import CORS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    import yt_dlp
    logger.info("yt-dlp imported successfully")
except Exception as e:
    logger.error(f"Failed to import yt-dlp: {e}")
    yt_dlp = None

app = Flask(__name__, static_folder="static", static_url_path="/")
CORS(app)

def build_format_string(max_height: str) -> str:
    """Build format string for yt-dlp based on quality selection"""
    if max_height == 'best':
        return 'bestvideo+bestaudio/best'
    try:
        h = int(max_height.replace('p', ''))
    except Exception:
        return 'bestvideo+bestaudio/best'
    return (
        f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={h}]+bestaudio/"
        f"best[height<={h}]"
    )

def build_opts(output_dir: Path, quality: str, output_type: str, mp3_bitrate: int,
               referer: Optional[str] = None, user_agent: Optional[str] = None,
               extra_headers: Optional[dict] = None) -> dict:
    """Build yt-dlp options dictionary"""
    fmt = build_format_string(quality)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Modern headers that work better with current YouTube
    headers = {
        'User-Agent': user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
    }
    
    if referer:
        headers['Referer'] = referer
    if extra_headers:
        headers.update(extra_headers)
    
    opts = {
        'format': fmt,
        'outtmpl': str(output_dir / '%(title)s [%(id)s].%(ext)s'),
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'geo_bypass': True,
        'extractor_retries': 3,
        'fragment_retries': 3,
        'retries': 3,
        'socket_timeout': 30,
        'extractor_timeout': 30,
        'sleep_interval': 1,
        'max_sleep_interval': 5,
        'ignoreerrors': False,
        'no_check_certificate': True,
        'prefer_insecure': True,
        'http_headers': headers,
        'cookiesfrombrowser': None,
        'cookiefile': None,
        'proxy': None,
    }
    
    # Post-processing for different output types
    if output_type == 'mp3':
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': str(int(mp3_bitrate)),
        }]
    elif output_type == 'mp4':
        opts['merge_output_format'] = 'mp4'
        opts['postprocessors'] = [{
            'key': 'FFmpegVideoRemuxer',
            'preferedformat': 'mp4',
        }]
    
    return opts

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe download"""
    # Remove problematic characters
    filename = re.sub(r'[^\w\-_\.]', '_', filename)
    # Ensure it's not too long
    if len(filename) > 100:
        name, ext = os.path.splitext(filename)
        filename = name[:90] + ext
    # Ensure it starts with a safe character
    if filename and not filename[0].isalnum():
        filename = 'video_' + filename
    return filename

@app.route('/api/direct-download', methods=['POST'])
def direct_download():
    """Direct download endpoint that streams the file to user's browser"""
    temp_dir = None
    permanent_file = None
    
    try:
        if yt_dlp is None:
            return jsonify({'ok': False, 'error': 'yt-dlp not available on server'}), 500

        # Get JSON data
        data = request.get_json(force=True)
        if not data:
            return jsonify({'ok': False, 'error': 'Invalid JSON data'}), 400

        url = (data.get('url') or '').strip()
        quality = (data.get('quality') or 'best').strip()
        output_type = (data.get('outputType') or 'mp4').strip()
        mp3_bitrate = int(data.get('mp3Bitrate') or 192)
        referer = (data.get('referer') or '').strip() or None
        user_agent = (data.get('userAgent') or '').strip() or None
        extra_headers = data.get('headers') or {}

        if not url:
            return jsonify({'ok': False, 'error': 'URL required'}), 400

        logger.info(f"Starting download for URL: {url}")

        # Create temporary directory for this download
        temp_dir = Path(tempfile.mkdtemp())
        logger.info(f"Created temp directory: {temp_dir}")
        
        # Build options
        opts = build_opts(temp_dir, quality, output_type, mp3_bitrate, referer, user_agent, extra_headers)
        
        # Download the video
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                # First extract info to get video details
                logger.info("Extracting video info...")
                info = ydl.extract_info(url, download=False)
                video_title = info.get('title', 'video')
                video_id = info.get('id', 'unknown')
                
                logger.info(f"Video title: {video_title}")
                logger.info(f"Video ID: {video_id}")
                
                # Download the video
                logger.info("Starting download...")
                ydl.download([url])
                
        except Exception as e:
            logger.error(f"Download failed: {e}")
            # Try fallback approach
            try:
                logger.info("Trying fallback approach...")
                fallback_opts = {
                    'format': 'best',
                    'outtmpl': str(temp_dir / '%(title)s [%(id)s].%(ext)s'),
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'no_check_certificate': True,
                    'prefer_insecure': True,
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate',
                        'Connection': 'keep-alive',
                    }
                }
                with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                    ydl.download([url])
            except Exception as fallback_error:
                logger.error(f"Fallback approach also failed: {fallback_error}")
                raise fallback_error
        
        # Find the downloaded file
        downloaded_files = list(temp_dir.glob('*'))
        if not downloaded_files:
            return jsonify({'ok': False, 'error': 'No file was downloaded'}), 500
        
        file_path = downloaded_files[0]
        logger.info(f"Downloaded file: {file_path}")
        
        # Get file info
        file_size = file_path.stat().st_size
        if file_size == 0:
            return jsonify({'ok': False, 'error': 'Downloaded file is empty'}), 500
        
        # Create filename
        original_filename = file_path.name
        filename = sanitize_filename(original_filename)
        
        # Copy file to a permanent location
        permanent_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1])
        permanent_file.close()
        
        shutil.copy2(file_path, permanent_file.name)
        logger.info(f"Copied to permanent location: {permanent_file.name}")
        
        # Clean up temp directory
        try:
            shutil.rmtree(temp_dir)
            logger.info(f"Cleaned up temp directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"Error cleaning up {temp_dir}: {e}")
        
        # Serve the file
        response = send_file(
            permanent_file.name,
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
        
        # Clean up permanent file after response
        @response.call_on_close
        def cleanup():
            try:
                os.unlink(permanent_file.name)
                logger.info(f"Cleaned up permanent file: {permanent_file.name}")
            except Exception as e:
                logger.warning(f"Error cleaning up {permanent_file.name}: {e}")
        
        logger.info(f"Download completed successfully: {filename}")
        return response
        
    except Exception as e:
        logger.error(f"Error in direct_download: {str(e)}")
        
        # Clean up on error
        if temp_dir and temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up temp directory on error: {temp_dir}")
            except:
                pass
        
        if permanent_file and os.path.exists(permanent_file.name):
            try:
                os.unlink(permanent_file.name)
                logger.info(f"Cleaned up permanent file on error: {permanent_file.name}")
            except:
                pass
        
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/download', methods=['POST'])
def api_download():
    """Legacy endpoint for compatibility"""
    return jsonify({'ok': True, 'message': 'Use direct-download endpoint for immediate download'})

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/test')
def test():
    """Test endpoint to check if server is working"""
    return jsonify({
        'ok': True, 
        'message': 'Server is working',
        'yt_dlp_available': yt_dlp is not None,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/health')
def health():
    """Health check endpoint for deployment platforms"""
    return jsonify({
        'status': 'healthy',
        'yt_dlp_available': yt_dlp is not None,
        'timestamp': datetime.now().isoformat()
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)



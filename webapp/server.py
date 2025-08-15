import os
import threading
import time
import json
import re
from pathlib import Path
from typing import Optional
import tempfile
import shutil

from flask import Flask, request, jsonify, send_from_directory, send_file, Response, stream_template
from flask_cors import CORS

try:
    import yt_dlp
except Exception as e:
    yt_dlp = None

app = Flask(__name__, static_folder="static", static_url_path="/")
CORS(app)

def build_format_string(max_height: str) -> str:
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
    fmt = build_format_string(quality)
    output_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        'format': fmt,
        'outtmpl': str(output_dir / '%(title)s [%(id)s].%(ext)s'),
        'noplaylist': True,
        'progress': True,
        'quiet': True,
        'no_warnings': True,
        'geo_bypass': True,
    }
    headers = {}
    if user_agent:
        headers['User-Agent'] = user_agent
    if referer:
        headers['Referer'] = referer
    if extra_headers:
        headers.update(extra_headers)
    if headers:
        opts['http_headers'] = headers
    # Post-processing
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


@app.route('/api/direct-download', methods=['POST'])
def direct_download():
    """Direct download endpoint that streams the file to user's browser"""
    try:
        if yt_dlp is None:
            return jsonify({'ok': False, 'error': 'yt-dlp not available on server'}), 500

        # Get JSON data
        data = request.get_json(force=True)

        url = (data.get('url') or '').strip()
        quality = (data.get('quality') or 'best').strip()
        output_type = (data.get('outputType') or 'mp4').strip()
        mp3_bitrate = int(data.get('mp3Bitrate') or 192)
        referer = (data.get('referer') or '').strip() or None
        user_agent = (data.get('userAgent') or '').strip() or None
        extra_headers = data.get('headers') or {}

        if not url:
            return jsonify({'ok': False, 'error': 'URL required'}), 400

        # Create temporary directory for this download
        temp_dir = Path(tempfile.mkdtemp())
        
        try:
            opts = build_opts(temp_dir, quality, output_type, mp3_bitrate, referer, user_agent, extra_headers)
            
            # Download the file
            with yt_dlp.YoutubeDL(opts) as ydl:
                # Get video info first
                info = ydl.extract_info(url, download=False)
                video_title = info.get('title', 'video')
                video_id = info.get('id', 'unknown')
                
                # Download the file
                ydl.download([url])
                
                # Find the downloaded file
                downloaded_files = list(temp_dir.glob('*'))
                if not downloaded_files:
                    return jsonify({'ok': False, 'error': 'No file downloaded'}), 500
                
                file_path = downloaded_files[0]
                filename = file_path.name
                
                # Sanitize filename to remove problematic characters
                filename = re.sub(r'[^\w\-_\.]', '_', filename)
                # Ensure it's not too long
                if len(filename) > 100:
                    name, ext = os.path.splitext(filename)
                    filename = name[:90] + ext
                # Ensure it starts with a safe character
                if filename and not filename[0].isalnum():
                    filename = 'video_' + filename
                
                # Stream the file to the user
                def generate():
                    try:
                        with open(file_path, 'rb') as f:
                            while True:
                                chunk = f.read(8192)  # 8KB chunks
                                if not chunk:
                                    break
                                yield chunk
                    finally:
                        # Clean up temporary files
                        try:
                            shutil.rmtree(temp_dir)
                        except:
                            pass
                
                # Determine MIME type
                mime_type = 'application/octet-stream'
                if filename.endswith('.mp4'):
                    mime_type = 'video/mp4'
                elif filename.endswith('.mp3'):
                    mime_type = 'audio/mpeg'
                elif filename.endswith('.webm'):
                    mime_type = 'video/webm'
                
                return Response(
                    generate(),
                    mimetype=mime_type,
                    headers={
                        'Content-Disposition': f'attachment; filename="{filename}"',
                        'Content-Type': mime_type
                    }
                )
                
        except Exception as e:
            # Clean up on error
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
            print(f"Error in direct_download: {str(e)}")
            return jsonify({'ok': False, 'error': str(e)}), 500
            
    except Exception as outer_e:
        print(f"Outer error in direct_download: {str(outer_e)}")
        return jsonify({'ok': False, 'error': f'Server error: {str(outer_e)}'}), 500


@app.route('/api/download', methods=['POST'])
def api_download():
    """Legacy endpoint for progress tracking (optional)"""
    if yt_dlp is None:
        return jsonify({'ok': False, 'error': 'yt-dlp not available on server'}), 500

    data = request.get_json(force=True)
    url = (data.get('url') or '').strip()
    
    if not url:
        return jsonify({'ok': False, 'error': 'URL required'}), 400

    # For direct download, we don't need job tracking
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
        'yt_dlp_available': yt_dlp is not None
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)



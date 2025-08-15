import os
import re
import subprocess
from pathlib import Path
from typing import Optional
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS

try:
    import yt_dlp
except Exception:
    yt_dlp = None

app = Flask(__name__, static_folder="static", static_url_path="/")
CORS(app)

# ===== Helper Functions =====
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

def build_opts(quality: str, output_type: str, mp3_bitrate: int,
               referer: Optional[str] = None, user_agent: Optional[str] = None,
               extra_headers: Optional[dict] = None) -> dict:
    fmt = build_format_string(quality)
    opts = {
        'format': fmt,
        'noplaylist': True,
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

    if output_type == 'mp3':
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': str(int(mp3_bitrate)),
        }]
    elif output_type == 'mp4':
        opts['merge_output_format'] = 'mp4'

    return opts

# ===== Direct Streaming Download =====
@app.route('/api/direct-download', methods=['GET', 'POST'])
def direct_download():
    """Stream file directly to user's browser without saving to server"""
    try:
        if yt_dlp is None:
            return jsonify({'ok': False, 'error': 'yt-dlp not available on server'}), 500

        # Accept GET query params or POST JSON
        if request.method == 'GET':
            data = request.args.to_dict()
        else:
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

        # Get video info for filename
        ydl_info_opts = build_opts(quality, output_type, mp3_bitrate, referer, user_agent, extra_headers)
        ydl_info_opts['skip_download'] = True
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        filename = f"{info.get('title', 'video')} [{info.get('id', 'unknown')}].{output_type}"

        # Clean filename
        filename = re.sub(r'[^\w\-_\.]', '_', filename)
        if len(filename) > 100:
            name, ext = os.path.splitext(filename)
            filename = name[:90] + ext

        def generate():
            """Yield video chunks from yt-dlp in real-time"""
            fmt = build_format_string(quality)
            cmd = ['yt-dlp', '-o', '-', '-f', fmt, url]
            if output_type == 'mp3':
                cmd.extend(['--extract-audio', '--audio-format', 'mp3', '--audio-quality', str(mp3_bitrate)])
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for chunk in iter(lambda: proc.stdout.read(8192), b''):
                yield chunk
            proc.stdout.close()
            proc.wait()

        # Set MIME type
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
        return jsonify({'ok': False, 'error': str(e)}), 500

# ===== Legacy Endpoint =====
@app.route('/api/download', methods=['POST'])
def api_download():
    """Legacy endpoint for progress tracking"""
    return jsonify({'ok': True, 'message': 'Use direct-download endpoint for immediate download'})

# ===== Frontend =====
@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

# ===== Test Endpoint =====
@app.route('/api/test')
def test():
    return jsonify({
        'ok': True,
        'message': 'Server is working',
        'yt_dlp_available': yt_dlp is not None
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

import os
from pathlib import Path
from typing import Optional
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
import yt_dlp

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

@app.route('/api/direct-download', methods=['GET', 'POST'])
def direct_download():
    """Stream file directly to user's browser without storing full file on server"""
    # Get data
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

    try:
        opts = build_opts(quality, output_type, mp3_bitrate, referer, user_agent, extra_headers)

        # Get video info to determine filename
        with yt_dlp.YoutubeDL({**opts, 'skip_download': True}) as ydl:
            info = ydl.extract_info(url, download=False)
        filename = f"{info.get('title', 'video')} [{info.get('id', 'unknown')}].{output_type}"

        def generate():
            """Generator that streams from yt-dlp directly"""
            with yt_dlp.YoutubeDL({**opts, 'outtmpl': '-', 'quiet': True}) as ydl:
                # yt-dlp will write binary data to stdout
                proc = ydl.download([url])  # Downloads to stdout
            yield from proc

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

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

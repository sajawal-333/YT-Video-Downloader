import os
import re
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

try:
    import yt_dlp
except Exception:
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
        'quiet': True,
        'no_warnings': True,
        'geo_bypass': True,
        'retries': 5,
        'socket_timeout': 60,
        'extractor_timeout': 60,
    }

    headers = {
        'User-Agent': user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                                    'Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
    }

    if referer:
        headers['Referer'] = referer
    if extra_headers:
        headers.update(extra_headers)

    opts['http_headers'] = headers

    # ✅ NEW: Load cookies.txt if it exists
    cookie_path = Path(__file__).parent / 'cookies.txt'
    if cookie_path.exists():
        opts['cookiefile'] = str(cookie_path)
        print(f"Using cookies from: {cookie_path}")

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
    try:
        if yt_dlp is None:
            return jsonify({'ok': False, 'error': 'yt-dlp not available on server'}), 500

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

        # Temporary folder for download
        temp_dir = Path(tempfile.mkdtemp())

        try:
            opts = build_opts(temp_dir, quality, output_type, mp3_bitrate, referer, user_agent, extra_headers)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_file = Path(ydl.prepare_filename(info))

            if not downloaded_file.exists():
                return jsonify({'ok': False, 'error': 'No file downloaded'}), 500

            # Sanitize filename
            filename = re.sub(r'[^\w\-_\.]', '_', downloaded_file.name)

            # Stream to browser
            response = send_file(
                downloaded_file,
                as_attachment=True,
                download_name=filename,
                mimetype='application/octet-stream'
            )

            # Cleanup temp folder after sending
            @response.call_on_close
            def cleanup():
                try:
                    shutil.rmtree(temp_dir)
                    print(f"Deleted temp folder: {temp_dir}")
                except Exception as e:
                    print(f"Cleanup error: {e}")

            return response

        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({'ok': False, 'error': f'Download failed: {str(e)}'}), 500

    except Exception as e:
        return jsonify({'ok': False, 'error': f'Server error: {str(e)}'}), 500


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


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

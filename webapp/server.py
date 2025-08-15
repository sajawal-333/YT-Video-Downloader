import os
import threading
import time
from pathlib import Path
from typing import Optional
import glob

from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS

try:
    import yt_dlp
except Exception as e:
    yt_dlp = None

app = Flask(__name__, static_folder="static", static_url_path="/")
CORS(app)

_jobs = {}
_downloaded_files = {}  # Track downloaded files for each job

# Cleanup old files periodically
def cleanup_old_files():
    """Clean up files older than 1 hour"""
    while True:
        try:
            current_time = time.time()
            downloads_dir = Path('downloads')
            if downloads_dir.exists():
                for file_path in downloads_dir.glob('*'):
                    if file_path.is_file():
                        # Remove files older than 1 hour
                        if current_time - file_path.stat().st_mtime > 3600:
                            try:
                                file_path.unlink()
                                print(f"Cleaned up old file: {file_path}")
                            except Exception as e:
                                print(f"Error cleaning up {file_path}: {e}")
        except Exception as e:
            print(f"Error in cleanup: {e}")
        time.sleep(300)  # Run cleanup every 5 minutes

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_old_files, daemon=True)
cleanup_thread.start()


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


@app.route('/api/download', methods=['POST'])
def api_download():
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
    out_dir = Path(data.get('outputDir') or 'downloads').resolve()

    if not url:
        return jsonify({'ok': False, 'error': 'URL required'}), 400

    job_id = os.urandom(6).hex()
    _jobs[job_id] = {'status': 'queued', 'progress': 0, 'message': 'Queued'}
    _downloaded_files[job_id] = []  # Track files for this job

    def worker():
        try:
            _jobs[job_id]['status'] = 'running'
            opts = build_opts(out_dir, quality, output_type, mp3_bitrate, referer, user_agent, extra_headers)

            def hook(d):
                status = d.get('status')
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes') or 0
                speed = d.get('speed') or 0
                eta = d.get('eta') or 0
                if status == 'downloading':
                    pct = int(downloaded * 100 / total) if total else 0
                    _jobs[job_id]['progress'] = pct
                    _jobs[job_id]['message'] = 'downloading'
                elif status == 'finished':
                    _jobs[job_id]['progress'] = 100
                    _jobs[job_id]['message'] = 'processing'
                # Always publish metrics
                _jobs[job_id]['status'] = status or _jobs[job_id].get('status', 'running')
                _jobs[job_id]['totalBytes'] = int(total)
                _jobs[job_id]['downloadedBytes'] = int(downloaded)
                _jobs[job_id]['speedBps'] = int(speed)
                _jobs[job_id]['etaSec'] = int(eta)

            opts['progress_hooks'] = [hook]
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            
            # Find downloaded files
            if out_dir.exists():
                for file_path in out_dir.glob('*'):
                    if file_path.is_file():
                        _downloaded_files[job_id].append({
                            'filename': file_path.name,
                            'size': file_path.stat().st_size,
                            'path': str(file_path)
                        })
            
            _jobs[job_id]['status'] = 'done'
            _jobs[job_id]['progress'] = 100
            _jobs[job_id]['message'] = 'completed'
            _jobs[job_id]['files'] = _downloaded_files[job_id]
        except Exception as e:
            _jobs[job_id]['status'] = 'error'
            _jobs[job_id]['message'] = str(e)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return jsonify({'ok': True, 'jobId': job_id})


@app.route('/api/status/<job_id>')
def api_status(job_id):
    job = _jobs.get(job_id)
    if not job:
        return jsonify({'ok': False, 'error': 'job not found'}), 404
    
    # Include file information if job is done
    if job.get('status') == 'done' and job_id in _downloaded_files:
        job['files'] = _downloaded_files[job_id]
    
    return jsonify({'ok': True, 'job': job})


@app.route('/api/download-file/<job_id>/<filename>')
def download_file(job_id, filename):
    """Serve downloaded files to users"""
    if job_id not in _downloaded_files:
        return jsonify({'ok': False, 'error': 'job not found'}), 404
    
    # Find the file in the job's downloaded files
    file_info = None
    for file_data in _downloaded_files[job_id]:
        if file_data['filename'] == filename:
            file_info = file_data
            break
    
    if not file_info:
        return jsonify({'ok': False, 'error': 'file not found'}), 404
    
    file_path = Path(file_info['path'])
    if not file_path.exists():
        return jsonify({'ok': False, 'error': 'file not found on server'}), 404
    
    # Serve the file for download
    return send_file(
        file_path,
        as_attachment=True,
        download_name=filename,
        mimetype='application/octet-stream'
    )


@app.route('/api/list-files/<job_id>')
def list_files(job_id):
    """List all files for a completed job"""
    if job_id not in _downloaded_files:
        return jsonify({'ok': False, 'error': 'job not found'}), 404
    
    return jsonify({
        'ok': True, 
        'files': _downloaded_files[job_id]
    })


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)



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

# Try alternative downloader
try:
    import yt_dlp as yt_dlp_alt
except Exception as e:
    yt_dlp_alt = None

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
        'extractor_retries': 5,
        'fragment_retries': 5,
        'retries': 5,
        'socket_timeout': 60,
        'extractor_timeout': 60,
        'sleep_interval': 2,
        'max_sleep_interval': 10,
        'ignoreerrors': False,
        'no_check_certificate': True,
        'prefer_insecure': True,
        'http_chunk_size': 10485760,  # 10MB chunks
    }
    
    # Advanced headers to bypass 403 errors
    headers = {
        'User-Agent': user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
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
        'Sec-Ch-Ua': '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
    }
    
    if referer:
        headers['Referer'] = referer
    if extra_headers:
        headers.update(extra_headers)
    
    opts['http_headers'] = headers
    
    # Add cookies and additional bypass options
    opts['cookiesfrombrowser'] = None
    opts['cookiefile'] = None
    
    # Add proxy rotation for better bypass
    import random
    free_proxies = [
        None,  # Direct connection
        'socks5://127.0.0.1:1080',  # Common SOCKS proxy
        'http://127.0.0.1:8080',    # Common HTTP proxy
    ]
    opts['proxy'] = random.choice(free_proxies)
    
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
            
            # Multi-strategy download with aggressive bypass
            download_success = False
            last_error = None
            
            # Strategy 1: Original settings
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    video_title = info.get('title', 'video')
                    video_id = info.get('id', 'unknown')
                    ydl.download([url])
                    download_success = True
            except Exception as e:
                last_error = e
                print(f"Strategy 1 failed: {e}")
            
            # Strategy 2: Different format + mobile user agent
            if not download_success:
                try:
                    opts2 = opts.copy()
                    opts2['format'] = 'best'
                    opts2['http_headers']['User-Agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Mobile/15E148 Safari/604.1'
                    with yt_dlp.YoutubeDL(opts2) as ydl:
                        ydl.download([url])
                        download_success = True
                except Exception as e:
                    last_error = e
                    print(f"Strategy 2 failed: {e}")
            
            # Strategy 3: Minimal settings + different approach
            if not download_success:
                try:
                    opts3 = {
                        'format': 'best',
                        'outtmpl': str(temp_dir / '%(title)s [%(id)s].%(ext)s'),
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'http_headers': {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                            'Accept-Language': 'en-US,en;q=0.5',
                            'Accept-Encoding': 'gzip, deflate',
                            'Connection': 'keep-alive',
                        }
                    }
                    with yt_dlp.YoutubeDL(opts3) as ydl:
                        ydl.download([url])
                        download_success = True
                except Exception as e:
                    last_error = e
                    print(f"Strategy 3 failed: {e}")
            
            # Strategy 4: Ultra-minimal approach
            if not download_success:
                try:
                    opts4 = {
                        'format': 'best',
                        'outtmpl': str(temp_dir / '%(title)s [%(id)s].%(ext)s'),
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'no_check_certificate': True,
                        'prefer_insecure': True,
                    }
                    with yt_dlp.YoutubeDL(opts4) as ydl:
                        ydl.download([url])
                        download_success = True
                except Exception as e:
                    last_error = e
                    print(f"Strategy 4 failed: {e}")
            
            # Strategy 5: Force specific extractor
            if not download_success:
                try:
                    opts5 = {
                        'format': 'best',
                        'outtmpl': str(temp_dir / '%(title)s [%(id)s].%(ext)s'),
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'extract_flat': False,
                        'force_generic_extractor': True,
                    }
                    with yt_dlp.YoutubeDL(opts5) as ydl:
                        ydl.download([url])
                        download_success = True
                except Exception as e:
                    last_error = e
                    print(f"Strategy 5 failed: {e}")
            
            # Strategy 6: Nuclear option - Ultra aggressive bypass
            if not download_success:
                try:
                    print("Trying nuclear option...")
                    opts6 = {
                        'format': 'worst',  # Try worst quality first
                        'outtmpl': str(temp_dir / '%(title)s [%(id)s].%(ext)s'),
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'no_check_certificate': True,
                        'prefer_insecure': True,
                        'http_chunk_size': 1,  # 1 byte chunks
                        'retries': 10,
                        'fragment_retries': 10,
                        'extractor_retries': 10,
                        'socket_timeout': 120,
                        'extractor_timeout': 120,
                        'sleep_interval': 5,
                        'max_sleep_interval': 20,
                        'http_headers': {
                            'User-Agent': 'curl/7.68.0',
                            'Accept': '*/*',
                            'Connection': 'keep-alive',
                        }
                    }
                    with yt_dlp.YoutubeDL(opts6) as ydl:
                        ydl.download([url])
                        download_success = True
                except Exception as e:
                    last_error = e
                    print(f"Strategy 6 failed: {e}")
            
            # Strategy 7: Last resort - Direct URL extraction
            if not download_success:
                try:
                    print("Trying direct URL extraction...")
                    # Try to extract direct video URL without downloading
                    opts7 = {
                        'quiet': True,
                        'no_warnings': True,
                        'no_check_certificate': True,
                        'prefer_insecure': True,
                        'http_headers': {
                            'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
                        }
                    }
                    with yt_dlp.YoutubeDL(opts7) as ydl:
                        info = ydl.extract_info(url, download=False)
                        if 'url' in info:
                            # Found direct URL, download it manually
                            import requests
                            response = requests.get(info['url'], stream=True, headers={
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                            })
                            if response.status_code == 200:
                                filename = f"video_{info.get('id', 'unknown')}.mp4"
                                file_path = temp_dir / filename
                                with open(file_path, 'wb') as f:
                                    for chunk in response.iter_content(chunk_size=8192):
                                        f.write(chunk)
                                download_success = True
                except Exception as e:
                    last_error = e
                    print(f"Strategy 7 failed: {e}")
            
            # Strategy 8: Final nuclear option - Try with different yt-dlp instance
            if not download_success and yt_dlp_alt is not None:
                try:
                    print("Trying alternative yt-dlp instance...")
                    opts8 = {
                        'format': 'best',
                        'outtmpl': str(temp_dir / '%(title)s [%(id)s].%(ext)s'),
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'no_check_certificate': True,
                        'prefer_insecure': True,
                        'http_headers': {
                            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        }
                    }
                    with yt_dlp_alt.YoutubeDL(opts8) as ydl:
                        ydl.download([url])
                        download_success = True
                except Exception as e:
                    last_error = e
                    print(f"Strategy 8 failed: {e}")
            
            # Strategy 9: YouTube-specific bypass with cookies
            if not download_success:
                try:
                    print("Trying YouTube-specific bypass...")
                    opts9 = {
                        'format': 'best',
                        'outtmpl': str(temp_dir / '%(title)s [%(id)s].%(ext)s'),
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'no_check_certificate': True,
                        'prefer_insecure': True,
                        'cookiesfrombrowser': ('chrome',),  # Use Chrome cookies
                        'http_headers': {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                            'Accept-Language': 'en-US,en;q=0.5',
                            'Accept-Encoding': 'gzip, deflate',
                            'Connection': 'keep-alive',
                            'Upgrade-Insecure-Requests': '1',
                        }
                    }
                    with yt_dlp.YoutubeDL(opts9) as ydl:
                        ydl.download([url])
                        download_success = True
                except Exception as e:
                    last_error = e
                    print(f"Strategy 9 failed: {e}")
            
            # Strategy 10: Ultra-minimal with age verification bypass
            if not download_success:
                try:
                    print("Trying age verification bypass...")
                    opts10 = {
                        'format': 'best',
                        'outtmpl': str(temp_dir / '%(title)s [%(id)s].%(ext)s'),
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'no_check_certificate': True,
                        'prefer_insecure': True,
                        'age_limit': 0,  # Bypass age restrictions
                        'http_headers': {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                            'Accept-Language': 'en-US,en;q=0.5',
                            'Accept-Encoding': 'gzip, deflate',
                            'Connection': 'keep-alive',
                        }
                    }
                    with yt_dlp.YoutubeDL(opts10) as ydl:
                        ydl.download([url])
                        download_success = True
                except Exception as e:
                    last_error = e
                    print(f"Strategy 10 failed: {e}")
            
            # Strategy 11: Force YouTube extractor with specific options
            if not download_success:
                try:
                    print("Trying forced YouTube extractor...")
                    opts11 = {
                        'format': 'best',
                        'outtmpl': str(temp_dir / '%(title)s [%(id)s].%(ext)s'),
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'no_check_certificate': True,
                        'prefer_insecure': True,
                        'extract_flat': False,
                        'force_generic_extractor': False,  # Force YouTube extractor
                        'http_headers': {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                            'Accept-Language': 'en-US,en;q=0.5',
                            'Accept-Encoding': 'gzip, deflate',
                            'Connection': 'keep-alive',
                        }
                    }
                    with yt_dlp.YoutubeDL(opts11) as ydl:
                        ydl.download([url])
                        download_success = True
                except Exception as e:
                    last_error = e
                    print(f"Strategy 11 failed: {e}")
            
            # Strategy 12: Last resort - Try with different format selection
            if not download_success:
                try:
                    print("Trying different format selection...")
                    opts12 = {
                        'format': 'worst[ext=mp4]/worst',  # Force worst MP4 or worst anything
                        'outtmpl': str(temp_dir / '%(title)s [%(id)s].%(ext)s'),
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'no_check_certificate': True,
                        'prefer_insecure': True,
                        'http_headers': {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                            'Accept-Language': 'en-US,en;q=0.5',
                            'Accept-Encoding': 'gzip, deflate',
                            'Connection': 'keep-alive',
                        }
                    }
                    with yt_dlp.YoutubeDL(opts12) as ydl:
                        ydl.download([url])
                        download_success = True
                except Exception as e:
                    last_error = e
                    print(f"Strategy 12 failed: {e}")
            
            # Strategy 13: YouTube Invidious API bypass
            if not download_success:
                try:
                    print("Trying Invidious API bypass...")
                    # Try using Invidious instances to bypass restrictions
                    invidious_instances = [
                        'https://invidious.projectsegfau.lt',
                        'https://invidious.slipfox.xyz',
                        'https://invidious.prvcy.eu',
                    ]
                    
                    for instance in invidious_instances:
                        try:
                            # Extract video ID from URL
                            import re
                            video_id_match = re.search(r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)', url)
                            if video_id_match:
                                video_id = video_id_match.group(1)
                                invidious_url = f"{instance}/api/v1/videos/{video_id}"
                                
                                import requests
                                response = requests.get(invidious_url, timeout=10)
                                if response.status_code == 200:
                                    data = response.json()
                                    if 'formatStreams' in data and data['formatStreams']:
                                        # Download from Invidious
                                        stream_url = data['formatStreams'][0]['url']
                                        video_response = requests.get(stream_url, stream=True)
                                        if video_response.status_code == 200:
                                            filename = f"{data.get('title', 'video')}_{video_id}.mp4"
                                            filename = re.sub(r'[^\w\-_\.]', '_', filename)
                                            file_path = temp_dir / filename
                                            with open(file_path, 'wb') as f:
                                                for chunk in video_response.iter_content(chunk_size=8192):
                                                    f.write(chunk)
                                            download_success = True
                                            break
                        except Exception as invidious_error:
                            print(f"Invidious instance {instance} failed: {invidious_error}")
                            continue
                            
                except Exception as e:
                    last_error = e
                    print(f"Strategy 13 failed: {e}")
            
            # Strategy 14: Final fallback - Try with completely different approach
            if not download_success:
                try:
                    print("Trying final fallback approach...")
                    opts14 = {
                        'format': 'best[height<=480]/best[height<=720]/best',  # Progressive quality fallback
                        'outtmpl': str(temp_dir / '%(title)s [%(id)s].%(ext)s'),
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'no_check_certificate': True,
                        'prefer_insecure': True,
                        'retries': 15,
                        'fragment_retries': 15,
                        'extractor_retries': 15,
                        'socket_timeout': 180,
                        'extractor_timeout': 180,
                        'sleep_interval': 3,
                        'max_sleep_interval': 15,
                        'http_headers': {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                            'Accept-Language': 'en-US,en;q=0.5',
                            'Accept-Encoding': 'gzip, deflate',
                            'Connection': 'keep-alive',
                            'Cache-Control': 'no-cache',
                            'Pragma': 'no-cache',
                        }
                    }
                    with yt_dlp.YoutubeDL(opts14) as ydl:
                        ydl.download([url])
                        download_success = True
                except Exception as e:
                    last_error = e
                    print(f"Strategy 14 failed: {e}")
            
            if not download_success:
                raise last_error or Exception("All download strategies failed")
                
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
                
                # Copy file to a permanent location before serving
                import tempfile as tf
                permanent_file = tf.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1])
                permanent_file.close()
                
                # Copy the downloaded file to permanent location
                shutil.copy2(file_path, permanent_file.name)
                
                # Clean up the temporary directory immediately
                try:
                    shutil.rmtree(temp_dir)
                    print(f"Cleaned up temp directory: {temp_dir}")
                except Exception as e:
                    print(f"Error cleaning up {temp_dir}: {e}")
                
                # Serve the permanent file
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
                        print(f"Cleaned up permanent file: {permanent_file.name}")
                    except Exception as e:
                        print(f"Error cleaning up {permanent_file.name}: {e}")
                
                return response
                
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



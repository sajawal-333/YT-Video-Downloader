# 🎬✨ Video Downloader Webapp

A beautiful and modern video downloader web application built with Flask and yt-dlp.

## Features

- Download videos from various platforms (YouTube, Vimeo, etc.)
- Multiple quality options (best, 720p, 480p, etc.)
- MP3 audio extraction with customizable bitrate
- Real-time download progress tracking
- Modern, responsive UI
- Cross-origin resource sharing (CORS) enabled

## Deployment to Render.com (Free 24/7 Hosting)

### Step 1: Prepare Your Repository
1. Push your code to a GitHub repository
2. Make sure all files are included:
   - `server.py`
   - `requirements.txt`
   - `Procfile`
   - `runtime.txt`
   - `static/` folder with `index.html`

### Step 2: Deploy on Render
1. Go to [render.com](https://render.com) and create a free account
2. Click "New +" and select "Web Service"
3. Connect your GitHub repository
4. Configure the service:
   - **Name**: `video-downloader` (or any name you prefer)
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn server:app`
   - **Plan**: Free (750 hours/month)

### Step 3: Environment Variables (Optional)
Add these environment variables in Render dashboard if needed:
- `PORT`: 10000 (Render sets this automatically)

### Step 4: Deploy
Click "Create Web Service" and wait for deployment to complete.

## Local Development

1. Create virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
python server.py
```

4. Open http://localhost:5000 in your browser

## API Endpoints

- `POST /api/download` - Start a download job
- `GET /api/status/<job_id>` - Get download status
- `GET /` - Main web interface

## Free Hosting Benefits

✅ **Always Online**: 24/7 uptime  
✅ **Free Tier**: 750 hours/month  
✅ **Automatic HTTPS**: SSL certificates included  
✅ **Global CDN**: Fast loading worldwide  
✅ **Easy Scaling**: Upgrade when needed  
✅ **No Credit Card Required**: Completely free to start  

Your webapp will be available at: `https://your-app-name.onrender.com`

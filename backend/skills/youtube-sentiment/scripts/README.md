# YouTube Sentiment Scripts

Structured skill for fetching YouTube videos and comments.

## Structure

| File | Purpose |
|------|---------|
| **video_scraper.py** | Fetch video list + metadata (title, author, view_count, etc.) from channels or single videos. Uses youtube-channel-scraper or requests fallback. |
| **comment_scraper.py** | Fetch comments for a video. Tries: 1) Playwright (network interception), 2) yt-dlp, 3) requests + InnerTube API. |
| **youtube_scraper.py** | Master orchestrator: calls video_scraper, then comment_scraper for each video, assembles final JSON. |

## Usage

```bash
# Video list only
python3 video_scraper.py --target "https://youtube.com/@channel" --max-videos 5 --output videos.json

# Comments for one video
python3 comment_scraper.py --video-url "https://youtube.com/watch?v=XXX" --output comments.json

# Full pipeline (videos + comments)
python3 youtube_scraper.py --target "https://youtube.com/@channel" --max-videos 5 --output output.json
python3 youtube_scraper.py --target "..." --no-fetch-comments  # Skip comment fetch (faster)
```

## Notes

- **Comments**: YouTube loads comments dynamically. Playwright intercepts API responses; yt-dlp may require a JS runtime for reliable extraction. If comments are empty, try installing `deno` or `node` for yt-dlp.
- **Video metadata**: Uses youtube-channel-scraper (Selenium) or requests + ytInitialData parsing.

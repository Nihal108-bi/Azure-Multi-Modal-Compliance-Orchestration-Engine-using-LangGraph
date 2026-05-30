import os
import re
import logging
import yt_dlp
from openai import OpenAI

logger = logging.getLogger("video-indexer")


class VideoIndexerService:
    def __init__(self):
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def download_youtube_video(self, url, output_path="temp_video.mp4"):
        """Downloads a YouTube video (prefer small format to stay under Whisper 25MB limit)."""
        logger.info(f"Downloading YouTube video: {url}")
        ydl_opts = {
            'format': 'best[filesize<24M]/worst[ext=mp4]/best',
            'outtmpl': output_path,
            'quiet': False,
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            logger.info("Download complete.")
            return output_path
        except Exception as e:
            raise Exception(f"YouTube Download Failed: {str(e)}")

    def get_youtube_transcript(self, url):
        """
        Fetches auto-generated subtitles from YouTube via yt-dlp.
        Free — no API key required.
        Returns cleaned transcript text, or None if unavailable.
        """
        logger.info("Attempting free subtitle extraction from YouTube...")
        subtitle_base = "temp_subtitle"
        ydl_opts = {
            'writeautomaticsub': True,
            'writesubtitles': True,
            'subtitleslangs': ['en', 'en-US'],
            'subtitlesformat': 'vtt',
            'skip_download': True,
            'quiet': True,
            'outtmpl': subtitle_base,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            for ext in ['.en.vtt', '.en-US.vtt']:
                subtitle_file = subtitle_base + ext
                if os.path.exists(subtitle_file):
                    with open(subtitle_file, 'r', encoding='utf-8') as f:
                        raw = f.read()
                    os.remove(subtitle_file)
                    # Strip VTT timestamps, tags, and blank lines
                    text = re.sub(r'\d{2}:\d{2}:\d{2}\.\d{3} --> [\d:.  \w]+\n', '', raw)
                    text = re.sub(r'WEBVTT.*?\n', '', text)
                    text = re.sub(r'<[^>]+>', '', text)
                    text = re.sub(r'\n+', ' ', text).strip()
                    if len(text) > 50:
                        logger.info("Subtitles extracted successfully (free).")
                        return text
        except Exception as e:
            logger.warning(f"Subtitle extraction failed: {e}")

        return None

    def transcribe_with_whisper(self, video_path):
        """
        Transcribes audio from a local video file using OpenAI Whisper API.
        Used as a fallback when YouTube subtitles are unavailable.
        File must be under 25MB.
        """
        logger.info("Transcribing with OpenAI Whisper API...")
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if file_size_mb > 24:
            raise Exception(
                f"Video file ({file_size_mb:.1f}MB) exceeds Whisper's 25MB limit. "
                "Use a shorter video or ensure YouTube subtitles are enabled."
            )
        with open(video_path, 'rb') as f:
            transcript = self.openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text"
            )
        logger.info("Whisper transcription complete.")
        return transcript

    def process_video(self, url):
        """
        Main method: tries free YouTube subtitle extraction first,
        falls back to OpenAI Whisper API if subtitles are unavailable.
        """
        # Step 1: Free subtitle extraction
        transcript = self.get_youtube_transcript(url)

        # Step 2: Paid Whisper fallback
        if not transcript:
            logger.info("No subtitles found. Falling back to Whisper transcription...")
            local_path = self.download_youtube_video(url, output_path="temp_audit_video.mp4")
            try:
                transcript = self.transcribe_with_whisper(local_path)
            finally:
                if os.path.exists(local_path):
                    os.remove(local_path)

        return {
            "transcript": transcript or "",
            "ocr_text": [],
            "video_metadata": {"platform": "youtube"}
        }

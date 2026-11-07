# spotDL web, with a current yt-dlp baked in.
#
# The upstream :latest image ships a pinned yt-dlp. YouTube changes often, and
# an out-of-date yt-dlp fails every media download with "HTTP Error 403:
# Forbidden". We update it at build time so each rebuild picks up the newest
# release. Rebuild whenever downloads start 403-ing again:
#     docker compose build --no-cache && docker compose up -d
FROM spotdl/spotify-downloader:latest

# uv manages the app's venv at /app/.venv; refresh just yt-dlp inside it.
RUN uv pip install --python /app/.venv/bin/python --upgrade yt-dlp

# Fix the web UI so pasting a playlist/album link downloads it, instead of
# failing with "Error downloading! Invalid URL" (upstream only handles single
# tracks in the web download handler). See patches/web_playlist_fix.py.
COPY patches/web_playlist_fix.py /tmp/web_playlist_fix.py
RUN python3 /tmp/web_playlist_fix.py

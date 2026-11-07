#!/usr/bin/env python3
"""Patch spotDL's web UI so downloads work from the browser, show progress, and
run through a single FIFO queue.

Fixes applied to spotdl/web/routes.py:

1. Downloads (`gen_download`). Upstream resolves the submitted URL with
   `Song.from_url`, which only accepts single **track** URLs, so playlists and
   albums fail with "Error downloading! Invalid URL". It also runs the download
   inside the SSE request coroutine, which is cancelled when the client is
   redirected to /downloads, and on the event loop, which freezes the UI.

   Replacement: each submission is put on a module-level FIFO queue, and a
   single background worker processes one batch at a time. The worker resolves
   the URL(s) via `get_simple_songs` (track / playlist / album / artist, and it
   accepts several URLs at once separated by spaces/commas) and downloads with a
   dedicated `Downloader` on its own event loop -- the reliable CLI path,
   decoupled from the request. The worker's `progress_handler` is the web
   client's, so the /downloads page shows live progress. One batch at a time
   keeps the host from being overloaded by many parallel submissions.

2. Text search (the non-URL branch) calls `get_search_results()` -- a blocking
   Spotify/YouTube lookup -- directly on the event loop, freezing the server.
   Moved to a worker thread via run_in_executor, with a `return` after the URL
   branch so a URL isn't also run through search.

Idempotent, run at image build time (see Dockerfile). Fails loudly if the
expected upstream source is missing, so an upstream change can't silently no-op.
"""

import sys
from pathlib import Path

ROUTES = Path("/app/spotdl/web/routes.py")

# --- 0. Make sure threading is imported ----------------------------------------
OLD_THREADING = "import asyncio\n"
NEW_THREADING = "import asyncio\nimport queue as _dl_queue_mod\nimport threading\n"

# --- 1. Import get_simple_songs + define the single-worker download queue -------
OLD_IMPORT = "from spotdl.utils.search import get_search_results"
NEW_IMPORT = '''from spotdl.utils.search import get_search_results, get_simple_songs

# Single-worker download queue: submissions are processed one batch at a time
# (FIFO). New submissions wait their turn instead of all running at once, which
# keeps the box responsive and avoids overloading the host.
_DOWNLOAD_QUEUE = _dl_queue_mod.Queue()
_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()


def _download_worker():
    from spotdl.download.downloader import Downloader

    while True:
        song_url, settings, progress_handler = _DOWNLOAD_QUEUE.get()
        try:
            # Accept several links at once (spaces, commas or newlines).
            urls = [u for u in song_url.replace(",", " ").split() if u]
            songs = get_simple_songs(
                urls,
                use_ytm_data=settings["ytm_data"],
                playlist_numbering=settings["playlist_numbering"],
                album_type=settings["album_type"],
                playlist_retain_track_cover=settings["playlist_retain_track_cover"],
            )
            app_state.logger.info(f"Downloading {len(songs)} song(s)")
            downloader = Downloader(settings=settings)
            # Report through the web client's progress handler so the /downloads
            # page (which polls it) shows live progress.
            downloader.progress_handler = progress_handler
            try:
                downloader.download_multiple_songs(songs)
            finally:
                try:
                    downloader.loop.close()
                except Exception:  # pylint: disable=broad-except
                    pass
            app_state.logger.info("Finished download batch.")
        except Exception as exc:  # pylint: disable=broad-except
            app_state.logger.error(f"Error downloading! {exc}")
        finally:
            _DOWNLOAD_QUEUE.task_done()'''

# --- 2. Replace the single-track-only download body with an enqueue ------------
OLD_BODY = '''    try:
        # Fetch song metadata
        song = Song.from_url(signals.song_url)
        app_state.logger.info(f"Downloading song: {song}")

        # Download Song
        _, path = await client.downloader.pool_download(song)
        yield SSE.patch_elements(f"""
            <button id="download-{signals.song_url}" class="btn btn-primary btn-square">
                    <iconify-icon icon="clarity:check-line" style="font-size: 24px"></iconify-icon>
                </button>
        """)

        if path is None:
            app_state.logger.error(f"Failure downloading {song.name}")

        # return str(path.absolute())

    except Exception as exception:
        app_state.logger.error(f"Error downloading! {exception}")'''

NEW_BODY = '''    try:
        global _WORKER_STARTED

        song_url = signals.song_url
        web_downloader = client.downloader
        settings = dict(web_downloader.settings)

        # Start the single background worker once, then queue this submission.
        # Batches download one at a time (FIFO); progress shows via the web
        # client's handler.
        with _WORKER_LOCK:
            if not _WORKER_STARTED:
                threading.Thread(
                    target=_download_worker,
                    name="spotdl-web-download-worker",
                    daemon=True,
                ).start()
                _WORKER_STARTED = True
        _DOWNLOAD_QUEUE.put((song_url, settings, web_downloader.progress_handler))
        app_state.logger.info(f"Queued download: {song_url}")

        yield SSE.patch_elements(f"""
            <button id="download-{signals.song_url}" class="btn btn-primary btn-square">
                    <iconify-icon icon="clarity:check-line" style="font-size: 24px"></iconify-icon>
                </button>
        """)

    except Exception as exception:
        app_state.logger.error(f"Error downloading! {exception}")'''

# --- 3. Run the text-search path off the event loop ---------------------------
OLD_SEARCH = '''        async for update in gen_download(signals):
            yield update

    songs = get_search_results(signals.search_term)
    yield SSE.patch_elements(
        templates.get_template("search-list.html.j2").render(
            songs=songs,
        )
    )'''

NEW_SEARCH = '''        async for update in gen_download(signals):
            yield update
        return

    # Text search (not a URL): run the blocking Spotify/YouTube lookup off the
    # event loop so a slow search can't freeze the whole web server.
    try:
        songs = await asyncio.get_running_loop().run_in_executor(
            None, get_search_results, signals.search_term
        )
    except Exception as exc:  # pylint: disable=broad-except
        app_state.logger.error(f"Search failed: {exc}")
        songs = []
    yield SSE.patch_elements(
        templates.get_template("search-list.html.j2").render(
            songs=songs,
        )
    )'''


def main() -> int:
    src = ROUTES.read_text()

    if OLD_BODY not in src and OLD_SEARCH not in src:
        print("web_playlist_fix: already applied, nothing to do.")
        return 0

    missing = [name for name, s in (("body", OLD_BODY), ("search", OLD_SEARCH))
               if s not in src]
    if missing:
        print(
            "web_playlist_fix: ERROR - expected source not found: "
            + ", ".join(missing)
            + ". Upstream spotdl/web/routes.py has changed; update this patch.",
            file=sys.stderr,
        )
        return 1

    if "import threading" not in src:
        src = src.replace(OLD_THREADING, NEW_THREADING, 1)
    if "get_simple_songs" not in src:
        src = src.replace(OLD_IMPORT, NEW_IMPORT, 1)
    src = src.replace(OLD_BODY, NEW_BODY, 1)
    src = src.replace(OLD_SEARCH, NEW_SEARCH, 1)
    ROUTES.write_text(src)
    print("web_playlist_fix: applied queued-download + progress + search fixes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

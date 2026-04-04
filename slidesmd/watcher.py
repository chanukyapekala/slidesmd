"""Watch a presentations folder and auto-regenerate agents.md on changes."""

import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from slidesmd.extractor import extract, PresentationMeta
from slidesmd.indexer import build_index


class PresentationHandler(FileSystemEventHandler):
    def __init__(self, watch_dir: Path) -> None:
        self.watch_dir = watch_dir

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and str(event.src_path).endswith(".pptx"):
            print(f"[slidesmd] New file detected: {event.src_path}")
            _refresh_index(self.watch_dir)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory and str(event.src_path).endswith(".pptx"):
            print(f"[slidesmd] File removed: {event.src_path}")
            _refresh_index(self.watch_dir)


def watch(watch_dir: Path) -> None:
    """Start watching the folder. Blocks until interrupted."""
    print(f"[slidesmd] Watching {watch_dir} for .pptx changes...")
    _refresh_index(watch_dir)  # initial index on startup

    handler = PresentationHandler(watch_dir)
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n[slidesmd] Stopped.")

    observer.join()


def _refresh_index(watch_dir: Path) -> None:
    pptx_files = list(watch_dir.rglob("*.pptx"))
    presentations: list[PresentationMeta] = []

    for f in pptx_files:
        try:
            presentations.append(extract(f))
        except Exception as e:
            print(f"[slidesmd] Warning: could not parse {f}: {e}")

    index_path = build_index(presentations, watch_dir)
    print(f"[slidesmd] Index updated → {index_path} ({len(presentations)} presentations)")

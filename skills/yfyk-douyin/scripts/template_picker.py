#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from PIL import Image, UnidentifiedImageError

from card_templates import TEMPLATES, render_framed_page
from docx_page_renderer import PageRenderError, render_docx_pages
from template_assignment import BALANCED_RANDOM

SKILL_DIR = Path(__file__).resolve().parent.parent
HTML_PATH = SKILL_DIR / "assets/template-picker/index.html"


def _atomic_json(path: Path, payload: dict[str, Any]):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    published = False
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        published = True
    finally:
        if not published:
            temporary.unlink(missing_ok=True)


def _validate_preview(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise PageRenderError(f"preview render did not produce a regular image: {path}")
    try:
        with Image.open(path) as image:
            image.verify()
            if image.format != "PNG" or image.size != (1080, 1440):
                raise PageRenderError(f"preview image is invalid: {path}")
    except PageRenderError:
        raise
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise PageRenderError(f"preview image is invalid: {path}") from exc


def generate_previews(source_docx: Path, session_dir: Path) -> dict[str, Path]:
    """Build every real-page preview privately, then publish the complete set once."""
    source_docx = Path(source_docx)
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    preview_dir = session_dir / "previews"
    if os.path.lexists(preview_dir):
        raise PageRenderError(f"preview directory already exists: {preview_dir}")

    staging_dir = Path(tempfile.mkdtemp(prefix=".preview-staging-", dir=session_dir))
    staged_previews = staging_dir / "previews"
    try:
        source_pages = render_docx_pages(source_docx, staging_dir / "source-pages")
        if not source_pages:
            raise PageRenderError("source DOCX rendered no pages")

        first_page = Path(source_pages[0])
        if not first_page.is_file():
            raise PageRenderError(f"first rendered source page does not exist: {first_page}")

        staged_previews.mkdir()
        for template_id in sorted(TEMPLATES):
            target = staged_previews / f"{template_id}.png"
            try:
                render_framed_page(first_page, target, template_id, 1, len(source_pages))
            except PageRenderError:
                raise
            except Exception as exc:
                raise PageRenderError(
                    f"failed to render preview for template {template_id}: {exc}"
                ) from exc
            _validate_preview(target)
        expected_names = sorted(f"{template_id}.png" for template_id in TEMPLATES)
        if sorted(path.name for path in staged_previews.iterdir()) != expected_names:
            raise PageRenderError("preview set is incomplete")
        if os.path.lexists(preview_dir):
            raise PageRenderError(f"preview directory already exists: {preview_dir}")
        os.rename(staged_previews, preview_dir)
    except PageRenderError:
        raise
    except Exception as exc:
        raise PageRenderError(f"failed to generate template previews: {exc}") from exc
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    return {
        template_id: preview_dir / f"{template_id}.png"
        for template_id in sorted(TEMPLATES)
    }


def create_picker_server(source_docx: Path, session_dir: Path, result_path: Path) -> ThreadingHTTPServer:
    session_dir = Path(session_dir)
    result_path = Path(result_path)
    result_path.unlink(missing_ok=True)
    generate_previews(source_docx, session_dir)
    allowed = set(TEMPLATES) | {BALANCED_RANDOM}
    preview_dir = session_dir / "previews"
    resolved_preview_dir = preview_dir.resolve()
    selection_lock = threading.Lock()
    selection_made = threading.Event()

    class PickerHandler(BaseHTTPRequestHandler):
        def _send(self, status: int, data: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            if path == "/":
                self._send(200, HTML_PATH.read_bytes(), "text/html; charset=utf-8")
                return
            preview_paths = {
                f"/previews/{template_id}.png": preview_dir / f"{template_id}.png"
                for template_id in TEMPLATES
            }
            target = preview_paths.get(path)
            if target is not None:
                try:
                    resolved_target = target.resolve(strict=True)
                except OSError:
                    resolved_target = None
                if (
                    resolved_target is not None
                    and not preview_dir.is_symlink()
                    and not target.is_symlink()
                    and target.is_file()
                    and resolved_target.parent == resolved_preview_dir
                ):
                    self._send(200, target.read_bytes(), "image/png")
                    return
            self._send(404, b'{"error":"not found"}', "application/json")

        def do_POST(self):
            if urlparse(self.path).path != "/select":
                self._send(404, b'{"error":"not found"}', "application/json")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                choice = payload.get("choice")
            except Exception:
                choice = None
            if choice not in allowed:
                data = json.dumps({"error": "invalid choice"}, ensure_ascii=False).encode()
                self._send(400, data, "application/json; charset=utf-8")
                return
            display_name = "均衡随机" if choice == BALANCED_RANDOM else TEMPLATES[choice].display_name
            result = {"status": "selected", "choice": choice, "display_name": display_name}
            with selection_lock:
                if selection_made.is_set():
                    data = json.dumps({"error": "selection already made"}, ensure_ascii=False).encode()
                    self._send(409, data, "application/json; charset=utf-8")
                    return
                try:
                    _atomic_json(result_path, result)
                except OSError as exc:
                    data = json.dumps({"error": f"failed to save selection: {exc}"}, ensure_ascii=False).encode()
                    self._send(500, data, "application/json; charset=utf-8")
                    return
                selection_made.set()
            self._send(200, json.dumps(result, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def log_message(self, format, *args):
            return

    return ThreadingHTTPServer(("127.0.0.1", 0), PickerHandler)


def run_picker(
    source_docx: Path,
    work_dir: Path,
    result_path: Path,
    timeout_seconds: int,
    open_browser: bool = False,
) -> dict[str, Any]:
    server = create_picker_server(source_docx, work_dir, result_path)
    thread = None
    started = False
    try:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started = True
        url = f"http://127.0.0.1:{server.server_port}/"
        print(json.dumps({"url": url, "result": str(result_path)}, ensure_ascii=False), flush=True)
        if open_browser:
            webbrowser.open(url)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if result_path.exists():
                return json.loads(result_path.read_text(encoding="utf-8"))
            time.sleep(0.1)
        raise TimeoutError("template selection timed out")
    finally:
        try:
            if started:
                server.shutdown()
        finally:
            try:
                server.server_close()
            finally:
                if started and thread is not None:
                    thread.join(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Show real previews and select a Douyin card template.")
    parser.add_argument("--source", required=True, type=Path, help="Source DOCX used for the real-page previews.")
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the legacy webpage picker. Use only after explicit user consent.",
    )
    args = parser.parse_args()
    try:
        selection = run_picker(args.source, args.work_dir, args.result, args.timeout_seconds, args.open_browser)
    except TimeoutError as exc:
        print(json.dumps({"status": "timeout", "error": str(exc)}, ensure_ascii=False))
        return 2
    except (PageRenderError, OSError, RuntimeError, webbrowser.Error) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        )
        return 3
    print(json.dumps(selection, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

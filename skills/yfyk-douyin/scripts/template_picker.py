#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from card_templates import TEMPLATES, render_cards
from template_assignment import BALANCED_RANDOM

SKILL_DIR = Path(__file__).resolve().parent.parent
HTML_PATH = SKILL_DIR / "assets/template-picker/index.html"

PREVIEW_BLOCKS = [
    {"type": "paragraph", "style": "Heading 1", "text": "产业工人建设决定交付基本盘"},
    {"type": "paragraph", "style": "Normal", "text": "家装质量最终落在一线工人身上。标准化培训，是稳定交付的基础。"},
    {"type": "paragraph", "style": "Heading 2", "text": "实训基地让标准可训练、可考核"},
    {"type": "paragraph", "style": "Normal", "text": "围绕关键工种建立训练、考核与验收路径。"},
]


def _atomic_json(path: Path, payload: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def generate_previews(session_dir: Path) -> dict[str, Path]:
    preview_dir = session_dir / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    for template_id in sorted(TEMPLATES):
        cards = render_cards(PREVIEW_BLOCKS, session_dir / "render" / template_id, template_id)
        target = preview_dir / f"{template_id}.png"
        shutil.copy2(cards[0], target)
        outputs[template_id] = target
    return outputs


def create_picker_server(session_dir: Path, result_path: Path) -> ThreadingHTTPServer:
    result_path.unlink(missing_ok=True)
    generate_previews(session_dir)
    allowed = set(TEMPLATES) | {BALANCED_RANDOM}

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
            if path.startswith("/previews/") and path.endswith(".png"):
                name = Path(path).name
                target = session_dir / "previews" / name
                if target.is_file() and target.parent == session_dir / "previews":
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
            _atomic_json(result_path, result)
            self._send(200, json.dumps(result, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def log_message(self, format, *args):
            return

    return ThreadingHTTPServer(("127.0.0.1", 0), PickerHandler)


def run_picker(work_dir: Path, result_path: Path, timeout_seconds: int, open_browser: bool = False) -> dict[str, Any]:
    server = create_picker_server(work_dir, result_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    print(json.dumps({"url": url, "result": str(result_path)}, ensure_ascii=False), flush=True)
    if open_browser:
        webbrowser.open(url)
    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            if result_path.exists():
                return json.loads(result_path.read_text(encoding="utf-8"))
            time.sleep(0.1)
        raise TimeoutError("template selection timed out")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Show real previews and select a Douyin card template.")
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
        selection = run_picker(args.work_dir, args.result, args.timeout_seconds, args.open_browser)
    except TimeoutError as exc:
        print(json.dumps({"status": "timeout", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(selection, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

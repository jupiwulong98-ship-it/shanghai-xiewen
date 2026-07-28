import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from template_picker import create_picker_server, generate_previews  # noqa: E402


class TemplatePickerTests(unittest.TestCase):
    def test_new_picker_session_clears_stale_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = root / "selection.json"
            result.write_text('{"choice":"classic-gray"}', encoding="utf-8")
            server = create_picker_server(root, result)
            try:
                self.assertFalse(result.exists())
            finally:
                server.server_close()

    def test_preview_generation_uses_all_production_templates(self):
        with tempfile.TemporaryDirectory() as temp:
            previews = generate_previews(Path(temp))
            self.assertEqual(
                set(previews),
                {"classic-gray", "editorial-warm", "premium-dark", "minimal-white"},
            )
            for path in previews.values():
                with Image.open(path) as image:
                    self.assertEqual(image.size, (1080, 1440))

    def test_server_serves_picker_and_accepts_valid_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = root / "selection.json"
            server = create_picker_server(root, result)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                html = urllib.request.urlopen(base, timeout=5).read().decode()
                for choice in (
                    "classic-gray",
                    "editorial-warm",
                    "premium-dark",
                    "minimal-white",
                    "balanced-random",
                ):
                    self.assertIn(choice, html)
                request = urllib.request.Request(
                    base + "/select",
                    data=json.dumps({"choice": "premium-dark"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                response = json.loads(urllib.request.urlopen(request, timeout=5).read())
                self.assertEqual(response["choice"], "premium-dark")
                self.assertEqual(json.loads(result.read_text())["choice"], "premium-dark")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_server_rejects_unknown_choice_without_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = root / "selection.json"
            server = create_picker_server(root, result)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/select",
                    data=b'{"choice":"wrong"}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=5)
                try:
                    self.assertEqual(caught.exception.code, 400)
                finally:
                    caught.exception.close()
                self.assertFalse(result.exists())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()

import json
import inspect
import io
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from card_templates import render_framed_page  # noqa: E402
from docx_page_renderer import PageRenderError  # noqa: E402
from template_picker import create_picker_server, generate_previews, main, run_picker  # noqa: E402


class TemplatePickerTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "source.docx"
        source.touch()
        return source

    def _page(self, root: Path, name: str = "page-001.png") -> Path:
        page = root / name
        Image.new("RGB", (640, 960), "#4d7ea8").save(page)
        return page

    def _preview_fixtures(self, root: Path) -> dict[str, Path]:
        preview_dir = root / "previews"
        preview_dir.mkdir(parents=True)
        previews = {}
        for template_id, color in {
            "classic-gray": "#6b7280",
            "editorial-warm": "#b45309",
            "premium-dark": "#111827",
            "minimal-white": "#f8fafc",
        }.items():
            preview = preview_dir / f"{template_id}.png"
            Image.new("RGB", (1080, 1440), color).save(preview)
            previews[template_id] = preview
        return previews

    def _render_source_pages(self, _source: Path, target_dir: Path) -> list[Path]:
        target_dir.mkdir(parents=True)
        return [
            self._page(target_dir, "page-001.png"),
            self._page(target_dir, "page-002.png"),
        ]

    def test_picker_does_not_open_browser_by_default(self):
        default = inspect.signature(run_picker).parameters["open_browser"].default
        self.assertIs(default, False)

    def test_picker_requires_source_docx(self):
        self.assertIn("source_docx", inspect.signature(create_picker_server).parameters)
        self.assertIn("source_docx", inspect.signature(run_picker).parameters)

    def test_skill_requires_chat_native_selection_before_web_fallback(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("ask_followup_questions", skill)
        self.assertIn("variant: visual", skill)
        self.assertIn(
            "Never open the webpage picker without explicit user consent",
            skill,
        )

    def test_frame_only_card_workflow_is_documented(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        content_rules = (ROOT / "references" / "content_rules.md").read_text(
            encoding="utf-8"
        )
        job_schema = (ROOT / "references" / "job_schema.md").read_text(
            encoding="utf-8"
        )
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

        for phrase in (
            "one source DOCX page becomes one card",
            "never reflow source blocks into production cards",
            "frame decorations must stay outside SAFE_BOX",
            "preview the actual first source page",
        ):
            self.assertIn(phrase, skill)
        self.assertIn("generate_previews(source_docx, session_dir)", skill)
        self.assertIn("--source", skill)
        self.assertIn("source page rendering", skill)
        self.assertIn("pure outer frame", skill)
        self.assertIn("one source DOCX page becomes one card", content_rules)
        self.assertIn("never reflow source blocks into production cards", content_rules)
        self.assertIn("do not crop, stretch, or duplicate", content_rules)
        self.assertIn("card_template controls only the outer frame", job_schema)
        self.assertIn("four registered IDs", job_schema)
        self.assertIn("balanced-random seed", job_schema)
        self.assertIn("frame-only", metadata)

    def test_new_picker_session_clears_stale_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            result = root / "selection.json"
            result.write_text('{"choice":"classic-gray"}', encoding="utf-8")
            with patch("template_picker.generate_previews", return_value={}):
                server = create_picker_server(source, root, result)
                try:
                    self.assertFalse(result.exists())
                finally:
                    server.server_close()

    def test_preview_generation_frames_the_same_real_first_page_for_all_templates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            with (
                patch(
                    "template_picker.render_docx_pages",
                    side_effect=self._render_source_pages,
                ) as render_pages,
                patch(
                    "template_picker.render_framed_page",
                    wraps=render_framed_page,
                ) as frame_page,
            ):
                previews = generate_previews(source, root / "session")

            render_pages.assert_called_once()
            render_source, render_target = render_pages.call_args.args
            self.assertEqual(render_source, source)
            self.assertEqual(render_target.name, "source-pages")
            self.assertEqual(render_target.parent.parent, root / "session")
            self.assertEqual(
                set(previews),
                {"classic-gray", "editorial-warm", "premium-dark", "minimal-white"},
            )
            self.assertEqual(frame_page.call_count, 4)
            for call in frame_page.call_args_list:
                self.assertEqual(call.args[0], render_target / "page-001.png")
                self.assertEqual(call.args[3:], (1, 2))
            for path in previews.values():
                with Image.open(path) as image:
                    self.assertEqual(image.size, (1080, 1440))
            self.assertFalse((root / "session" / "source-pages").exists())
            self.assertEqual(list((root / "session").glob(".preview-staging-*")), [])

    def test_preview_generation_is_all_or_nothing_and_can_retry_after_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            session = root / "session"
            failed = False

            def fail_one_frame(source_page, target, template_id, page_no, total_pages):
                nonlocal failed
                if not failed and template_id == "editorial-warm":
                    failed = True
                    raise OSError("injected frame failure")
                return render_framed_page(source_page, target, template_id, page_no, total_pages)

            with (
                patch("template_picker.render_docx_pages", side_effect=self._render_source_pages),
                patch("template_picker.render_framed_page", side_effect=fail_one_frame),
            ):
                with self.assertRaisesRegex(PageRenderError, "injected frame failure"):
                    generate_previews(source, session)

            self.assertFalse((session / "previews").exists())
            self.assertFalse((session / "source-pages").exists())
            self.assertEqual(list(session.glob(".preview-staging-*")), [])

            with patch("template_picker.render_docx_pages", side_effect=self._render_source_pages):
                previews = generate_previews(source, session)
            self.assertEqual(len(previews), 4)
            self.assertTrue(all(path.is_file() for path in previews.values()))

    def test_preview_generation_refuses_an_existing_preview_set_without_mixing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            session = root / "session"
            existing = self._preview_fixtures(session)
            original = {name: path.read_bytes() for name, path in existing.items()}
            with patch("template_picker.render_docx_pages") as render_pages:
                with self.assertRaisesRegex(PageRenderError, "already exists"):
                    generate_previews(source, session)
            render_pages.assert_not_called()
            self.assertEqual(
                {name: path.read_bytes() for name, path in existing.items()},
                original,
            )

    def test_preview_generation_rejects_empty_or_missing_pages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            with patch("template_picker.render_docx_pages", return_value=[]):
                with self.assertRaisesRegex(PageRenderError, "no pages"):
                    generate_previews(source, root / "empty")
            with patch("template_picker.render_docx_pages", return_value=[root / "missing.png"]):
                with self.assertRaisesRegex(PageRenderError, "does not exist"):
                    generate_previews(source, root / "missing")

    def test_preview_generation_propagates_page_render_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            expected = PageRenderError("conversion failed")
            with patch("template_picker.render_docx_pages", side_effect=expected):
                with self.assertRaises(PageRenderError) as caught:
                    generate_previews(source, root / "failed")
            self.assertIs(caught.exception, expected)

    def test_preview_generation_wraps_frame_failures_as_page_render_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            first_page = self._page(root)
            with (
                patch("template_picker.render_docx_pages", return_value=[first_page]),
                patch("template_picker.render_framed_page", side_effect=OSError("disk failure")),
            ):
                with self.assertRaisesRegex(PageRenderError, "failed to render preview"):
                    generate_previews(source, root / "failed-frame")

    def test_server_serves_picker_and_accepts_valid_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            result = root / "selection.json"
            previews = self._preview_fixtures(root)
            with patch("template_picker.generate_previews", return_value=previews):
                server = create_picker_server(source, root, result)
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
                for template_id in previews:
                    with urllib.request.urlopen(base + f"/previews/{template_id}.png", timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.headers.get_content_type(), "image/png")
                        with Image.open(io.BytesIO(response.read())) as image:
                            image.verify()
                            self.assertEqual(image.size, (1080, 1440))
                with self.assertRaises(urllib.error.HTTPError) as missing_preview:
                    urllib.request.urlopen(base + "/previews/not-a-template.png", timeout=5)
                try:
                    self.assertEqual(missing_preview.exception.code, 404)
                finally:
                    missing_preview.exception.close()
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
            source = self._source(root)
            result = root / "selection.json"
            with patch("template_picker.generate_previews", return_value={}):
                server = create_picker_server(source, root, result)
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

    def test_server_only_serves_registered_regular_preview_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            result = root / "selection.json"
            previews = self._preview_fixtures(root)
            leak = root / "previews" / "leak.png"
            Image.new("RGB", (1080, 1440), "red").save(leak)
            outside = self._page(root, "outside.png")
            symlink_preview = previews["classic-gray"]
            symlink_preview.unlink()
            symlink_preview.symlink_to(outside)
            with patch("template_picker.generate_previews", return_value=previews):
                server = create_picker_server(source, root, result)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                for path in (
                    "/previews/leak.png",
                    "/previews/classic-gray.png",
                    "/previews/%2e%2e/outside.png",
                ):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(base + path, timeout=5)
                    try:
                        self.assertEqual(caught.exception.code, 404)
                    finally:
                        caught.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_server_rejects_a_symlinked_preview_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            result = root / "selection.json"
            external_session = root / "external"
            previews = self._preview_fixtures(external_session)
            (root / "previews").symlink_to(external_session / "previews", target_is_directory=True)
            with patch("template_picker.generate_previews", return_value=previews):
                server = create_picker_server(source, root, result)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{server.server_port}/previews/minimal-white.png",
                        timeout=5,
                    )
                try:
                    self.assertEqual(caught.exception.code, 404)
                finally:
                    caught.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_server_commits_only_the_first_concurrent_valid_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            result = root / "selection.json"
            previews = self._preview_fixtures(root)
            with patch("template_picker.generate_previews", return_value=previews):
                server = create_picker_server(source, root, result)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            choices = [
                "classic-gray",
                "editorial-warm",
                "premium-dark",
                "minimal-white",
                "balanced-random",
            ] * 3
            barrier = threading.Barrier(len(choices))

            def submit(choice: str) -> tuple[int, dict]:
                barrier.wait(timeout=5)
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/select",
                    data=json.dumps({"choice": choice}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        return response.status, json.loads(response.read())
                except urllib.error.HTTPError as exc:
                    try:
                        return exc.code, json.loads(exc.read())
                    finally:
                        exc.close()

            try:
                with ThreadPoolExecutor(max_workers=len(choices)) as executor:
                    responses = list(executor.map(submit, choices))
                successes = [payload for status, payload in responses if status == 200]
                conflicts = [payload for status, payload in responses if status == 409]
                self.assertEqual(len(successes), 1)
                self.assertEqual(len(conflicts), len(choices) - 1)
                self.assertTrue(all(payload["error"] == "selection already made" for payload in conflicts))
                self.assertEqual(json.loads(result.read_text())["choice"], successes[0]["choice"])
                self.assertEqual(list(root.glob("selection.json.*.tmp")), [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_run_picker_closes_server_if_thread_start_fails(self):
        server = Mock(server_port=12345)
        thread = Mock()
        thread.start.side_effect = RuntimeError("thread failed")
        with (
            patch("template_picker.create_picker_server", return_value=server),
            patch("template_picker.threading.Thread", return_value=thread),
        ):
            with self.assertRaisesRegex(RuntimeError, "thread failed"):
                run_picker(Path("source.docx"), Path("work"), Path("result.json"), 1)
        server.shutdown.assert_not_called()
        server.server_close.assert_called_once_with()
        thread.join.assert_not_called()

    def test_run_picker_cleans_started_server_when_browser_open_fails(self):
        server = Mock(server_port=12345)
        thread = Mock()
        with (
            patch("template_picker.create_picker_server", return_value=server),
            patch("template_picker.threading.Thread", return_value=thread),
            patch("template_picker.webbrowser.open", side_effect=OSError("browser failed")),
            patch("builtins.print"),
        ):
            with self.assertRaisesRegex(OSError, "browser failed"):
                run_picker(
                    Path("source.docx"),
                    Path("work"),
                    Path("result.json"),
                    1,
                    open_browser=True,
                )
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        thread.join.assert_called_once_with(timeout=5)

    def test_run_picker_cleans_started_server_when_url_print_fails(self):
        server = Mock(server_port=12345)
        thread = Mock()
        with (
            patch("template_picker.create_picker_server", return_value=server),
            patch("template_picker.threading.Thread", return_value=thread),
            patch("builtins.print", side_effect=OSError("stdout failed")),
        ):
            with self.assertRaisesRegex(OSError, "stdout failed"):
                run_picker(Path("source.docx"), Path("work"), Path("result.json"), 1)
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        thread.join.assert_called_once_with(timeout=5)

    def test_cli_requires_source_and_passes_it_to_picker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            result = root / "selection.json"
            with (
                patch("template_picker.run_picker", return_value={"choice": "minimal-white"}) as picker,
                patch.object(
                    sys,
                    "argv",
                    [
                        "template_picker.py",
                        "--source",
                        str(source),
                        "--work-dir",
                        str(root / "session"),
                        "--result",
                        str(result),
                    ],
                ),
            ):
                self.assertEqual(main(), 0)
            picker.assert_called_once_with(source, root / "session", result, 1800, False)

            with patch.object(
                sys,
                "argv",
                ["template_picker.py", "--work-dir", str(root / "session"), "--result", str(result)],
            ):
                with self.assertRaises(SystemExit) as missing_source:
                    main()
            self.assertEqual(missing_source.exception.code, 2)

    def test_cli_reports_expected_picker_failures_as_structured_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            result = root / "selection.json"
            arguments = [
                "template_picker.py",
                "--source",
                str(source),
                "--work-dir",
                str(root / "session"),
                "--result",
                str(result),
            ]
            for failure in (
                PageRenderError("render failed"),
                OSError("server failed"),
                RuntimeError("thread failed"),
            ):
                output = io.StringIO()
                with (
                    patch("template_picker.run_picker", side_effect=failure),
                    patch.object(sys, "argv", arguments),
                    redirect_stdout(output),
                ):
                    self.assertNotEqual(main(), 0)
                payload = json.loads(output.getvalue())
                self.assertEqual(payload["status"], "error")
                self.assertEqual(payload["error"], str(failure))
                self.assertEqual(payload["error_type"], type(failure).__name__)


if __name__ == "__main__":
    unittest.main()

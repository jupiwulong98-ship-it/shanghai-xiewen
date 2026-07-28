import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from docx_page_renderer import PageRenderError, render_docx_pages  # noqa: E402


class _FakePixmap:
    def __init__(self, color: str):
        self.color = color

    def save(self, path: str):
        Image.new("RGB", (32, 48), self.color).save(path, format="PNG")


class _FakePage:
    def __init__(self, color: str):
        self.color = color

    def get_pixmap(self, *, matrix, alpha):
        self.matrix = matrix
        self.alpha = alpha
        return _FakePixmap(self.color)


class _FakeDocument:
    def __init__(self, colors: list[str]):
        self.pages = [_FakePage(color) for color in colors]
        self.page_count = len(self.pages)

    def load_page(self, index: int):
        return self.pages[index]

    def close(self):
        pass


class _FakeFitz:
    class Matrix:
        def __init__(self, x, y):
            self.x = x
            self.y = y

    def __init__(self, colors: list[str]):
        self.colors = colors

    def open(self, path):
        return _FakeDocument(self.colors)


class DocxPageRendererTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "source.docx"
        source.write_bytes(b"not-a-real-docx")
        return source

    def _successful_conversion(self, args, **kwargs):
        output_dir = Path(args[args.index("--outdir") + 1])
        source = Path(args[-1])
        (output_dir / f"{source.stem}.pdf").write_bytes(b"%PDF-fake")
        return subprocess.CompletedProcess(args, 0, "", "")

    def test_renders_two_pages_in_order_and_as_decodable_pngs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "pages"
            with (
                patch("docx_page_renderer._load_fitz", return_value=_FakeFitz(["red", "blue"])),
                patch("docx_page_renderer.subprocess.run", side_effect=self._successful_conversion),
                patch("docx_page_renderer._find_soffice", return_value="/fake/soffice"),
            ):
                pages = render_docx_pages(self._source(root), target, dpi=160)

            self.assertEqual(pages, [target / "page-001.png", target / "page-002.png"])
            self.assertEqual(sorted(path.name for path in target.glob("page-*.png")), ["page-001.png", "page-002.png"])
            for page in pages:
                with Image.open(page) as image:
                    image.verify()

    def test_missing_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing.docx"
            with self.assertRaisesRegex(PageRenderError, "does not exist"):
                render_docx_pages(missing, Path(temp) / "pages")

    def test_conversion_failure_and_zero_page_pdf_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._source(root)
            with (
                patch("docx_page_renderer._find_soffice", return_value="/fake/soffice"),
                patch(
                    "docx_page_renderer.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 1, "", "converter failed"),
                ),
            ):
                with self.assertRaisesRegex(PageRenderError, "conversion failed"):
                    render_docx_pages(source, root / "conversion-failure")

            with (
                patch("docx_page_renderer._find_soffice", return_value="/fake/soffice"),
                patch("docx_page_renderer.subprocess.run", side_effect=self._successful_conversion),
                patch("docx_page_renderer._load_fitz", return_value=_FakeFitz([])),
            ):
                with self.assertRaisesRegex(PageRenderError, "no pages"):
                    render_docx_pages(source, root / "zero-pages")


@unittest.skipUnless(
    __import__("importlib").util.find_spec("fitz") and __import__("shutil").which("soffice"),
    "PyMuPDF and soffice are required for the real DOCX smoke test",
)
class DocxPageRendererSmokeTests(unittest.TestCase):
    def test_real_minimal_docx_renders_a_png(self):
        from docx import Document

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "smoke.docx"
            document = Document()
            document.add_paragraph("DOCX renderer smoke test")
            document.save(source)
            pages = render_docx_pages(source, root / "pages", dpi=72)
            self.assertEqual([path.name for path in pages], ["page-001.png"])
            with Image.open(pages[0]) as image:
                image.verify()


if __name__ == "__main__":
    unittest.main()

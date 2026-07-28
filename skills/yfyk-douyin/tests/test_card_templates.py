import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import card_templates  # noqa: E402
from card_templates import TEMPLATES, render_cards  # noqa: E402


class CardTemplateTests(unittest.TestCase):
    EXPECTED_IDS = {
        "classic-gray",
        "editorial-warm",
        "premium-dark",
        "minimal-white",
    }

    def test_registry_has_exact_template_ids(self):
        self.assertEqual(set(TEMPLATES), self.EXPECTED_IDS)

    def test_every_template_renders_1080_by_1440_cards(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_image = root / "source.png"
            Image.new("RGB", (360, 240), "#5B7FA3").save(source_image)
            blocks = [
                {"type": "paragraph", "style": "Heading 1", "text": "产业工人建设决定交付基本盘"},
                {"type": "paragraph", "style": "Normal", "text": "完整正文内容" * 80},
                {"type": "paragraph", "style": "List Number", "text": "第一项说明"},
                {"type": "table", "rows": [["项目", "说明"], ["培训", "标准化实训"]]},
                {"type": "image", "path": str(source_image)},
            ]
            first_pixels = {}
            for template_id in sorted(self.EXPECTED_IDS):
                cards = render_cards(blocks, root / template_id, template_id)
                self.assertTrue(cards)
                for card in cards:
                    with Image.open(card) as image:
                        self.assertEqual(image.size, (1080, 1440))
                with Image.open(cards[0]) as image:
                    first_pixels[template_id] = image.getpixel((5, 5))
            self.assertGreaterEqual(len(set(first_pixels.values())), 3)

    def test_unknown_template_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "unknown card template"):
                render_cards([], Path(temp), "not-a-template")

    def test_contain_size_preserves_aspect_ratio_and_rejects_invalid_dimensions(self):
        contain_size = self._frame_api()["contain_size"]
        self.assertEqual(contain_size(1600, 800, 900, 1200), (900, 450))
        self.assertEqual(contain_size(800, 1600, 900, 1200), (600, 1200))
        for dimensions in ((0, 10, 1, 1), (10, 0, 1, 1), (1, 1, 0, 1), (1, 1, 1, 0)):
            with self.assertRaises(ValueError):
                contain_size(*dimensions)

    def test_framed_page_contains_sources_without_cropping_or_distortion(self):
        api = self._frame_api()
        width, height, safe_box = api["WIDTH"], api["HEIGHT"], api["SAFE_BOX"]
        render_framed_page = api["render_framed_page"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for source_size in ((360, 720), (720, 360), (80, 720)):
                source = self._marked_source(root / f"source-{source_size[0]}x{source_size[1]}.png", source_size)
                target = root / f"framed-{source_size[0]}x{source_size[1]}.png"
                output = render_framed_page(source, target, "classic-gray", 1, 1)
                self.assertEqual(output, target)
                with Image.open(output).convert("RGB") as image:
                    self.assertEqual(image.size, (width, height))
                    bbox = self._source_bbox(image, safe_box)
                    self.assertGreaterEqual(bbox[0], safe_box[0])
                    self.assertGreaterEqual(bbox[1], safe_box[1])
                    self.assertLessEqual(bbox[2], safe_box[2])
                    self.assertLessEqual(bbox[3], safe_box[3])
                    actual_width, actual_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    self.assertLessEqual(abs(actual_width - actual_height * source_size[0] / source_size[1]), 1)
                    self.assertTrue(self._has_color_near(image, (255, 0, 0), (bbox[0], bbox[1])))
                    self.assertTrue(self._has_color_near(image, (0, 255, 0), (bbox[2] - 1, bbox[1])))
                    self.assertTrue(self._has_color_near(image, (0, 0, 255), (bbox[0], bbox[3] - 1)))
                    self.assertTrue(self._has_color_near(image, (255, 255, 0), (bbox[2] - 1, bbox[3] - 1)))

    def test_all_frames_share_an_identical_safe_box_but_differ_outside_it(self):
        api = self._frame_api()
        safe_box, render_framed_page = api["SAFE_BOX"], api["render_framed_page"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._marked_source(root / "source.png", (360, 720))
            rendered = {}
            for template_id in sorted(self.EXPECTED_IDS):
                output = render_framed_page(source, root / f"{template_id}.png", template_id, 2, 4)
                with Image.open(output).convert("RGB") as image:
                    rendered[template_id] = image.copy()
            safe_regions = [image.crop(safe_box).tobytes() for image in rendered.values()]
            self.assertTrue(all(region == safe_regions[0] for region in safe_regions[1:]))
            outer_regions = [self._outside_safe_box_bytes(image) for image in rendered.values()]
            self.assertEqual(len(set(outer_regions)), len(self.EXPECTED_IDS))

    def test_framed_page_batch_preserves_order_count_and_numbered_names(self):
        render_framed_pages = self._frame_api()["render_framed_pages"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = [
                self._marked_source(root / f"source-{index}.png", (300 + index, 500 + index))
                for index in range(3)
            ]
            outputs = render_framed_pages(sources, root / "frames", "minimal-white")
            self.assertEqual([path.name for path in outputs], ["001.png", "002.png", "003.png"])
            self.assertEqual(len(outputs), len(sources))
            for output in outputs:
                self.assertTrue(output.is_file())

    def test_framed_rendering_rejects_empty_unknown_missing_and_bad_sources(self):
        api = self._frame_api()
        render_framed_page, render_framed_pages = api["render_framed_page"], api["render_framed_pages"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = root / "missing.png"
            bad = root / "bad.png"
            bad.write_text("not an image", encoding="utf-8")
            with self.assertRaises(ValueError):
                render_framed_pages([], root / "frames", "classic-gray")
            with self.assertRaisesRegex(ValueError, "unknown card template"):
                render_framed_page(missing, root / "out.png", "not-a-template", 1, 1)
            with self.assertRaises(FileNotFoundError):
                render_framed_page(missing, root / "out.png", "classic-gray", 1, 1)
            with self.assertRaises(UnidentifiedImageError):
                render_framed_page(bad, root / "out.png", "classic-gray", 1, 1)

    @staticmethod
    def _marked_source(path: Path, size: tuple[int, int]) -> Path:
        image = Image.new("RGB", size, (35, 155, 210))
        marker = max(8, min(size) // 8)
        draw = ImageDraw.Draw(image)
        width, height = size
        draw.rectangle((0, 0, marker - 1, marker - 1), fill=(255, 0, 0))
        draw.rectangle((width - marker, 0, width - 1, marker - 1), fill=(0, 255, 0))
        draw.rectangle((0, height - marker, marker - 1, height - 1), fill=(0, 0, 255))
        draw.rectangle((width - marker, height - marker, width - 1, height - 1), fill=(255, 255, 0))
        image.save(path)
        return path

    @staticmethod
    def _source_bbox(image: Image.Image, safe_box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        pixels = image.load()
        candidates = [
            (x, y)
            for y in range(safe_box[1], safe_box[3])
            for x in range(safe_box[0], safe_box[2])
            if pixels[x, y] != (250, 250, 248)
        ]
        xs, ys = zip(*candidates)
        return min(xs), min(ys), max(xs) + 1, max(ys) + 1

    @staticmethod
    def _has_color_near(image: Image.Image, color: tuple[int, int, int], point: tuple[int, int]) -> bool:
        x, y = point
        return any(
            all(abs(actual - expected) <= 8 for actual, expected in zip(image.getpixel((sx, sy)), color))
            for sy in range(max(0, y - 4), min(image.height, y + 5))
            for sx in range(max(0, x - 4), min(image.width, x + 5))
        )

    @staticmethod
    def _outside_safe_box_bytes(image: Image.Image) -> bytes:
        safe_box = CardTemplateTests._frame_api_static()["SAFE_BOX"]
        pixels = image.load()
        return bytes(
            channel
            for y in range(image.height)
            for x in range(image.width)
            if not (safe_box[0] <= x < safe_box[2] and safe_box[1] <= y < safe_box[3])
            for channel in pixels[x, y]
        )

    def _frame_api(self) -> dict[str, object]:
        return self._frame_api_static()

    @staticmethod
    def _frame_api_static() -> dict[str, object]:
        names = ("WIDTH", "HEIGHT", "SAFE_BOX", "contain_size", "render_framed_page", "render_framed_pages")
        missing = [name for name in names if not hasattr(card_templates, name)]
        if missing:
            raise AssertionError(f"missing framed-page API: {', '.join(missing)}")
        return {name: getattr(card_templates, name) for name in names}


if __name__ == "__main__":
    unittest.main()

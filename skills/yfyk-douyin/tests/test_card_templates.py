import math
import os
import stat
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

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

    def test_safe_box_has_the_fixed_production_geometry(self):
        self.assertEqual(self._frame_api()["SAFE_BOX"], (90, 120, 990, 1320))

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

    def test_each_frame_has_its_specified_outer_style_without_safe_box_decoration(self):
        api = self._frame_api()
        safe_box, render_framed_page = api["SAFE_BOX"], api["render_framed_page"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._marked_source(root / "source.png", (360, 720))
            frames = {}
            for template_id in sorted(self.EXPECTED_IDS):
                target = root / f"{template_id}.png"
                render_framed_page(source, target, template_id, 2, 4)
                with Image.open(target).convert("RGB") as image:
                    frames[template_id] = image.copy()

            self.assertEqual(frames["classic-gray"].getpixel((0, 0)), (234, 227, 218))
            self._assert_region_outside_safe((72, 102, 90, 1320), safe_box)
            self.assertEqual(frames["classic-gray"].getpixel((80, 200)), (215, 206, 195))
            self._assert_region_outside_safe((48, 48, 51, 51), safe_box)
            self.assertEqual(frames["classic-gray"].getpixel((48, 48)), (255, 255, 255))

            self.assertEqual(frames["editorial-warm"].getpixel((0, 0)), (246, 240, 232))
            self._assert_region_outside_safe((42, 34, 1038, 51), safe_box)
            self.assertEqual(frames["editorial-warm"].getpixel((100, 42)), (183, 77, 54))
            self._assert_region_outside_safe((990, 120, 1080, 190), safe_box)
            self.assertTrue(self._region_has_color(frames["editorial-warm"], (990, 120, 1080, 190), (183, 77, 54)))

            self.assertEqual(frames["premium-dark"].getpixel((0, 0)), (23, 42, 58))
            self._assert_region_outside_safe((1002, 0, 1080, 169), safe_box)
            self.assertTrue(self._region_has_color(frames["premium-dark"], (1002, 0, 1080, 169), (217, 175, 103)))
            self._assert_region_outside_safe((90, 1320, 400, 1390), safe_box)
            self.assertTrue(self._region_has_color(frames["premium-dark"], (90, 1320, 400, 1390), (217, 175, 103)))

            self.assertEqual(frames["minimal-white"].getpixel((0, 0)), (255, 255, 255))
            self._assert_region_outside_safe((46, 52, 48, 120), safe_box)
            self.assertEqual(frames["minimal-white"].getpixel((46, 100)), (213, 216, 218))
            self._assert_region_outside_safe((990, 1320, 1080, 1390), safe_box)
            self.assertTrue(self._region_has_color(frames["minimal-white"], (990, 1320, 1080, 1390), (74, 79, 84), tolerance=64))

            for image in frames.values():
                self.assertEqual(image.crop(safe_box).getpixel((10, 10)), (255, 255, 255))

    def test_framed_page_batch_preserves_order_count_and_numbered_names(self):
        render_framed_pages = self._frame_api()["render_framed_pages"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            colors = [(190, 40, 50), (45, 145, 80), (45, 90, 190)]
            sources = [
                self._marked_source(root / f"source-{index}.png", (300 + index, 500 + index), colors[index])
                for index in range(len(colors))
            ]
            outputs = render_framed_pages(sources, root / "frames", "minimal-white")
            self.assertEqual([path.name for path in outputs], ["001.png", "002.png", "003.png"])
            self.assertEqual(len(outputs), len(sources))
            for output in outputs:
                self.assertTrue(output.is_file())
            for output, color in zip(outputs, colors):
                with Image.open(output).convert("RGB") as image:
                    self.assertEqual(image.getpixel((540, 720)), color)

    def test_editorial_three_digit_page_number_is_right_aligned_outside_the_safe_box(self):
        render_framed_page = self._frame_api()["render_framed_page"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._marked_source(root / "source.png", (360, 720))
            target = render_framed_page(source, root / "editorial.png", "editorial-warm", 100, 100)
            with Image.open(target).convert("RGB") as image:
                page_pixels = self._color_pixels(image, (990, 120, 1080, 190), (183, 77, 54), tolerance=64)
                self.assertTrue(page_pixels)
                self.assertGreaterEqual(min(x for x, _ in page_pixels), 990)
                self.assertGreater(max(x for x, _ in page_pixels), 1040)
                self.assertLess(max(x for x, _ in page_pixels), 1080)

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

    def test_framed_page_rejects_non_integer_and_invalid_page_numbers_for_every_template(self):
        render_framed_page = self._frame_api()["render_framed_page"]
        invalid_numbers = (
            (True, 1),
            (1, False),
            (1.0, 1),
            (1, 1.0),
            (math.nan, 1),
            (1, math.nan),
            (0, 1),
            (2, 1),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._marked_source(root / "source.png", (360, 720))
            for template_id in sorted(self.EXPECTED_IDS):
                for case_no, (page_no, total_pages) in enumerate(invalid_numbers):
                    target = root / f"{template_id}-{case_no}.png"
                    with self.assertRaisesRegex(ValueError, "page numbers"):
                        render_framed_page(source, target, template_id, page_no, total_pages)
                    self.assertFalse(target.exists())

    def test_framed_page_interrupted_write_preserves_existing_target(self):
        render_framed_page = self._frame_api()["render_framed_page"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._marked_source(root / "source.png", (360, 720))
            target = root / "out.png"
            original = b"existing target must survive"
            target.write_bytes(original)

            def interrupted_save(_image, path, *args, **kwargs):
                Path(path).write_bytes(b"partial")
                raise OSError("simulated write interruption")

            with patch.object(Image.Image, "save", new=interrupted_save):
                with self.assertRaisesRegex(OSError, "write interruption"):
                    render_framed_page(source, target, "classic-gray", 1, 1)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(set(root.iterdir()), {source, target})

    def test_framed_page_rejects_corrupt_staged_png_without_replacing_target(self):
        render_framed_page = self._frame_api()["render_framed_page"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._marked_source(root / "source.png", (360, 720))
            target = root / "out.png"
            original = b"existing target must survive validation"
            target.write_bytes(original)

            def corrupt_save(_image, path, *args, **kwargs):
                Path(path).write_bytes(b"not a png")

            with patch.object(Image.Image, "save", new=corrupt_save):
                with self.assertRaisesRegex(ValueError, "valid framed PNG"):
                    render_framed_page(source, target, "classic-gray", 1, 1)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(set(root.iterdir()), {source, target})

    def test_framed_page_publishes_readable_0644_png(self):
        render_framed_page = self._frame_api()["render_framed_page"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._marked_source(root / "source.png", (360, 720))
            target = render_framed_page(source, root / "out.png", "classic-gray", 1, 1)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
            else:
                self.assertTrue(os.access(target, os.R_OK))

    def test_framed_page_does_not_delete_new_owner_reusing_published_temp_name(self):
        render_framed_page = self._frame_api()["render_framed_page"]
        real_replace = os.replace
        reused = {}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._marked_source(root / "source.png", (360, 720))
            target = root / "out.png"

            def replace_then_reuse(temporary, published):
                real_replace(temporary, published)
                reused["path"] = Path(temporary)
                reused["path"].write_bytes(b"new owner")

            with patch.object(card_templates.os, "replace", side_effect=replace_then_reuse):
                self.assertEqual(render_framed_page(source, target, "classic-gray", 1, 1), target)
            self.assertTrue(reused["path"].is_file())
            self.assertEqual(reused["path"].read_bytes(), b"new owner")

    def test_framed_pages_rejects_existing_directory_and_dangling_symlink(self):
        render_framed_pages = self._frame_api()["render_framed_pages"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._marked_source(root / "source.png", (360, 720))
            existing = root / "existing"
            existing.mkdir()
            old = existing / "001.png"
            old.write_bytes(b"old short batch")
            with self.assertRaises(FileExistsError):
                render_framed_pages([source], existing, "minimal-white")
            self.assertEqual(old.read_bytes(), b"old short batch")

            dangling = root / "dangling"
            dangling.symlink_to(root / "missing", target_is_directory=True)
            with self.assertRaises(FileExistsError):
                render_framed_pages([source], dangling, "minimal-white")
            self.assertTrue(os.path.lexists(dangling))

    def test_bad_second_page_leaves_no_published_or_staging_directory(self):
        render_framed_pages = self._frame_api()["render_framed_pages"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = self._marked_source(root / "first.png", (360, 720))
            bad = root / "bad.png"
            bad.write_bytes(b"bad image")
            target = root / "frames"
            with self.assertRaises(UnidentifiedImageError):
                render_framed_pages([first, bad], target, "classic-gray")
            self.assertFalse(os.path.lexists(target))
            self.assertFalse(any(path.name.startswith(".frames-") for path in root.iterdir()))

    def test_failed_batch_reports_staging_cleanup_error(self):
        render_framed_pages = self._frame_api()["render_framed_pages"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = self._marked_source(root / "first.png", (360, 720))
            bad = root / "bad.png"
            bad.write_bytes(b"bad image")
            with patch.object(card_templates.shutil, "rmtree", side_effect=OSError("cleanup denied")):
                try:
                    render_framed_pages([first, bad], root / "frames", "classic-gray")
                except Exception as exc:
                    self.assertIsInstance(exc, RuntimeError)
                    self.assertIn("failed to clean framed card staging directory", str(exc))
                else:
                    self.fail("staging cleanup failure was not reported")

    def test_sources_inside_numbered_target_directory_are_not_overwritten(self):
        render_framed_pages = self._frame_api()["render_framed_pages"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "frames"
            target.mkdir()
            first = self._marked_source(target / "001.png", (300, 500), (180, 40, 50))
            second = self._marked_source(target / "002.png", (310, 510), (40, 150, 80))
            originals = [path.read_bytes() for path in (first, second)]
            with self.assertRaises(FileExistsError):
                render_framed_pages([first, second], target, "premium-dark")
            self.assertEqual([path.read_bytes() for path in (first, second)], originals)

    def test_target_appearing_during_batch_publish_is_not_replaced_or_mixed(self):
        render_framed_pages = self._frame_api()["render_framed_pages"]
        real_render_page = self._frame_api()["render_framed_page"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = [
                self._marked_source(root / f"source-{index}.png", (300, 500), color)
                for index, color in enumerate(((180, 40, 50), (40, 150, 80)), start=1)
            ]
            target = root / "frames"

            def external_target_arrives(source, staged_target, template_id, page_no, total_pages):
                output = real_render_page(source, staged_target, template_id, page_no, total_pages)
                if page_no == total_pages:
                    target.mkdir()
                    (target / "external.txt").write_text("keep me", encoding="utf-8")
                return output

            with patch.object(card_templates, "render_framed_page", side_effect=external_target_arrives):
                with self.assertRaises(FileExistsError):
                    render_framed_pages(sources, target, "classic-gray")
            self.assertEqual([path.name for path in target.iterdir()], ["external.txt"])
            self.assertEqual((target / "external.txt").read_text(encoding="utf-8"), "keep me")

    def test_concurrent_batches_publish_one_complete_template_without_mixing(self):
        render_framed_pages = self._frame_api()["render_framed_pages"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            colors = ((180, 40, 50), (40, 150, 80), (40, 80, 180))
            sources = [
                self._marked_source(root / f"source-{index}.png", (300, 500), color)
                for index, color in enumerate(colors, start=1)
            ]
            target = root / "frames"

            def run(template_id):
                try:
                    return "ok", template_id, render_framed_pages(sources, target, template_id)
                except FileExistsError as exc:
                    return "exists", template_id, exc

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(run, ("classic-gray", "premium-dark")))
            self.assertEqual(sorted(status for status, _, _ in results), ["exists", "ok"])
            self.assertEqual(sorted(path.name for path in target.iterdir()), ["001.png", "002.png", "003.png"])
            corner_colors = []
            for index, expected_color in enumerate(colors, start=1):
                with Image.open(target / f"{index:03d}.png").convert("RGB") as image:
                    corner_colors.append(image.getpixel((0, 0)))
                    self.assertEqual(image.getpixel((540, 720)), expected_color)
            self.assertEqual(len(set(corner_colors)), 1)

    def test_framed_pages_publish_readable_0755_directory_and_0644_pngs(self):
        render_framed_pages = self._frame_api()["render_framed_pages"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = [
                self._marked_source(root / f"source-{index}.png", (300, 500), color)
                for index, color in enumerate(((180, 40, 50), (40, 150, 80)), start=1)
            ]
            target = root / "frames"
            outputs = render_framed_pages(sources, target, "minimal-white")
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)
                self.assertEqual([stat.S_IMODE(path.stat().st_mode) for path in outputs], [0o644, 0o644])
            else:
                self.assertTrue(os.access(target, os.R_OK | os.X_OK))
                self.assertTrue(all(os.access(path, os.R_OK) for path in outputs))

    def test_framed_pages_do_not_delete_new_owner_reusing_published_staging_name(self):
        render_framed_pages = self._frame_api()["render_framed_pages"]
        real_publish = card_templates._atomic_publish_directory_no_replace
        reused = {}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._marked_source(root / "source.png", (360, 720))
            target = root / "frames"

            def publish_then_reuse(staging, published):
                real_publish(staging, published)
                reused["path"] = Path(staging)
                reused["path"].mkdir()
                (reused["path"] / "new-owner.txt").write_text("keep me", encoding="utf-8")

            with patch.object(card_templates, "_atomic_publish_directory_no_replace", side_effect=publish_then_reuse):
                outputs = render_framed_pages([source], target, "premium-dark")
            self.assertEqual(outputs, [target / "001.png"])
            self.assertTrue((reused["path"] / "new-owner.txt").is_file())
            self.assertEqual((reused["path"] / "new-owner.txt").read_text(encoding="utf-8"), "keep me")

    @staticmethod
    def _marked_source(path: Path, size: tuple[int, int], fill: tuple[int, int, int] = (35, 155, 210)) -> Path:
        image = Image.new("RGB", size, fill)
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
            if pixels[x, y] != (255, 255, 255)
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

    @staticmethod
    def _assert_region_outside_safe(region: tuple[int, int, int, int], safe_box: tuple[int, int, int, int]) -> None:
        left, top, right, bottom = region
        safe_left, safe_top, safe_right, safe_bottom = safe_box
        intersects = left < safe_right and right > safe_left and top < safe_bottom and bottom > safe_top
        if intersects:
            raise AssertionError(f"decoration region intersects SAFE_BOX: {region}")

    @staticmethod
    def _color_pixels(
        image: Image.Image,
        region: tuple[int, int, int, int],
        color: tuple[int, int, int],
        tolerance: int = 0,
    ) -> list[tuple[int, int]]:
        left, top, right, bottom = region
        return [
            (x, y)
            for y in range(top, bottom)
            for x in range(left, right)
            if all(abs(actual - expected) <= tolerance for actual, expected in zip(image.getpixel((x, y)), color))
        ]

    @classmethod
    def _region_has_color(
        cls,
        image: Image.Image,
        region: tuple[int, int, int, int],
        color: tuple[int, int, int],
        tolerance: int = 0,
    ) -> bool:
        return bool(cls._color_pixels(image, region, color, tolerance))

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

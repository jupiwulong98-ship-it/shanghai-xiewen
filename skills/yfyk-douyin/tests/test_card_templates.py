import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

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


if __name__ == "__main__":
    unittest.main()

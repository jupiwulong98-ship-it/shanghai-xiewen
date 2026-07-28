#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

SKILL_DIR = Path(__file__).resolve().parent.parent
FONT_PATH = SKILL_DIR / "assets/cjk-font/NotoSansSC.ttf"
WIDTH, HEIGHT = 1080, 1440
SAFE_BOX = (90, 120, 990, 1320)
SAFE_FILL = "#FAFAF8"


@dataclass(frozen=True)
class TemplateSpec:
    id: str
    display_name: str
    canvas_fill: str
    panel_fill: str
    title_color: str
    body_color: str
    accent_color: str
    border_color: str | None
    variant: str


TEMPLATES = {
    spec.id: spec
    for spec in (
        TemplateSpec("classic-gray", "经典灰边", "#EEEAE3", "#FFFFFF", "#22577A", "#252525", "#B45A2A", None, "classic"),
        TemplateSpec("editorial-warm", "品牌杂志", "#F7F3ED", "#F7F3ED", "#222222", "#352F2A", "#C65B35", "#E7DDD0", "editorial"),
        TemplateSpec("premium-dark", "深色质感", "#172331", "#223442", "#FFFFFF", "#D5DDE3", "#E7B469", None, "premium"),
        TemplateSpec("minimal-white", "极简白纸", "#FFFFFF", "#FFFFFF", "#111111", "#444444", "#111111", "#DFE3E6", "minimal"),
    )
}


def load_font(size: int):
    if not FONT_PATH.exists() or FONT_PATH.stat().st_size < 100_000:
        raise FileNotFoundError(f"中文字体资产缺失或不完整：{FONT_PATH}")
    return ImageFont.truetype(str(FONT_PATH), size=size)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        if current and draw.textlength(trial, font=font) > max_width:
            lines.append(current)
            current = char
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [""]


def contain_size(width: int, height: int, max_width: int, max_height: int) -> tuple[int, int]:
    """Return the largest whole-pixel size that fits within the supplied bounds."""
    if min(width, height, max_width, max_height) <= 0:
        raise ValueError("image and container dimensions must be positive")
    scale = min(max_width / width, max_height / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _draw_frame(canvas: Image.Image, template_id: str, page_no: int, total_pages: int) -> None:
    """Draw a template's ornament outside the shared source-safe area."""
    spec = TEMPLATES[template_id]
    draw = ImageDraw.Draw(canvas)
    left, top, right, bottom = SAFE_BOX

    if spec.variant == "classic":
        draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), fill="#EAE3DA")
        draw.rectangle((72, top - 18, left - 1, bottom + 20), fill="#D7CEC3")
        draw.rectangle((right, top - 6, right + 17, bottom + 32), fill="#D7CEC3")
        draw.rectangle((left - 18, bottom, right + 20, bottom + 17), fill="#D7CEC3")
        draw.rectangle((48, 48, WIDTH - 49, HEIGHT - 49), outline="#FFFFFF", width=3)
    elif spec.variant == "editorial":
        draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), fill="#F6F0E8")
        draw.rectangle((42, 34, WIDTH - 43, 50), fill="#B74D36")
        draw.rectangle((42, 34, WIDTH - 43, HEIGHT - 43), outline="#DCCFC0", width=2)
        font = load_font(24)
        page_label = f"{page_no:02d}/{total_pages:02d}"
        draw.text((1002, 130), page_label, font=font, fill="#B74D36", anchor="la")
    elif spec.variant == "premium":
        draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), fill="#172A3A")
        draw.ellipse((1002, -56, 1226, 168), outline="#D9AF67", width=3)
        draw.ellipse((1042, -16, 1186, 128), outline="#D9AF67", width=1)
        draw.rectangle((50, 52, WIDTH - 51, HEIGHT - 53), outline="#294154", width=2)
        font = load_font(16)
        draw.text((90, 1360), "DOUYIN GRAPHIC · REPORT", font=font, fill="#D9AF67")
    else:
        draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), fill="#FFFFFF")
        draw.rectangle((46, 52, WIDTH - 47, HEIGHT - 53), outline="#D5D8DA", width=2)
        font = load_font(20)
        draw.text((1004, 1350), f"{page_no:02d}", font=font, fill="#4A4F54")

    # This is deliberately last: every template exposes the exact same source area.
    draw.rectangle((left, top, right - 1, bottom - 1), fill=SAFE_FILL)


def render_framed_page(
    source_page: Path,
    target: Path,
    template_id: str,
    page_no: int,
    total_pages: int,
) -> Path:
    """Place one pre-rendered source page inside a fixed 1080×1440 template frame."""
    if template_id not in TEMPLATES:
        raise ValueError(f"unknown card template: {template_id}")
    if page_no <= 0 or total_pages <= 0 or page_no > total_pages:
        raise ValueError("page numbers must be positive and ordered")
    source_page = Path(source_page)
    target = Path(target)
    if not source_page.is_file():
        raise FileNotFoundError(source_page)

    with Image.open(source_page) as source:
        source_rgb = source.convert("RGB")
    resized_size = contain_size(source_rgb.width, source_rgb.height, SAFE_BOX[2] - SAFE_BOX[0], SAFE_BOX[3] - SAFE_BOX[1])
    resized = source_rgb.resize(resized_size, Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", (WIDTH, HEIGHT))
    _draw_frame(canvas, template_id, page_no, total_pages)
    x = SAFE_BOX[0] + (SAFE_BOX[2] - SAFE_BOX[0] - resized.width) // 2
    y = SAFE_BOX[1] + (SAFE_BOX[3] - SAFE_BOX[1] - resized.height) // 2
    canvas.paste(resized, (x, y))
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, format="PNG")
    return target


def render_framed_pages(source_pages: list[Path], target_dir: Path, template_id: str) -> list[Path]:
    """Frame source pages in their supplied order, using stable numbered PNG filenames."""
    if template_id not in TEMPLATES:
        raise ValueError(f"unknown card template: {template_id}")
    if not source_pages:
        raise ValueError("source pages must not be empty")
    target_dir = Path(target_dir)
    total_pages = len(source_pages)
    return [
        render_framed_page(Path(source), target_dir / f"{index:03d}.png", template_id, index, total_pages)
        for index, source in enumerate(source_pages, start=1)
    ]


class CardRenderer:
    def __init__(self, target_dir: Path, template_id: str):
        if template_id not in TEMPLATES:
            raise ValueError(f"unknown card template: {template_id}")
        self.spec = TEMPLATES[template_id]
        self.target_dir = target_dir
        self.target_dir.mkdir(parents=True, exist_ok=True)
        self.cards: list[Path] = []
        self.canvas: Image.Image | None = None
        self.draw: ImageDraw.ImageDraw | None = None
        self.page_no = 0
        self.left, self.right, self.top, self.bottom = self._geometry()
        self.y = self.top
        self.new_page()

    def _geometry(self) -> tuple[int, int, int, int]:
        if self.spec.variant == "minimal":
            return 92, 988, 94, 1330
        if self.spec.variant == "editorial":
            return 100, 980, 112, 1325
        if self.spec.variant == "premium":
            return 104, 976, 108, 1320
        return 100, 980, 86, 1345

    def new_page(self):
        if self.canvas is not None:
            self.save_page()
        self.page_no += 1
        self.canvas = Image.new("RGB", (WIDTH, HEIGHT), self.spec.canvas_fill)
        self.draw = ImageDraw.Draw(self.canvas)
        if self.spec.variant == "classic":
            self.draw.rounded_rectangle((38, 30, 1042, 1410), radius=12, fill=self.spec.panel_fill)
        elif self.spec.variant == "editorial":
            self.draw.rectangle((42, 38, 1038, 1402), fill=self.spec.panel_fill, outline=self.spec.border_color, width=2)
            self.draw.rectangle((42, 38, 1038, 54), fill=self.spec.accent_color)
        elif self.spec.variant == "premium":
            self.draw.rounded_rectangle((42, 38, 1038, 1402), radius=18, fill=self.spec.panel_fill)
            self.draw.ellipse((850, -70, 1140, 220), outline=self.spec.accent_color, width=2)
        else:
            self.draw.rectangle((54, 48, 1026, 1392), fill=self.spec.panel_fill, outline=self.spec.border_color, width=2)
        self.y = self.top

    def save_page(self):
        if self.spec.variant == "editorial":
            font = load_font(34)
            text = f"{self.page_no:02d}"
            self.draw.text((self.right - self.draw.textlength(text, font=font), 1342), text, font=font, fill="#D8CBBB")
        elif self.spec.variant == "premium":
            font = load_font(17)
            self.draw.text((self.left, 1356), "DOUYIN GRAPHIC · REPORT", font=font, fill=self.spec.accent_color)
        elif self.spec.variant == "minimal":
            font = load_font(17)
            text = f"{self.page_no:02d}"
            self.draw.text((self.right - self.draw.textlength(text, font=font), 1350), text, font=font, fill="#777777")
        path = self.target_dir / f"{self.page_no:03d}.png"
        self.canvas.save(path, format="PNG")
        self.cards.append(path)

    def ensure(self, height: int):
        if self.y + height > self.bottom:
            self.new_page()

    def add_text(self, text: str, style: str = "Normal"):
        heading = style == "Title" or style.startswith("Heading")
        if style == "Title":
            size, before, after, gap = 36, 0, 22, 51
        elif style == "Heading 1":
            size, before, after, gap = 29, 20, 14, 42
        elif style == "Heading 2":
            size, before, after, gap = 26, 17, 12, 39
        elif style == "Heading 3":
            size, before, after, gap = 23, 13, 10, 36
        else:
            size, before, after, gap = 19, 2, 10, 31
        if self.spec.variant == "minimal" and heading:
            size += 2
        color = self.spec.title_color if heading else self.spec.body_color
        font = load_font(size)
        lines = wrap_text(self.draw, text, font, self.right - self.left)
        required_total = before + len(lines) * gap + after + (10 if heading else 0)
        self.ensure(required_total)
        self.y += before
        for line in lines:
            self.draw.text((self.left, self.y), line, font=font, fill=color)
            self.y += gap
        if heading:
            rule_width = self.right - self.left if self.spec.variant == "minimal" else 76
            self.draw.rectangle((self.left, self.y + 2, self.left + rule_width, self.y + 5), fill=self.spec.accent_color)
            self.y += 10
        self.y += after

    def add_table(self, rows: list[list[str]]):
        for row_index, row in enumerate(rows):
            text = " | ".join(cell for cell in row if cell)
            self.add_text(text, "Heading 3" if row_index == 0 else "Normal")

    def add_image(self, path: Path):
        with Image.open(path).convert("RGB") as image:
            max_w = self.right - self.left
            max_h = 680
            scale = min(max_w / image.width, max_h / image.height, 1.0)
            resized = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                Image.Resampling.LANCZOS,
            )
            required = resized.height + 26
            self.ensure(required)
            x = (WIDTH - resized.width) // 2
            if self.spec.variant == "premium":
                self.draw.rounded_rectangle((x - 8, self.y - 8, x + resized.width + 8, self.y + resized.height + 8), radius=8, fill="#F7F3ED")
            self.canvas.paste(resized, (x, self.y))
            self.y += required

    def finish(self) -> list[Path]:
        self.save_page()
        return self.cards


def render_cards(blocks: list[dict[str, Any]], target_dir: Path, template_id: str) -> list[Path]:
    renderer = CardRenderer(target_dir, template_id)
    list_no = 0
    for block in blocks:
        if block["type"] == "paragraph":
            text = block.get("text", "")
            if not text or text.startswith("(Web)"):
                continue
            style = block.get("style", "Normal")
            if style == "List Number":
                list_no += 1
                text = f"{list_no}. {text}"
            elif style.startswith("Heading"):
                list_no = 0
            renderer.add_text(text, style)
        elif block["type"] == "table":
            renderer.add_table(block["rows"])
        elif block["type"] == "image" and Path(block["path"]).exists():
            renderer.add_image(Path(block["path"]))
    return renderer.finish()

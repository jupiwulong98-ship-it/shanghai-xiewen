#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from PIL import Image


RANK_HEADING = re.compile(r"(综合榜|排名|排行|推荐榜|评分榜|榜单)", re.I)
HEADING_ITEM = re.compile(r"(?:榜单)?第\s*([一二三四五六七八九十百\d]+)\s*名?[：:\s—-]+(.+)")
TOP_ITEM = re.compile(r"TOP\s*(\d+)[：:\s—-]*(.+)", re.I)
ARABIC = re.compile(r"^\s*(\d+)[.、\s|]+(.+)")
CHINESE_NUMBERS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
ARTICLE_BRAND = re.compile(r"([一-龥]{2})(整装|装饰|家居)")
GENERIC_BRAND_STEMS = {
    "专业",
    "品质",
    "高端",
    "全屋",
    "家庭",
    "进行",
    "整体",
    "现代",
    "选择",
    "装修",
    "我们",
}


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def iter_blocks(doc: DocumentType) -> Iterable[Paragraph | Table]:
    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield Table(child, doc)


def image_blocks(paragraph: Paragraph, media_dir: Path, stem: str, counter: list[int]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for blip in paragraph._p.xpath(".//a:blip"):
        rid = blip.get(qn("r:embed"))
        if not rid or rid not in paragraph.part.related_parts:
            continue
        part = paragraph.part.related_parts[rid]
        counter[0] += 1
        suffix = Path(str(part.partname)).suffix or ".png"
        target = media_dir / f"{stem}-{counter[0]:03d}{suffix}"
        target.write_bytes(part.blob)
        width = height = None
        try:
            with Image.open(target) as im:
                width, height = im.size
        except Exception:
            pass
        found.append({
            "type": "image",
            "path": str(target.resolve()),
            "width": width,
            "height": height,
            "relationship_id": rid,
        })
    return found


def extract_blocks(path: Path, media_dir: Path) -> list[dict[str, Any]]:
    doc = Document(path)
    media_dir.mkdir(parents=True, exist_ok=True)
    blocks: list[dict[str, Any]] = []
    counter = [0]
    block_no = 0
    for item in iter_blocks(doc):
        if isinstance(item, Paragraph):
            text = clean(item.text)
            if text:
                block_no += 1
                blocks.append({
                    "id": f"b{block_no}",
                    "type": "paragraph",
                    "style": item.style.name if item.style else "Normal",
                    "text": text,
                })
            for image in image_blocks(item, media_dir, path.stem, counter):
                block_no += 1
                image["id"] = f"b{block_no}"
                blocks.append(image)
        else:
            rows = [[clean(cell.text) for cell in row.cells] for row in item.rows]
            if rows:
                block_no += 1
                blocks.append({"id": f"b{block_no}", "type": "table", "rows": rows})
    return blocks


def to_rank(value: str) -> int | None:
    value = clean(value)
    if value.isdigit():
        return int(value)
    if value in CHINESE_NUMBERS:
        return CHINESE_NUMBERS[value]
    return None


def split_name_description(text: str) -> tuple[str, str]:
    text = clean(text).strip("| ")
    parts = re.split(r"[：:—–-]", text, maxsplit=1)
    return clean(parts[0]), clean(parts[1]) if len(parts) > 1 else ""


def table_candidate(block: dict[str, Any], index: int) -> dict[str, Any] | None:
    rows = block["rows"]
    items = []
    for row in rows:
        if len(row) < 2:
            continue
        rank = to_rank(row[0].strip("| "))
        if not rank:
            continue
        name = clean(row[1].strip("| "))
        if not name:
            continue
        score = None
        description = ""
        if len(row) >= 3:
            third = clean(row[2].strip("| "))
            if re.fullmatch(r"\d+(?:\.\d+)?(?:分)?", third):
                score = third.removesuffix("分")
                description = clean(" ".join(cell.strip("| ") for cell in row[3:]))
            else:
                description = clean(" ".join(cell.strip("| ") for cell in row[2:]))
        items.append({"rank": rank, "name": name, "description": description, "score": score})
    if len(items) < 2:
        return None
    items.sort(key=lambda x: x["rank"])
    return {
        "id": f"ranking-table-{index}",
        "heading": "表格榜单",
        "confidence": 0.94,
        "block_ids": [block["id"]],
        "items": items,
    }


def pipe_candidates(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block["type"] != "paragraph" or "|" not in block["text"] or "排名" not in block["text"]:
            i += 1
            continue
        items = []
        ids = [block["id"]]
        j = i + 1
        while j < len(blocks):
            following = blocks[j]
            if following["type"] != "paragraph" or "|" not in following["text"]:
                break
            cells = [clean(cell) for cell in following["text"].strip().strip("|").split("|")]
            j += 1
            if not cells or all(re.fullmatch(r"[-:]+", cell or "-") for cell in cells):
                continue
            if len(cells) < 2:
                break
            rank = to_rank(cells[0])
            if not rank:
                break
            name = cells[1]
            score = None
            description = ""
            if len(cells) >= 3:
                if re.fullmatch(r"\d+(?:\.\d+)?(?:分)?", cells[2]):
                    score = cells[2].removesuffix("分")
                    description = clean(" ".join(cells[3:]))
                else:
                    description = clean(" ".join(cells[2:]))
            items.append({"rank": rank, "name": name, "description": description, "score": score})
            ids.append(following["id"])
        if len(items) >= 2:
            candidates.append({
                "id": f"ranking-pipe-{len(candidates) + 1}",
                "heading": block["text"],
                "confidence": 0.97,
                "block_ids": ids,
                "items": items,
            })
        i = max(j, i + 1)
    return candidates


def list_candidates(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for i, block in enumerate(blocks):
        if block["type"] != "paragraph" or not RANK_HEADING.search(block["text"]):
            continue
        items = []
        ids = [block["id"]]
        for following in blocks[i + 1:]:
            if following["type"] != "paragraph":
                if items:
                    break
                continue
            text = following["text"]
            style = following.get("style", "")
            match = ARABIC.match(text)
            if style == "List Number":
                rank = len(items) + 1
                payload = text
            elif match:
                rank = int(match.group(1))
                payload = match.group(2)
            else:
                if items:
                    break
                if style.startswith("Heading"):
                    break
                continue
            name, description = split_name_description(payload)
            if not name:
                break
            items.append({"rank": rank, "name": name, "description": description, "score": None})
            ids.append(following["id"])
        if len(items) >= 2:
            candidates.append({
                "id": f"ranking-list-{len(candidates) + 1}",
                "heading": block["text"],
                "confidence": 0.96,
                "block_ids": ids,
                "items": items,
            })
    return candidates


def heading_candidate(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    items = []
    ids = []
    for block in blocks:
        if block["type"] != "paragraph" or not block.get("style", "").startswith("Heading"):
            continue
        text = block["text"]
        match = HEADING_ITEM.search(text) or TOP_ITEM.search(text)
        if not match:
            continue
        rank = to_rank(match.group(1))
        if not rank:
            continue
        name, description = split_name_description(match.group(2))
        items.append({"rank": rank, "name": name, "description": description, "score": None})
        ids.append(block["id"])
    if len(items) < 2:
        return None
    items.sort(key=lambda x: x["rank"])
    return {
        "id": "ranking-headings-1",
        "heading": "名次标题榜单",
        "confidence": 0.9,
        "block_ids": ids,
        "items": items,
    }


def find_rankings(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = pipe_candidates(blocks) + list_candidates(blocks)
    for index, block in enumerate(blocks, 1):
        if block["type"] == "table":
            candidate = table_candidate(block, index)
            if candidate:
                candidates.append(candidate)
    heading = heading_candidate(blocks)
    if heading:
        candidates.append(heading)
    # Deduplicate candidates that contain the same ordered names.
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for candidate in sorted(candidates, key=lambda x: x["confidence"], reverse=True):
        signature = tuple(re.split(r"[，,（(]", item["name"], maxsplit=1)[0].strip() for item in candidate["items"])
        if signature not in seen:
            seen.add(signature)
            unique.append(candidate)
    return unique


def article_brand_candidates(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Infer only repeatedly named, brand-shaped terms from article prose."""
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    first_position: dict[str, int] = {}
    paragraph_no = 0
    for block in blocks:
        if block["type"] != "paragraph":
            continue
        paragraph_no += 1
        paragraph_candidates: dict[str, int] = {}
        for match in ARTICLE_BRAND.finditer(block["text"]):
            stem = match.group(1)
            if stem in GENERIC_BRAND_STEMS:
                continue
            paragraph_candidates.setdefault(match.group(0), match.start())
        for value, position in paragraph_candidates.items():
            counts[value] = counts.get(value, 0) + 1
            first_seen.setdefault(value, paragraph_no)
            first_position.setdefault(value, position)

    repeated = [value for value, count in counts.items() if count >= 2]
    repeated.sort(
        key=lambda value: (
            -counts[value],
            first_seen[value],
            first_position[value],
            value,
        )
    )
    return [
        {
            "value": value,
            "confidence": min(0.55 + 0.05 * (counts[value] - 2), 0.75),
            "reason": f"article-repeated-brand-shaped-term:{counts[value]}",
        }
        for value in repeated
    ]


def inspect_document(path: Path, work_dir: Path) -> dict[str, Any]:
    blocks = extract_blocks(path, work_dir / "media")
    rankings = find_rankings(blocks)
    content_mode = "ranking" if rankings else "article"
    first_text = next((b["text"] for b in blocks if b["type"] == "paragraph"), "")
    title = first_text if first_text and len(first_text) <= 80 else path.stem
    brands = []
    if rankings and rankings[0]["items"]:
        brands.append({
            "value": rankings[0]["items"][0]["name"],
            "confidence": 0.65,
            "reason": "main-ranking-first",
        })
    else:
        brands = article_brand_candidates(blocks)
    warnings = []
    if len(rankings) > 1 and abs(rankings[0]["confidence"] - rankings[1]["confidence"]) <= 0.08:
        warnings.append({"code": "AMBIGUOUS_RANKING", "message": "检测到多套可信度接近的榜单，需要确认"})
    return {
        "source_path": str(path.resolve()),
        "source_title": title,
        "content_mode": content_mode,
        "blocks": blocks,
        "brand_candidates": brands,
        "keyword_candidates": [{"value": path.stem, "confidence": 0.4, "reason": "filename"}],
        "ranking_candidates": rankings,
        "warnings": warnings,
    }


def inspect_sources(input_path: Path, work_dir: Path) -> dict[str, Any]:
    files = [input_path] if input_path.is_file() else sorted(input_path.glob("*.docx"))
    if not files:
        raise ValueError(f"未找到 DOCX：{input_path}")
    documents = [inspect_document(path, work_dir / f"{index:03d}") for index, path in enumerate(files, 1)]
    return {"version": 1, "documents": documents}


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect DOCX sources for Douyin card generation.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    result = inspect_sources(args.input, args.work_dir)
    output = args.output or args.work_dir / "inspection.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

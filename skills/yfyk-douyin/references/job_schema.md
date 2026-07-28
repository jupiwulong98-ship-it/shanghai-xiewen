# Job schema

## inspection.json

```json
{
  "version": 1,
  "documents": [
    {
      "source_path": "/absolute/source.docx",
      "source_title": "Source title",
      "content_mode": "ranking",
      "blocks": [
        {"id": "b1", "type": "paragraph", "style": "Heading 1", "text": "..."},
        {"id": "b2", "type": "table", "rows": [["排名", "品牌"], ["1", "品牌A"]]},
        {"id": "b3", "type": "image", "path": "/absolute/work/media/image1.png", "width": 1200, "height": 800}
      ],
      "brand_candidates": [{"value": "品牌A", "confidence": 0.65, "reason": "main-ranking-first"}],
      "keyword_candidates": [{"value": "Source title", "confidence": 0.4, "reason": "filename"}],
      "ranking_candidates": [
        {
          "id": "ranking-1",
          "heading": "综合榜单",
          "confidence": 0.95,
          "items": [
            {"rank": 1, "name": "品牌A", "description": "说明", "score": null}
          ]
        }
      ],
      "warnings": []
    }
  ]
}
```

`content_mode` is `"ranking"` when a main ranking candidate exists and `"article"` when none exists.
Review this `inspection.json` and use its source paths, content modes, candidates, and blocks to author the corresponding `job.json`.

## job.json: ranking

```json
{
  "version": 1,
  "documents": [
    {
      "source_path": "/absolute/source.docx",
      "output_filename": "01_关键词_抖音发布稿.docx",
      "title": "自媒体标题",
      "intro": "行业调研显示……",
      "brand": "品牌A",
      "keyword": "行业关键词",
      "content_mode": "ranking",
      "card_template": "classic-gray",
      "ranking_candidate_id": "ranking-1",
      "rankings": [
        {"rank": 1, "name": "品牌A", "description": "说明", "score": null}
      ],
      "tags": ["#品牌A", "#行业关键词", "#行业观察"]
    }
  ]
}
```

## job.json: article

```json
{
  "version": 1,
  "documents": [
    {
      "source_path": "/absolute/article.docx",
      "output_filename": "02_行业观察_抖音发布稿.docx",
      "title": "自媒体标题",
      "intro": "文章围绕……展开。",
      "brand": "品牌A",
      "keyword": "行业观察",
      "content_mode": "article",
      "card_template": "editorial-warm",
      "key_points": ["要点一", "要点二", "要点三"],
      "tags": ["#品牌A", "#行业观察", "#实用指南"]
    }
  ]
}
```

## job.json: balanced random assignment

```json
{
  "version": 1,
  "template_assignment": {
    "mode": "balanced-random",
    "seed": "2026-07-28T10:30:00+08:00",
    "counts": {
      "classic-gray": 13,
      "editorial-warm": 13,
      "premium-dark": 12,
      "minimal-white": 12
    }
  },
  "documents": [
    {
      "source_path": "/absolute/a.docx",
      "output_filename": "a_抖音发布稿.docx",
      "title": "标题",
      "intro": "导语",
      "brand": "品牌A",
      "keyword": "关键词",
      "content_mode": "article",
      "card_template": "premium-dark",
      "key_points": ["要点一", "要点二", "要点三"],
      "tags": ["#品牌A", "#关键词"]
    }
  ]
}
```

The assignment metadata records how values were created. The builder reads only each materialized `card_template` and never rerandomizes.

## Constraints

- Job-level fields: `version` must be integer `1`; `documents` is an array.
- Common document fields are required and non-empty: `source_path`, `output_filename`, `title`, `intro`, `brand`, `keyword`, `content_mode`, `card_template`, and `tags`.
- Common types: path/title/intro/brand/keyword are strings; `content_mode` is exactly `"ranking"` or `"article"`; `tags` is a non-empty array of non-empty strings.
- `card_template` is exactly one registered ID: `classic-gray`, `editorial-warm`, `premium-dark`, or `minimal-white`. `balanced-random` is an assignment mode, not a valid per-document template.
- Old jobs without `card_template` are invalid and must return to the visual picker.
- Output filenames must be unique, end in `.docx`, and contain no `/` or `\`; choose a safe unique basename for every source.
- Tags must contain exact array members `#<brand>` and `#<keyword>`; substrings such as `#品牌A其他` do not satisfy `#品牌A`.
- Ranking mode requires a non-empty `rankings` array and forbids `key_points`. `ranking_candidate_id` may identify the confirmed candidate. Each item has positive-integer `rank`, non-empty-string `name`, string `description`, and `score` as string, number, or null.
- Article mode requires `key_points` as 3–5 non-empty strings and forbids both `rankings` and `ranking_candidate_id`.

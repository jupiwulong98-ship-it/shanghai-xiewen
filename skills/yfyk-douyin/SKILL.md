---
name: yfyk-douyin
description: Convert one or more ranking or non-ranking article, research, report, or observation DOCX files into complete editable Douyin graphic-post release DOCX files with clickable visual template selection and balanced-random batch styling. Use for 3:4 Douyin cards, batch channel delivery, editable copy, or complete embedded source cards.
---

# YFYK Douyin

Produce one final release DOCX per source DOCX. Keep title, body content, and tags editable; preserve the complete source as embedded 1080×1440 cards; leave only final DOCX files in the delivery directory.

## Required workflow

1. Read [references/content_rules.md](references/content_rules.md) and [references/job_schema.md](references/job_schema.md).
2. Ask the user to confirm the absolute output directory. Never infer it.
3. Inspect sources:

```bash
python3 scripts/inspect_sources.py \
  --input "/absolute/source-or-folder" \
  --work-dir "/absolute/temp/work" \
  --output "/absolute/temp/work/inspection.json"
```

4. Review `inspection.json`.
   - Use `content_mode: "ranking"` when a main ranking exists; otherwise use `"article"` and continue.
   - If `AMBIGUOUS_RANKING` appears, show only the candidate headings and ordered names, then ask the user to choose.
   - For articles, infer the publishing brand only from a clear repeated brand-shaped subject. If absent or ambiguous, ask.
   - User-provided title, intro, brand, keyword, or tags always override inference.
5. Generate real production previews before creating `job.json`:

```bash
python3 -c 'import sys; from pathlib import Path; sys.path.insert(0, "scripts"); from template_picker import generate_previews; print(generate_previews(Path("/absolute/temp/template-picker")))'
```

   Use this interaction order:
   - If the ChatCut `ask_followup_questions` tool is available, call it with one `single` field using `variant: visual`. Show the four generated preview images plus `balanced-random` directly in the current chat. When the tool requires preview URLs, serve only the generated preview directory through a temporary loopback HTTP server without opening it in a browser; stop that server after the user submits.
   - Otherwise, show the four preview images in chat with numbered choices and wait for the user's reply.
   - Use the legacy webpage picker only when chat-native selection is unavailable and the user explicitly agrees:

```bash
python3 scripts/template_picker.py \
  --work-dir "/absolute/temp/template-picker" \
  --result "/absolute/temp/template-selection.json" \
  --open-browser
```

Never open the webpage picker without explicit user consent. Never choose a default. For a fixed choice, write that registered template ID to every selected document unless the user requests per-document choices. For `balanced-random`, create a stable seed, call `template_assignment.apply_template_choice`, show the resulting counts, and write every materialized per-document `card_template`. Do not write `balanced-random` as a document template.

6. Create `job.json` exactly as defined in the schema, with explicit `content_mode` and registered `card_template` for every document. In ranking mode, copy only the confirmed candidate without changing order, names, descriptions, or scores. In article mode, derive 3–5 source-grounded key points. Never invent rankings, numbers, or claims. Old jobs without `card_template` must return to the visual picker.
7. Build:

```bash
python3 scripts/build_release.py \
  --job "/absolute/temp/work/job.json" \
  --output "/absolute/confirmed/output"
```

Do not use `--overwrite` unless the user explicitly authorizes replacement.

8. Validate:

```bash
python3 scripts/validate_release.py \
  --job "/absolute/temp/work/job.json" \
  --output "/absolute/confirmed/output"
```

Fix every diagnostic before delivery.
9. Use the documents Skill to render every final DOCX to a temporary QA directory and visually inspect every page PNG. Do not deliver QA files.

## Content decisions

- Apply the detailed grounding, tag, source-preservation, and delivery rules in [references/content_rules.md](references/content_rules.md).
- Generate picker previews and final cards through the same production renderer.
- Ranking hierarchy: `正文` → intro → `本次榜单排名如下：` → real numbered list.
- Article hierarchy: `正文` → intro → `核心要点` → 3–5 real bullet items.

## Delivery contract

- Output count equals source DOCX count.
- Output directory contains final `.docx` files only.
- Each card is 1080×1440.
- Cards are embedded; no separate image folder remains.
- Source files are never modified.
- Existing output files are not overwritten by default.

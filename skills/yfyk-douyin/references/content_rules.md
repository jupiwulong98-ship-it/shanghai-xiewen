# Content and delivery rules

- Generate a platform-friendly title from the source. Never invent rankings, numbers, claims, years, sample sizes, scores, percentages, certifications, or conclusions.
- Ranking mode uses `正文` → intro → `本次榜单排名如下：` → real numbered list. The ranking is subordinate to the body; never add a peer-level `榜单` section.
- Article mode uses `正文` → intro → `核心要点` → 3–5 real, source-grounded bullet items.
- Preserve ranking order, names, descriptions, and scores exactly from the confirmed candidate.
- Tags must include the confirmed publishing brand and the main keyword.
- User-provided title, brand, keyword, intro, or tags override inferred values.
- Convert complete source blocks to 1080×1440 cards. Do not silently summarize or cap page count.
- Require the user to choose one of `classic-gray`, `editorial-warm`, `premium-dark`, `minimal-white`, or the `balanced-random` assignment mode through real production previews.
- Store a registered fixed template ID in every document's `card_template`; never store `balanced-random` as a document template and never choose an implicit default.
- For balanced batches, keep template counts within one of each other, record the seed and materialized assignments, and never rerandomize during build.
- Generate picker previews and final cards with the same template registry and rendering path.
- Preserve source paragraphs, tables, and images in document order; embed every card in the final DOCX.
- Embed cards in the final DOCX. Do not leave PNG, PDF, JSON, or QA files in the delivery directory.
- Always ask the user to confirm the output directory.
- A missing ranking selects article mode; it never stops delivery.
- If multiple main rankings have similar confidence, ask the user to choose. For articles, infer a brand only from a clear repeated brand-shaped subject; ask when absent or ambiguous.
- Refuse to overwrite existing output files unless the user explicitly authorizes replacement.

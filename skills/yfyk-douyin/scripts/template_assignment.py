#!/usr/bin/env python3
from __future__ import annotations

import copy
import random
from collections import Counter
from typing import Any

from card_templates import TEMPLATES

BALANCED_RANDOM = "balanced-random"


def assign_balanced(source_paths: list[str], seed: str) -> dict[str, str]:
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError("seed must be a non-empty string")
    if len(source_paths) != len(set(source_paths)):
        raise ValueError("duplicate source paths are not allowed")
    ordered = sorted(source_paths)
    if not ordered:
        return {}
    rng = random.Random(seed)
    template_ids = sorted(TEMPLATES)
    rng.shuffle(template_ids)
    base, remainder = divmod(len(ordered), len(template_ids))
    pool = template_ids * base + template_ids[:remainder]
    rng.shuffle(pool)
    return dict(zip(ordered, pool))


def apply_template_choice(job: dict[str, Any], choice: str, seed: str | None = None) -> dict[str, Any]:
    if choice not in TEMPLATES and choice != BALANCED_RANDOM:
        raise ValueError(f"unknown template choice: {choice}")
    result = copy.deepcopy(job)
    documents = result.get("documents")
    if not isinstance(documents, list):
        raise ValueError("job documents must be a list")
    source_paths = [document.get("source_path") for document in documents]
    if any(not isinstance(path, str) or not path for path in source_paths):
        raise ValueError("every document requires source_path")
    if choice == BALANCED_RANDOM:
        assignments = assign_balanced(source_paths, seed or "")
        counts = Counter(assignments.values())
        result["template_assignment"] = {
            "mode": BALANCED_RANDOM,
            "seed": seed,
            "counts": {template_id: counts.get(template_id, 0) for template_id in sorted(TEMPLATES)},
        }
        for document in documents:
            document["card_template"] = assignments[document["source_path"]]
    else:
        result["template_assignment"] = {"mode": "fixed", "template": choice}
        for document in documents:
            document["card_template"] = choice
    return result

import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from template_assignment import apply_template_choice, assign_balanced  # noqa: E402


class TemplateAssignmentTests(unittest.TestCase):
    def test_balanced_distribution_sizes(self):
        for size in (1, 2, 4, 5, 50):
            with self.subTest(size=size):
                docs = [f"/tmp/{index:02d}.docx" for index in range(size)]
                result = assign_balanced(docs, seed="stable")
                counts = Counter(result.values())
                all_counts = [counts.get(template, 0) for template in (
                    "classic-gray", "editorial-warm", "premium-dark", "minimal-white"
                )]
                self.assertEqual(len(result), size)
                self.assertLessEqual(max(all_counts) - min(all_counts), 1)
        counts_50 = sorted(Counter(assign_balanced(
            [f"/tmp/{index:02d}.docx" for index in range(50)],
            seed="stable",
        ).values()).values())
        self.assertEqual(counts_50, [12, 12, 13, 13])

    def test_same_seed_is_reproducible_independent_of_input_order(self):
        docs = ["/tmp/b.docx", "/tmp/a.docx", "/tmp/c.docx"]
        self.assertEqual(
            assign_balanced(docs, seed="same"),
            assign_balanced(list(reversed(docs)), seed="same"),
        )

    def test_apply_choice_materializes_templates_without_mutating_input(self):
        job = {
            "version": 1,
            "documents": [
                {"source_path": "/tmp/b.docx"},
                {"source_path": "/tmp/a.docx"},
            ],
        }
        result = apply_template_choice(job, "balanced-random", seed="seed-1")
        self.assertNotIn("card_template", job["documents"][0])
        self.assertEqual(result["template_assignment"]["mode"], "balanced-random")
        self.assertEqual(result["template_assignment"]["seed"], "seed-1")
        self.assertTrue(all(doc["card_template"] for doc in result["documents"]))

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "seed"):
            assign_balanced(["/tmp/a.docx"], seed="")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            assign_balanced(["/tmp/a.docx", "/tmp/a.docx"], seed="x")
        with self.assertRaisesRegex(ValueError, "unknown"):
            apply_template_choice(
                {"version": 1, "documents": [{"source_path": "/tmp/a.docx"}]},
                "wrong",
                seed="x",
            )


if __name__ == "__main__":
    unittest.main()

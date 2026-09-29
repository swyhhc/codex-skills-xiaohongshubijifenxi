#!/usr/bin/env python3
import json
import unittest
from pathlib import Path


CONTRACT = Path(__file__).resolve().parents[1] / "references" / "analysis-contract.json"


class AnalysisContractTests(unittest.TestCase):
    def test_contract_contains_required_model_fields(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        required = set(contract["required"])
        self.assertEqual(
            required,
            {
                "index",
                "comment_focus",
                "cover_ocr",
                "cover_strategy",
                "content_type",
                "commercial_judgment",
                "brand_product",
                "placement",
                "high_read_method",
                "evidence_gap",
            },
        )


if __name__ == "__main__":
    unittest.main()

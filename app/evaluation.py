from __future__ import annotations

import re
from typing import Any

from app.models import EvaluationInput, GroundTruthFinding, ReviewedFinding


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _matches(expected: GroundTruthFinding, observed: ReviewedFinding) -> bool:
    observed_text = _normalize(f"{observed.title} {observed.claim}")
    candidates = [expected.key, expected.title, *expected.aliases]
    return any(_normalize(candidate) in observed_text for candidate in candidates if candidate.strip())


def score_ground_truth(payload: EvaluationInput) -> dict[str, Any]:
    matched_expected: set[str] = set()
    matched_observed: set[int] = set()
    matches: list[dict[str, Any]] = []

    for index, observed in enumerate(payload.observed):
        candidates = [
            expected
            for expected in payload.expected
            if expected.key not in matched_expected and _matches(expected, observed)
        ]
        if not candidates:
            continue
        expected = candidates[0]
        matched_expected.add(expected.key)
        matched_observed.add(index)
        matches.append(
            {
                "expected_key": expected.key,
                "expected_title": expected.title,
                "observed_title": observed.title,
                "observed_confidence": observed.confidence,
            }
        )

    true_positive = len(matches)
    false_positive = len(payload.observed) - len(matched_observed)
    false_negative = len(payload.expected) - len(matched_expected)
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "matches": matches,
        "missed": [
            expected.model_dump(mode="json")
            for expected in payload.expected
            if expected.key not in matched_expected
        ],
        "unmatched_observed": [
            observed.model_dump(mode="json")
            for index, observed in enumerate(payload.observed)
            if index not in matched_observed
        ],
    }

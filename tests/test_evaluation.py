from app.evaluation import score_ground_truth
from app.models import EvaluationInput, GroundTruthFinding, ReviewedFinding


def test_ground_truth_scoring_reports_precision_and_recall() -> None:
    result = score_ground_truth(
        EvaluationInput(
            expected=[
                GroundTruthFinding(
                    key="idor",
                    title="Insecure direct object reference",
                    severity="high",
                    aliases=["broken object level authorization"],
                ),
                GroundTruthFinding(
                    key="stored-xss",
                    title="Stored cross-site scripting",
                    severity="medium",
                    aliases=["persistent xss"],
                ),
            ],
            observed=[
                ReviewedFinding(
                    title="Broken object level authorization in order API",
                    severity="high",
                    confidence=0.95,
                    claim="A user can access another user's order.",
                    evidence="GET /orders/2 returned another account.",
                ),
                ReviewedFinding(
                    title="Missing security header",
                    severity="low",
                    confidence=0.7,
                    claim="The response lacks a header.",
                    evidence="Observed response headers.",
                ),
            ],
        )
    )

    assert result["true_positive"] == 1
    assert result["false_positive"] == 1
    assert result["false_negative"] == 1
    assert result["precision"] == 0.5
    assert result["recall"] == 0.5
    assert result["f1"] == 0.5

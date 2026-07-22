from __future__ import annotations

import argparse
from typing import Any

import httpx


def request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    response = client.request(method, path, json=json)
    if response.status_code != expected_status:
        raise AssertionError(
            f"{method} {path} returned {response.status_code}, "
            f"expected {expected_status}: {response.text}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(f"{method} {path} did not return a JSON object")
    return payload


def run(base_url: str) -> None:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0) as client:
        health = request_json(client, "GET", "/health")
        assert health["status"] == "ok"
        assert health["version"] == "4.0.0"
        assert health["campaign_engine"] is True

        capabilities = request_json(client, "GET", "/api/capabilities")
        assert capabilities["version"] == "4.0.0"
        workflow = set(capabilities["workflow"])
        assert {
            "durable_campaign_graph",
            "distributed_worker_leases",
            "checkpointed_experiments",
            "ground_truth_scoring",
        }.issubset(workflow)
        assert capabilities["workspace"]["public_egress"] is False

        campaign_payload = request_json(
            client,
            "POST",
            "/api/campaigns",
            expected_status=201,
            json={
                "name": "QA campaign",
                "target": "http://juice-shop:3000",
                "objective": "Validate the durable campaign API without invoking a model.",
                "max_parallel": 2,
                "max_experiments": 10,
                "metadata": {"source": "qa-smoke"},
            },
        )
        campaign_id = campaign_payload["campaign"]["id"]

        root_payload = request_json(
            client,
            "POST",
            f"/api/campaigns/{campaign_id}/experiments",
            expected_status=201,
            json={
                "title": "Collect route evidence",
                "kind": "browser",
                "objective": "Collect bounded browser and HTTP evidence from the range target.",
                "required_capabilities": ["browser", "http"],
                "priority": 100,
                "max_attempts": 2,
            },
        )
        root_id = root_payload["experiment"]["id"]
        assert root_payload["experiment"]["status"] == "queued"

        child_payload = request_json(
            client,
            "POST",
            f"/api/campaigns/{campaign_id}/experiments",
            expected_status=201,
            json={
                "title": "Review collected evidence",
                "kind": "validation",
                "objective": "Review the completed root experiment and record a final result.",
                "parent_ids": [root_id],
                "required_capabilities": ["review"],
                "priority": 90,
            },
        )
        child_id = child_payload["experiment"]["id"]
        assert child_payload["experiment"]["status"] == "blocked"

        activated = request_json(
            client,
            "POST",
            f"/api/campaigns/{campaign_id}/activate",
        )
        assert activated["campaign"]["status"] == "active"

        root_lease = request_json(
            client,
            "POST",
            f"/api/campaigns/{campaign_id}/lease",
            json={
                "worker_id": "qa-browser-worker",
                "capabilities": ["browser", "http"],
                "lease_seconds": 120,
            },
        )["experiment"]
        assert root_lease["id"] == root_id
        assert root_lease["status"] == "leased"

        heartbeat = request_json(
            client,
            "POST",
            f"/api/experiments/{root_id}/heartbeat",
            json={
                "worker_id": "qa-browser-worker",
                "lease_seconds": 120,
                "checkpoint": {"phase": "evidence-collected", "pages": 1},
            },
        )["experiment"]
        assert heartbeat["status"] == "running"
        assert heartbeat["checkpoint"]["pages"] == 1

        completed_root = request_json(
            client,
            "POST",
            f"/api/experiments/{root_id}/complete",
            json={
                "worker_id": "qa-browser-worker",
                "checkpoint": {"phase": "complete"},
                "result": {"summary": "Root experiment completed in QA."},
            },
        )["experiment"]
        assert completed_root["status"] == "succeeded"

        child_lease = request_json(
            client,
            "POST",
            f"/api/campaigns/{campaign_id}/lease",
            json={
                "worker_id": "qa-review-worker",
                "capabilities": ["review"],
                "lease_seconds": 120,
            },
        )["experiment"]
        assert child_lease["id"] == child_id

        completed_child = request_json(
            client,
            "POST",
            f"/api/experiments/{child_id}/complete",
            json={
                "worker_id": "qa-review-worker",
                "result": {"summary": "Dependency scheduling verified."},
            },
        )["experiment"]
        assert completed_child["status"] == "succeeded"

        summary = request_json(client, "GET", f"/api/campaigns/{campaign_id}")
        assert summary["campaign"]["status"] == "completed"
        assert summary["experiment_count"] == 2
        assert summary["counts"]["succeeded"] == 2

        graph = request_json(client, "GET", f"/api/campaigns/{campaign_id}/graph")
        assert len(graph["nodes"]) == 2
        assert graph["edges"] == [{"from": root_id, "to": child_id}]

        evaluation = request_json(
            client,
            "POST",
            "/api/evaluations/ground-truth",
            json={
                "expected": [
                    {
                        "key": "missing-csp",
                        "title": "Missing Content Security Policy",
                        "severity": "low",
                        "aliases": ["content security policy"],
                    }
                ],
                "observed": [
                    {
                        "title": "Missing Content Security Policy header",
                        "severity": "low",
                        "confidence": 0.95,
                        "claim": "The response does not contain a Content-Security-Policy header.",
                        "evidence": "Observed response headers from the private range target.",
                        "remediation": "Define and deploy a restrictive CSP.",
                    }
                ],
            },
        )
        assert evaluation["true_positive"] == 1
        assert evaluation["false_positive"] == 0
        assert evaluation["false_negative"] == 0
        assert evaluation["precision"] == 1.0
        assert evaluation["recall"] == 1.0
        assert evaluation["f1"] == 1.0

    print("SecPloit QA smoke test passed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SecPloit control-plane smoke tests.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    run(args.base_url)


if __name__ == "__main__":
    main()

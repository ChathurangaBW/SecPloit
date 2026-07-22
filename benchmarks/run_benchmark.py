from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx


TERMINAL_STATES = {"completed", "failed", "cancelled"}


def load_scenarios(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("Scenario file must contain a non-empty JSON array")
    return data


def run_scenario(
    client: httpx.Client,
    base_url: str,
    scenario: dict[str, Any],
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    started = time.monotonic()
    response = client.post(
        f"{base_url}/api/jobs",
        json={
            "target": scenario["target"],
            "objective": scenario["objective"],
            "max_steps": scenario.get("max_steps", 20),
        },
    )
    response.raise_for_status()
    payload = response.json()
    job = payload["job"]
    job_id = job["id"]

    final_payload: dict[str, Any] | None = None
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status_response = client.get(f"{base_url}/api/jobs/{job_id}")
        status_response.raise_for_status()
        final_payload = status_response.json()
        status = final_payload["job"]["status"]
        if status in TERMINAL_STATES:
            break
        time.sleep(poll_seconds)
    else:
        try:
            client.post(f"{base_url}/api/jobs/{job_id}/cancel").raise_for_status()
        except httpx.HTTPError:
            pass
        return {
            "name": scenario["name"],
            "job_id": job_id,
            "status": "timeout",
            "duration_seconds": round(time.monotonic() - started, 3),
            "error": f"Scenario exceeded {timeout_seconds} seconds",
        }

    assert final_payload is not None
    final_job = final_payload["job"]
    events = final_payload.get("events", [])
    findings = final_payload.get("findings", [])
    report = final_job.get("report") or ""
    command_events = [event for event in events if event.get("kind") == "command_result"]
    specialist_events = [
        event for event in events if event.get("kind") == "specialist_assessment"
    ]
    review_events = [event for event in events if event.get("kind") == "review"]

    return {
        "name": scenario["name"],
        "job_id": job_id,
        "target": scenario["target"],
        "status": final_job["status"],
        "duration_seconds": round(time.monotonic() - started, 3),
        "current_step": final_job.get("current_step", 0),
        "command_count": len(command_events),
        "specialist_count": len(specialist_events),
        "review_count": len(review_events),
        "finding_count": len(findings),
        "report_characters": len(report),
        "has_report": bool(report.strip()),
        "error": final_job.get("error"),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [result for result in results if result.get("status") == "completed"]
    return {
        "scenario_count": len(results),
        "completed_count": len(completed),
        "completion_rate": round(len(completed) / len(results), 3) if results else 0.0,
        "total_findings": sum(int(result.get("finding_count", 0)) for result in results),
        "total_commands": sum(int(result.get("command_count", 0)) for result in results),
        "all_reports_present": all(result.get("has_report", False) for result in completed),
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Run SecPloit against the bundled private cyber-range scenarios."
    )
    root.add_argument("--base-url", default="http://localhost:8000")
    root.add_argument(
        "--scenarios",
        type=Path,
        default=Path(__file__).with_name("scenarios.json"),
    )
    root.add_argument("--output", type=Path, default=Path("benchmark-results.json"))
    root.add_argument("--timeout-seconds", type=int, default=3600)
    root.add_argument("--poll-seconds", type=float, default=2.0)
    return root


def main() -> None:
    args = parser().parse_args()
    scenarios = load_scenarios(args.scenarios)
    base_url = args.base_url.rstrip("/")
    results: list[dict[str, Any]] = []

    with httpx.Client(timeout=30.0) as client:
        for scenario in scenarios:
            print(f"[SecPloit benchmark] starting {scenario['name']}")
            result = run_scenario(
                client=client,
                base_url=base_url,
                scenario=scenario,
                timeout_seconds=max(60, args.timeout_seconds),
                poll_seconds=max(0.2, args.poll_seconds),
            )
            results.append(result)
            print(json.dumps(result, indent=2))

    report = {
        "generated_at_unix": int(time.time()),
        "base_url": base_url,
        "summary": summarize(results),
        "results": results,
    }
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[SecPloit benchmark] wrote {args.output}")


if __name__ == "__main__":
    main()

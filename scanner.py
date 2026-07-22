from __future__ import annotations

import argparse
import json
import time
from typing import Any

import httpx

TERMINAL = {"completed", "failed", "cancelled"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit and follow a SecPloit engagement")
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--target", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--steps", type=int, default=20)
    return parser.parse_args()


def print_event(event: dict[str, Any]) -> None:
    timestamp = event.get("created_at", "")
    kind = event.get("kind", "event")
    message = event.get("message", "")
    print(f"[{timestamp}] {kind}: {message}")
    data = event.get("data")
    if data:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def main() -> None:
    args = parse_args()
    base = args.server.rstrip("/")

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{base}/api/jobs",
            json={
                "target": args.target,
                "objective": args.objective,
                "max_steps": args.steps,
            },
        )
        response.raise_for_status()
        job_id = response.json()["job"]["id"]
        print(f"job={job_id}")

        seen: set[str] = set()
        while True:
            snapshot = client.get(f"{base}/api/jobs/{job_id}")
            snapshot.raise_for_status()
            body = snapshot.json()
            for event in body["events"]:
                if event["id"] not in seen:
                    print_event(event)
                    seen.add(event["id"])

            status = body["job"]["status"]
            if status in TERMINAL:
                if body["job"].get("report"):
                    print("\n=== FINAL REPORT ===\n")
                    print(body["job"]["report"])
                if body["job"].get("error"):
                    print(f"\nERROR: {body['job']['error']}")
                return
            time.sleep(2)


if __name__ == "__main__":
    main()

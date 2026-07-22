from __future__ import annotations

import argparse
import sys

from app.agent import SecurityAgent
from app.config import settings
from app.store import Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an autonomous, evidence-driven security assessment job."
    )
    parser.add_argument("--target", required=True, help="Allowlisted URL, hostname, or IP")
    parser.add_argument("--objective", required=True, help="Assessment objective")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=settings.default_max_steps,
        help=f"Maximum agent steps (1-{settings.max_max_steps})",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if not 1 <= args.max_steps <= settings.max_max_steps:
        print(
            f"--max-steps must be between 1 and {settings.max_max_steps}",
            file=sys.stderr,
        )
        return 2

    store = Store(settings.database_path)
    store.initialize()

    job = store.create_job(
        target=args.target,
        objective=args.objective,
        max_steps=args.max_steps,
    )

    agent = SecurityAgent(store=store)
    agent.run(job.id)

    completed = store.get_job(job.id)
    if completed is None:
        print("Job record disappeared unexpectedly", file=sys.stderr)
        return 1

    if completed.report:
        print(completed.report)

    if completed.error:
        print(f"Error: {completed.error}", file=sys.stderr)

    return 0 if completed.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

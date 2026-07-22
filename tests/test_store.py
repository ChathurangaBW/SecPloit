from __future__ import annotations

from app.models import JobStatus
from app.store import Store


def test_store_job_event_and_finding(tmp_path) -> None:
    store = Store(str(tmp_path / "test.sqlite3"))
    store.initialize()

    job = store.create_job("dvwa", "Assess the authorized test target", 12)
    store.update_job(job.id, status=JobStatus.running, current_step=2)
    store.add_event(job.id, 2, "command_result", "ok", {"exit_code": 0})
    store.add_finding(
        job.id,
        title="Missing response header",
        severity="low",
        confidence=0.91,
        claim="The response omits a defensive header.",
        evidence="curl output",
        remediation="Set the header.",
    )

    loaded = store.get_job(job.id)
    assert loaded is not None
    assert loaded.status == JobStatus.running
    assert loaded.current_step == 2
    assert store.get_events(job.id)[0].data["exit_code"] == 0
    assert store.get_findings(job.id)[0].confidence == 0.91

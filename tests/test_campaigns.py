from __future__ import annotations

from app.campaigns import CampaignService, LeaseConflict
from app.models import (
    CampaignCreate,
    CampaignStatus,
    ExperimentComplete,
    ExperimentCreate,
    ExperimentHeartbeat,
    ExperimentKind,
    ExperimentLeaseRequest,
    ExperimentStatus,
)
from app.store import Store


def service(tmp_path):
    store = Store(str(tmp_path / "campaigns.sqlite3"))
    store.initialize()
    return store, CampaignService(store)


def test_dependency_graph_unlocks_children(tmp_path) -> None:
    store, campaigns = service(tmp_path)
    campaign = campaigns.create_campaign(
        CampaignCreate(
            name="Kernel parser campaign",
            target="dvwa",
            objective="Run a durable graph of authorized research experiments.",
        )
    )
    root = campaigns.add_experiment(
        campaign.id,
        ExperimentCreate(
            title="Build corpus",
            kind=ExperimentKind.fuzzing,
            objective="Create the initial deterministic input corpus.",
            required_capabilities=["fuzzer"],
        ),
    )
    child = campaigns.add_experiment(
        campaign.id,
        ExperimentCreate(
            title="Triage crashes",
            kind=ExperimentKind.analysis,
            objective="Cluster and minimize crashes from the corpus campaign.",
            parent_ids=[root.id],
            required_capabilities=["triage"],
        ),
    )
    assert child.status == ExperimentStatus.blocked

    campaigns.activate(campaign.id)
    leased = campaigns.lease_next(
        campaign.id,
        ExperimentLeaseRequest(
            worker_id="worker-fuzz-1",
            capabilities=["fuzzer"],
            lease_seconds=60,
        ),
    )
    assert leased is not None
    assert leased.id == root.id
    assert leased.status == ExperimentStatus.leased

    campaigns.complete(
        root.id,
        ExperimentComplete(
            worker_id="worker-fuzz-1",
            result={"corpus_files": 42},
            checkpoint={"seed": 17},
        ),
    )
    unlocked = store.get_experiment(child.id)
    assert unlocked is not None
    assert unlocked.status == ExperimentStatus.queued


def test_capability_routing_and_parallel_limit(tmp_path) -> None:
    _, campaigns = service(tmp_path)
    campaign = campaigns.create_campaign(
        CampaignCreate(
            name="Distributed research",
            target="dvwa",
            objective="Route experiments to workers by declared capabilities.",
            max_parallel=1,
        )
    )
    campaigns.add_experiment(
        campaign.id,
        ExperimentCreate(
            title="Browser workflow",
            objective="Capture authenticated workflow evidence.",
            kind=ExperimentKind.browser,
            required_capabilities=["browser"],
            priority=100,
        ),
    )
    campaigns.add_experiment(
        campaign.id,
        ExperimentCreate(
            title="Binary triage",
            objective="Inspect the supplied test binary and mitigations.",
            kind=ExperimentKind.binary,
            required_capabilities=["binary"],
            priority=50,
        ),
    )
    campaigns.activate(campaign.id)

    binary = campaigns.lease_next(
        campaign.id,
        ExperimentLeaseRequest(
            worker_id="worker-binary",
            capabilities=["binary"],
        ),
    )
    assert binary is not None
    assert binary.kind == ExperimentKind.binary

    blocked_by_parallelism = campaigns.lease_next(
        campaign.id,
        ExperimentLeaseRequest(
            worker_id="worker-browser",
            capabilities=["browser"],
        ),
    )
    assert blocked_by_parallelism is None


def test_checkpoint_heartbeat_and_ownership(tmp_path) -> None:
    store, campaigns = service(tmp_path)
    campaign = campaigns.create_campaign(
        CampaignCreate(
            name="Checkpoint test",
            target="dvwa",
            objective="Verify resumable experiment checkpoints and worker ownership.",
        )
    )
    experiment = campaigns.add_experiment(
        campaign.id,
        ExperimentCreate(
            title="Long fuzzing run",
            objective="Persist fuzzing progress across worker heartbeats.",
            kind=ExperimentKind.fuzzing,
        ),
    )
    campaigns.activate(campaign.id)
    campaigns.lease_next(
        campaign.id,
        ExperimentLeaseRequest(worker_id="worker-1", capabilities=[]),
    )

    updated = campaigns.heartbeat(
        experiment.id,
        ExperimentHeartbeat(
            worker_id="worker-1",
            checkpoint={"executions": 100000, "corpus": 88},
        ),
    )
    assert updated.status == ExperimentStatus.running
    assert updated.checkpoint["executions"] == 100000

    try:
        campaigns.heartbeat(
            experiment.id,
            ExperimentHeartbeat(worker_id="other-worker"),
        )
    except LeaseConflict:
        pass
    else:
        raise AssertionError("lease ownership was not enforced")

    stored = store.get_experiment(experiment.id)
    assert stored is not None
    assert stored.lease_owner == "worker-1"


def test_campaign_completes_when_graph_finishes(tmp_path) -> None:
    store, campaigns = service(tmp_path)
    campaign = campaigns.create_campaign(
        CampaignCreate(
            name="Completion test",
            target="dvwa",
            objective="Complete a one-node durable research campaign.",
        )
    )
    experiment = campaigns.add_experiment(
        campaign.id,
        ExperimentCreate(
            title="Validate target",
            objective="Produce one reproducible validation result.",
        ),
    )
    campaigns.activate(campaign.id)
    campaigns.lease_next(
        campaign.id,
        ExperimentLeaseRequest(worker_id="worker-1"),
    )
    campaigns.complete(
        experiment.id,
        ExperimentComplete(worker_id="worker-1", result={"verified": True}),
    )
    completed = store.get_campaign(campaign.id)
    assert completed is not None
    assert completed.status == CampaignStatus.completed

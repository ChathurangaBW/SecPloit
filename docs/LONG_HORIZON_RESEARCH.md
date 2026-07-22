# Long-horizon research engine

SecPloit v4 introduces a durable campaign control plane for research that cannot be represented as a single linear agent transcript.

## Core entities

### Campaign

A campaign owns the target, objective, parallelism budget, experiment budget, metadata, and lifecycle state.

### Experiment

An experiment is an independently schedulable research unit with:

- a research kind;
- an objective and hypothesis;
- dependency experiment IDs;
- required worker capabilities;
- priority;
- retry budget;
- lease owner and expiry;
- resumable checkpoint;
- payload, result, and error state.

## State machine

```text
blocked -> queued -> leased -> running -> succeeded
                    |          |
                    |          +-> queued (retry)
                    +------------> failed
```

A dependency failure cancels blocked descendants. Successful parents unlock their queued children. When every node is terminal, the campaign becomes completed or failed.

## Worker protocol

Workers do not need access to the SecPloit database.

1. Request a lease with a worker ID and declared capabilities.
2. Execute only the leased experiment in its assigned research environment.
3. Send periodic heartbeat checkpoints.
4. Complete the experiment with structured results, or fail it with a retryable flag.
5. Request another lease.

The scheduler enforces `max_parallel`, capability matching, priority ordering, lease ownership, retry budgets, and lease-expiry recovery.

## Research mappings

The graph is deliberately backend-neutral. Worker capabilities can represent:

| Research domain | Example capabilities |
|---|---|
| Browser application | `browser`, `http`, `proxy` |
| Source analysis | `source`, `semgrep`, `codeql` |
| Native binary | `binary`, `gdb`, `asan`, `fuzzer` |
| Kernel laboratory | `vm`, `kernel`, `kasan`, `kcov`, `syzkaller` |
| Browser engine | `chromium-build`, `asan`, `libfuzzer` |
| Race research | `race`, `scheduler-control`, `tsan` |
| Cloud laboratory | `terraform`, `aws`, `azure`, `gcp`, `kubernetes` |
| Hardware laboratory | `serial`, `jtag`, `power-control`, `firmware` |

SecPloit v4 implements the control plane and worker protocol. Domain-specific VM, cloud, browser-engine, and hardware workers can be added without changing campaign storage or scheduling semantics.

## Ground-truth evaluation

Operational metrics such as command count and report presence do not measure vulnerability-discovery quality. The evaluation endpoint compares reviewed findings with known target findings and returns:

- true positives;
- false positives;
- false negatives;
- precision;
- recall;
- F1;
- matched records;
- missed vulnerabilities;
- unmatched observations.

Use stable finding keys and domain-specific aliases in benchmark datasets. Treat text matching as a baseline; future evaluators can add CWE, endpoint, evidence, exploitability, and patch-validation matching.

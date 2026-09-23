# Ax Scheduler

## Ax Scheduler Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    participant BE as W&B backend
    participant GO as Go scheduler<br/>(wandb-core)
    participant PY as Python scheduler client<br/>(bridge, inferred)
    participant AO as AxOptimizer
    participant AX as Ax Client

    rect rgba(59,130,246,0.15)
    note over GO,AX: Warm start: adopt runs the sweep already has
    GO->>BE: poll sweep runs
    GO->>PY: warm-start task (existing runs)
    PY->>AO: tell_existing_finished_run(run)
    AO->>AX: attach_trial → complete_trial / mark_trial_failed
    PY->>AO: tell_existing_active_run(run)
    AO->>AX: attach_trial (left running)
    AO-->>PY: trial_index → optimizer run id
    PY-->>GO: warm-start result
    end

    loop Each generation
        rect rgba(34,197,94,0.15)
        GO->>BE: poll tracked runs (states, metrics)
        GO->>PY: generation task {Updates, AskUpTo}
        loop each run update (inferred)
            PY->>AO: tell_run(id, data)
            AO->>AX: attach_data (alive) / complete_trial / mark_trial_failed
        end
        PY->>AO: prune_run(id, data) for running runs (inferred)
        AO->>AX: should_stop_trial_early → mark_trial_early_stopped
        PY->>AO: should_terminate_sweep() (inferred)
        PY->>AO: ask_n_runs(AskUpTo)
        AO->>AX: get_next_trials(max_trials)
        AO-->>PY: suggestions / None / []
        PY-->>GO: generation result {Suggestions, Prune, AskOutcome}
        end

        alt SUGGESTED (#12891)
            GO->>BE: FetchSweep (re-check state)
            GO->>BE: EnqueueRun per suggestion
            BE-->>GO: minted run name → tracked InFlight
        else EXHAUSTED ([] from ask)
            GO->>GO: stop asking, drain in-flight runs, then finish sweep
        else declined (None from ask)
            GO->>GO: wait, ask again next poll
        end
        note over GO: Stopping pruned runs lands in a later slice
    end

    rect rgba(239,68,68,0.15)
    note over GO,AX: Shutdown
    GO->>PY: Done task {Reason, DiscardedOptimizerRunIds}
    PY->>AO: forget_run(id) per discarded id (#12892, inferred)
    AO->>AX: mark_trial_failed
    end
```

## `ask_n_runs(n)`
```mermaid
flowchart TD
    classDef local fill:#2563eb,stroke:#93c5fd,color:#fff
    classDef base fill:#b45309,stroke:#fcd34d,color:#fff
    classDef ax fill:#15803d,stroke:#86efac,color:#fff
    classDef flow fill:#475569,stroke:#cbd5e1,color:#fff

    ASK[ask_n_runs]:::local --> GNT(["client.get_next_trials(max_trials=n)"]):::ax
    GNT -->|trials| RC[["RunConfig.from_values"]]:::base
    RC --> RS[["RunSuggestion(run_id=str(trial_index))"]]:::base
    RS --> R1("return suggestions"):::flow
    GNT -->|DataRequiredError /<br/>MaxParallelismReachedException| R2("return None: declined"):::flow
    GNT -->|OptimizationComplete| R3("return []: exhausted"):::flow
    GNT -->|other exception| R4("propagates"):::flow
```

## `tell_run(run_id, data)`
```mermaid
flowchart TD
    classDef local fill:#2563eb,stroke:#93c5fd,color:#fff
    classDef base fill:#b45309,stroke:#fcd34d,color:#fff
    classDef ax fill:#15803d,stroke:#86efac,color:#fff
    classDef flow fill:#475569,stroke:#cbd5e1,color:#fff

    TR[tell_run]:::local --> F{"trial in<br/>_finalized?"}:::flow
    F -->|yes| NOOP("return"):::flow
    F -->|no| S{"data.state"}:::flow

    S -->|is_alive| H{"history_metrics?"}:::flow
    H -->|empty| NOOP
    H -->|last row| OV1[["objective_values(row)"]]:::base
    OV1 -->|None| NOOP
    OV1 -->|values| RD1[_raw_data]:::local
    RD1 --> AD(["client.attach_data(progression=row['_step'])"]):::ax
    AD -->|any exception swallowed| NOOP

    S -->|FINISHED| OV2[["objective_values(summary)"]]:::base
    OV2 -->|values| RD2[_raw_data]:::local
    RD2 --> CT(["client.complete_trial"]):::ax
    OV2 -->|None| MTF(["client.mark_trial_failed"]):::ax
    S -->|FAILED / CRASHED /<br/>KILLED / PREEMPTED| MTF

    CT --> ADD("add to _finalized"):::flow
    MTF --> ADD
```
The alive branch is _attach_latest_progression, inlined. _raw_data zips the base class's metric_names() with the objective values.

## `forget_run(run_id)`
```mermaid
flowchart TD
    classDef local fill:#2563eb,stroke:#93c5fd,color:#fff
    classDef ax fill:#15803d,stroke:#86efac,color:#fff
    classDef flow fill:#475569,stroke:#cbd5e1,color:#fff

    FR[forget_run]:::local --> F{"trial in<br/>_finalized?"}:::flow
    F -->|yes| NOOP("return"):::flow
    F -->|no| ADD("add to _finalized"):::flow
    ADD --> MTF(["client.mark_trial_failed"]):::ax
```

## `prune_run(run_id, data)`
```mermaid
flowchart TD
    classDef local fill:#2563eb,stroke:#93c5fd,color:#fff
    classDef ax fill:#15803d,stroke:#86efac,color:#fff
    classDef flow fill:#475569,stroke:#cbd5e1,color:#fff

    PR[prune_run]:::local --> F{"trial in<br/>_finalized?"}:::flow
    F -->|yes| NO("return False"):::flow
    F -->|no| SS(["client.should_stop_trial_early"]):::ax
    SS -->|False, or any exception| NO
    SS -->|True| ADD("add to _finalized"):::flow
    ADD --> MES(["client.mark_trial_early_stopped"]):::ax
    MES --> YES("return True"):::flow
```

## `tell_existing_finished_run(data)` (warm start)
```mermaid
flowchart TD
    classDef local fill:#2563eb,stroke:#93c5fd,color:#fff
    classDef base fill:#b45309,stroke:#fcd34d,color:#fff
    classDef ax fill:#15803d,stroke:#86efac,color:#fff
    classDef flow fill:#475569,stroke:#cbd5e1,color:#fff

    TEF[tell_existing_finished_run]:::local --> T[["is_terminal_state"]]:::base
    T -->|not terminal| SKIP("return: skipped"):::flow
    T -->|terminal| FIN{"FINISHED?"}:::flow
    FIN -->|yes| OV[["objective_values(summary)"]]:::base
    OV -->|None| SKIP
    OV -->|values| SSP
    FIN -->|no| SSP[_search_space_params]:::local
    SSP --> EXP[_experiment]:::local
    EXP --> P{"config has every<br/>search-space param?"}:::flow
    P -->|no| SKIP
    P -->|yes| PT(["cast via parameter.python_type"]):::ax
    PT --> AT(["client.attach_trial"]):::ax
    AT --> TR["tell_run(trial_index, data)<br/>see diagram 2"]:::local
```

## `tell_existing_active_run(data)` (adopt an in-flight run)
```mermaid
flowchart TD
    classDef local fill:#2563eb,stroke:#93c5fd,color:#fff
    classDef ax fill:#15803d,stroke:#86efac,color:#fff
    classDef flow fill:#475569,stroke:#cbd5e1,color:#fff

    TEA[tell_existing_active_run]:::local --> SSP[_search_space_params]:::local
    SSP --> EXP[_experiment]:::local
    EXP --> P{"config has every<br/>search-space param?"}:::flow
    P -->|no| NONE("return None"):::flow
    P -->|yes| PT(["cast via parameter.python_type"]):::ax
    PT --> AT(["client.attach_trial"]):::ax
    AT --> RET("return trial_index (int)<br/>trial left running"):::flow
```

## `should_terminate_sweep()`
```mermaid
flowchart TD
    classDef local fill:#2563eb,stroke:#93c5fd,color:#fff
    classDef base fill:#b45309,stroke:#fcd34d,color:#fff
    classDef flow fill:#475569,stroke:#cbd5e1,color:#fff

    STS[should_terminate_sweep]:::local --> T{"_terminator set?"}:::flow
    T -->|no| NO("return False"):::flow
    T -->|yes| CALL[["terminator(client)"]]:::base
    CALL --> RET("return its result"):::flow
```

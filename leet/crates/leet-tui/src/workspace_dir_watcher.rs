//! Port of `core/internal/leet/workspacedirwatcher.go` — the on-thread
//! (update-loop) half: the 5s wandb-dir poll arming and the bounded FIFO
//! run-overview preloader (CONCURRENCY.md B4).
//!
//! The off-thread command bodies live in the runtime (§2.7 effect threads):
//! [`crate::runtime::scan_wandb_run_dirs`] / `parse_run_dir_timestamp` (the
//! `tea.Tick` callback body incl. the run-dir sorting,
//! workspacedirwatcher.go:105-108, 111-165), and
//! [`crate::runtime::preload_run_overview`] / `find_run_msg` with the
//! `maxRecordsToScan` constants (workspacedirwatcher.go:19-31, 225-276).
//! The `Workspace` message handlers wiring these together —
//! `handleWorkspaceRunDirs`, `enqueueMissingRunOverviews`,
//! `startRunOverviewPreloadsCmd`, `handleWorkspaceRunOverviewPreloaded`,
//! `applyRunKeys` and friends (workspacedirwatcher.go:168-222, 277-403) —
//! port with workspace_handlers.rs (Phase 5b).

use std::collections::{HashSet, VecDeque};
use std::time::Duration;

use crate::command::Command;

// TODO: make this configurable. (workspacedirwatcher.go:16-17)
pub const WANDB_DIR_POLL_INTERVAL: Duration = Duration::from_secs(5);

/// maxConcurrentPreloads limits the number of concurrent run record preloads
/// (workspacedirwatcher.go:28).
pub const MAX_CONCURRENT_PRELOADS: usize = 4;

/// Port of `Workspace.pollWandbDirCmd` (workspacedirwatcher.go:100-109):
/// arm the dir-poll timer; on fire the runtime scans the wandb dir on an
/// effect thread (the Go tick callback body) and delivers
/// `Event::WorkspaceRunDirs`.
///
/// A free function where Go has a method — the closure captures only
/// `w.wandbDir` (workspacedirwatcher.go:101); the Workspace port passes its
/// dir.
// PARITY: Go clamps a negative delay to 0 (workspacedirwatcher.go:102-104);
// `Duration` is unsigned, so the clamp is inherent at every call site.
pub fn poll_wandb_dir_cmd(wandb_dir: &str, delay: Duration) -> Command {
    Command::PollWandbDir {
        wandb_dir: wandb_dir.to_string(),
        delay,
    }
}

/// runOverviewPreloader implements a bounded-concurrency FIFO queue with
/// dedupe (workspacedirwatcher.go:33-98).
///
/// LOCK-FREE in Go and here (B4): state is owned by the update thread;
/// concurrency is achieved by counting in-flight
/// `Command::PreloadRunOverview`s — the workspace issues one per key
/// returned by [`dequeue_startable`], each running on its own effect thread,
/// and calls [`mark_done`] + [`dequeue_startable`] again per
/// `WorkspaceRunOverviewPreloaded` result, keeping at most
/// [`MAX_CONCURRENT_PRELOADS`] in flight.
///
/// [`dequeue_startable`]: RunOverviewPreloader::dequeue_startable
/// [`mark_done`]: RunOverviewPreloader::mark_done
#[derive(Debug)]
pub struct RunOverviewPreloader {
    /// queued or in-flight
    pending: HashSet<String>,
    in_flight: HashSet<String>,
    /// FIFO of queued (not in-flight)
    queue: VecDeque<String>,
    max_in_flight: usize,
}

impl RunOverviewPreloader {
    /// `newRunOverviewPreloader` (workspacedirwatcher.go:41-50).
    // PARITY: Go coerces maxInFlight <= 0 to 1; usize cannot be negative,
    // so only the 0 case remains.
    pub fn new(max_in_flight: usize) -> RunOverviewPreloader {
        RunOverviewPreloader {
            pending: HashSet::new(),
            in_flight: HashSet::new(),
            queue: VecDeque::new(),
            max_in_flight: max_in_flight.max(1),
        }
    }

    /// `Enqueue` (workspacedirwatcher.go:52-61): queues a key unless empty
    /// or already queued/in-flight.
    pub fn enqueue(&mut self, run_key: &str) {
        if run_key.is_empty() {
            return;
        }
        if self.pending.contains(run_key) {
            return;
        }
        self.pending.insert(run_key.to_string());
        self.queue.push_back(run_key.to_string());
    }

    /// `DropQueuedNotPresent` (workspacedirwatcher.go:63-76): drops queued
    /// (not in-flight) keys that vanished from the directory, preserving
    /// FIFO order of the kept ones (Go filters in place via `queue[:0]`).
    pub fn drop_queued_not_present(&mut self, present: &HashSet<String>) {
        if self.queue.is_empty() {
            return;
        }
        let pending = &mut self.pending;
        self.queue.retain(|key| {
            if present.contains(key) {
                true
            } else {
                pending.remove(key);
                false
            }
        });
    }

    /// `DequeueStartable` (workspacedirwatcher.go:78-93): moves up to
    /// `max_in_flight - in_flight` queued keys into the in-flight set and
    /// returns them, FIFO.
    pub fn dequeue_startable(&mut self) -> Vec<String> {
        let available = self.max_in_flight.saturating_sub(self.in_flight.len());
        if available == 0 || self.queue.is_empty() {
            return Vec::new();
        }
        let n = available.min(self.queue.len());

        let mut keys = Vec::with_capacity(n);
        for _ in 0..n {
            let Some(run_key) = self.queue.pop_front() else {
                break; // unreachable: n <= queue.len()
            };
            self.in_flight.insert(run_key.clone());
            keys.push(run_key);
        }
        keys
    }

    /// `MarkDone` (workspacedirwatcher.go:95-98).
    pub fn mark_done(&mut self, run_key: &str) {
        self.in_flight.remove(run_key);
        self.pending.remove(run_key);
    }

    /// testhelpers.go `TestRunOverviewPreloadsInFlight`.
    pub fn in_flight_len(&self) -> usize {
        self.in_flight.len()
    }

    /// testhelpers.go `TestRunOverviewPreloadQueueLen`.
    pub fn queue_len(&self) -> usize {
        self.queue.len()
    }
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::{Path, PathBuf};

    use leet_data::history_source::{self as hs, SourceMsg};
    use leet_proto::wandb_internal::{Record, RunRecord, record};
    use leet_wire::transaction_log;
    use pretty_assertions::assert_eq;

    use super::*;
    use crate::command::Command;
    use crate::runtime::{find_run_msg, preload_run_overview};

    // TODO(phase-5b) — deferred Go test halves; this checklist is the
    // coverage debt workspace_handlers.rs must retire, one item per named
    // Go test (workspacedirwatcher_test.go /
    // workspacedirwatcher_preload_test.go):
    //   - TestWorkspace_PinSelectsAndPinsWhenNotSelected (ENTIRE test):
    //     Workspace.Update key handling — auto-select/pin on
    //     WorkspaceRunDirsMsg.
    //   - TestWorkspace_SelectAndPinRuns_StateTransitions (ENTIRE test).
    //   - TestWorkspace_RunOverviewPreloads_BoundedConcurrency (Update
    //     wiring half): one WorkspaceRunDirsMsg through
    //     handleWorkspaceRunDirs actually yields inFlight=4 / queue=3;
    //     the queue mechanics it delegates to port below.
    //   - TestWorkspace_PreloadRunOverview_ExtractsRunRecord
    //     (overview-population half): Update(msg) populates the overview
    //     (TestGetRunOverviewByRunKey assertions).
    //   - TestWorkspace_PreloadRunOverview_AllRunsPopulated
    //     (overview-population half), incl.
    //     handleWorkspaceRunOverviewPreloaded's logging suppression for
    //     errRunRecordNotFound / os.IsNotExist errors
    //     (workspacedirwatcher.go:277-302).
    // The remaining tests of those files port below.

    /// Go: createRunWandbFile (workspacedirwatcher_test.go:17-34). The run
    /// id is the run-key suffix after the timestamp; Go extracts it via
    /// `extractRunID` (model.go:441 — ports with model.rs).
    fn create_run_wandb_file(wandb_dir: &Path, run_key: &str, records: &[Record]) -> PathBuf {
        let run_id = run_key.rsplit('-').next().expect("run key has an id");
        assert!(
            !run_id.is_empty(),
            "could not extract run ID from {run_key:?}"
        );

        let run_dir = wandb_dir.join(run_key);
        fs::create_dir_all(&run_dir).unwrap();

        let wandb_file = run_dir.join(format!("run-{run_id}.wandb"));
        let mut w = transaction_log::open_writer(&wandb_file).unwrap();
        for rec in records {
            w.write(rec).unwrap();
        }
        w.close().unwrap();
        wandb_file
    }

    fn run_record(run_id: &str, display_name: &str, project: &str) -> Record {
        Record {
            record_type: Some(record::RecordType::Run(RunRecord {
                run_id: run_id.to_string(),
                display_name: display_name.to_string(),
                project: project.to_string(),
                ..Default::default()
            })),
            ..Default::default()
        }
    }

    /// ADAPTED(TestWorkspace_RunOverviewPreloads_BoundedConcurrency): Go
    /// drives Workspace.Update with WorkspaceRunDirsMsg /
    /// WorkspaceRunOverviewPreloadedMsg; those handlers port with
    /// workspace_handlers.rs (Phase 5b). This exercises the same queue
    /// mechanics they delegate to — handleWorkspaceRunDirs ⇒ Enqueue +
    /// DequeueStartable (workspacedirwatcher.go:186-192, 208-218);
    /// handleWorkspaceRunOverviewPreloaded ⇒ MarkDone + DequeueStartable
    /// ("keep draining the queue", workspacedirwatcher.go:277-302) — with
    /// the Go test's exact keys and assertions.
    #[test]
    fn workspace_run_overview_preloads_bounded_concurrency() {
        let run_keys = [
            "run-20250731_170606-a1aaaaaa",
            "run-20250731_170607-b2bbbbbb",
            "run-20250731_170608-c3cccccc",
            "run-20250731_170609-d4dddddd",
            "run-20250731_170610-e5eeeeee",
            "run-20250731_170611-f6ffffff",
            "run-20250731_170612-g7gggggg",
        ];

        let mut preloader = RunOverviewPreloader::new(MAX_CONCURRENT_PRELOADS);

        // Seeds queue and starts up to maxConcurrentPreloads immediately.
        for run_key in run_keys {
            preloader.enqueue(run_key);
        }
        let started = preloader.dequeue_startable();
        assert_eq!(started, run_keys[..4].to_vec()); // FIFO

        assert_eq!(preloader.in_flight_len(), 4);
        assert_eq!(preloader.queue_len(), 3);

        // Simulate completions in FIFO order; inFlight should stay at 4
        // until fewer remain.
        for (i, run_key) in run_keys.iter().enumerate() {
            preloader.mark_done(run_key);
            let _ = preloader.dequeue_startable(); // keep draining the queue

            let remaining = run_keys.len() - (i + 1);
            let want_in_flight = remaining.min(4);
            assert_eq!(preloader.in_flight_len(), want_in_flight);
        }

        assert_eq!(preloader.queue_len(), 0);
        assert_eq!(preloader.in_flight_len(), 0);
    }

    /// Dedupe and drop semantics of the queue (workspacedirwatcher.go:52-76):
    /// empty keys and re-enqueues are ignored; keys that vanish from the
    /// directory are dropped from the queue (in-flight ones are not — they
    /// are not queued).
    #[test]
    fn preloader_dedupes_and_drops_missing() {
        let mut preloader = RunOverviewPreloader::new(2);
        preloader.enqueue("");
        preloader.enqueue("run-a");
        preloader.enqueue("run-a"); // dedupe: queued
        preloader.enqueue("run-b");
        preloader.enqueue("run-c");
        assert_eq!(preloader.queue_len(), 3);

        let started = preloader.dequeue_startable();
        assert_eq!(started, vec!["run-a".to_string(), "run-b".to_string()]);
        preloader.enqueue("run-a"); // dedupe: in-flight is still pending
        assert_eq!(preloader.queue_len(), 1);

        // run-c vanished; run-a is in flight and unaffected.
        let present: HashSet<String> = ["run-a", "run-b"].map(String::from).into();
        preloader.drop_queued_not_present(&present);
        assert_eq!(preloader.queue_len(), 0);
        assert_eq!(preloader.in_flight_len(), 2);

        // Dropped keys can be re-enqueued (pending was cleared).
        preloader.enqueue("run-c");
        assert_eq!(preloader.queue_len(), 1);

        // PARITY: Go coerces maxInFlight <= 0 to 1.
        let mut one = RunOverviewPreloader::new(0);
        one.enqueue("run-a");
        one.enqueue("run-b");
        assert_eq!(one.dequeue_startable(), vec!["run-a".to_string()]);
    }

    /// pollWandbDirCmd arms the runtime's dir-poll timer with the captured
    /// dir (workspacedirwatcher.go:100-109).
    #[test]
    fn poll_wandb_dir_cmd_arms_dir_poll() {
        let cmd = poll_wandb_dir_cmd("/tmp/wandb", WANDB_DIR_POLL_INTERVAL);
        let Command::PollWandbDir { wandb_dir, delay } = cmd else {
            panic!("expected PollWandbDir, got {cmd:?}");
        };
        assert_eq!(wandb_dir, "/tmp/wandb");
        assert_eq!(delay, Duration::from_secs(5));
    }

    /// ADAPTED(TestWorkspace_PreloadRunOverview_ExtractsRunRecord): Go
    /// resolves the path via Workspace.preloadRunOverviewCmd (runWandbFile,
    /// model.go:450) and then feeds the msg to Workspace.Update to populate
    /// the RunOverview — both Phase 5b. Here the preload command body
    /// itself (runtime::preload_run_overview) is exercised against a real
    /// .wandb file, with the Go test's field assertions.
    #[test]
    fn workspace_preload_run_overview_extracts_run_record() {
        let wandb_dir = tempfile::tempdir().unwrap();

        let run_id = "iazb7i1k";
        let run_key = format!("run-20250731_170606-{run_id}");
        let wandb_file = create_run_wandb_file(
            wandb_dir.path(),
            &run_key,
            &[run_record(run_id, "test-run", "test-project")],
        );

        let msg = preload_run_overview(&run_key, wandb_file.to_str().unwrap());

        assert_eq!(msg.run_key, run_key);
        assert_eq!(msg.err, None);
        let run = msg.run.expect("preload returned a Run");
        assert_eq!(run.id, run_id);
        assert_eq!(run.display_name, "test-run");
        assert_eq!(run.project, "test-project");
    }

    /// ADAPTED(TestWorkspace_PreloadRunOverview_AllRunsPopulated): as above,
    /// per-run preloads against real files; the overview-population half
    /// (Workspace.Update) lands with workspace_handlers.rs.
    #[test]
    fn workspace_preload_run_overview_all_runs_populated() {
        let wandb_dir = tempfile::tempdir().unwrap();

        let runs = [
            (
                "run-20250731_170606-aaaaaaaa",
                "aaaaaaaa",
                "run-alpha",
                "proj-1",
            ),
            (
                "run-20250731_170607-bbbbbbbb",
                "bbbbbbbb",
                "run-beta",
                "proj-1",
            ),
            (
                "run-20250731_170608-cccccccc",
                "cccccccc",
                "run-gamma",
                "proj-2",
            ),
        ];

        for (key, id, display, project) in runs {
            create_run_wandb_file(wandb_dir.path(), key, &[run_record(id, display, project)]);
        }

        for (key, id, display, project) in runs {
            let run_id = key.rsplit('-').next().unwrap();
            let wandb_file = wandb_dir
                .path()
                .join(key)
                .join(format!("run-{run_id}.wandb"));

            let msg = preload_run_overview(key, wandb_file.to_str().unwrap());

            assert_eq!(msg.err, None, "preload failed for {key}");
            let run = msg.run.unwrap_or_else(|| panic!("nil Run for {key}"));
            assert_eq!(run.id, id, "overview ID mismatch for {key}");
            assert_eq!(run.display_name, display, "display name mismatch for {key}");
            assert_eq!(run.project, project, "project mismatch for {key}");
        }
    }

    /// Go: TestFindRunMsg (workspacedirwatcher_preload_test.go).
    ///
    /// ADAPTED: the Go "batched records" case has no counterpart —
    /// `HistorySource.Read` never returns a BatchedRecordsMsg, so
    /// `SourceMsg` has no such variant (see the PARITY note on
    /// `runtime::find_run_msg`).
    #[test]
    fn find_run_msg_table() {
        let want = || hs::RunMsg {
            id: "run-123".into(),
            display_name: "demo".into(),
            ..Default::default()
        };

        let cases: Vec<(&str, SourceMsg, Option<hs::RunMsg>)> = vec![
            ("direct run message", SourceMsg::Run(want()), Some(want())),
            (
                "chunked batch",
                SourceMsg::ChunkedBatch(hs::ChunkedBatchMsg {
                    msgs: vec![
                        SourceMsg::Summary(hs::SummaryMsg::default()),
                        SourceMsg::Run(want()),
                    ],
                    ..Default::default()
                }),
                Some(want()),
            ),
            (
                "run without id is ignored",
                SourceMsg::ChunkedBatch(hs::ChunkedBatchMsg {
                    msgs: vec![SourceMsg::Run(hs::RunMsg {
                        display_name: "missing-id".into(),
                        ..Default::default()
                    })],
                    ..Default::default()
                }),
                None,
            ),
            (
                "no run message",
                SourceMsg::ChunkedBatch(hs::ChunkedBatchMsg {
                    msgs: vec![
                        SourceMsg::Summary(hs::SummaryMsg::default()),
                        SourceMsg::ConsoleLog(hs::ConsoleLogMsg::default()),
                    ],
                    ..Default::default()
                }),
                None,
            ),
        ];

        for (name, msg, want) in cases {
            assert_eq!(find_run_msg(msg), want, "{name}");
        }
    }
}

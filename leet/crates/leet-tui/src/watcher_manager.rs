//! Port of `core/internal/leet/watchermanager.go` plus the polling semantics
//! of `core/internal/watcher` (docs/CONCURRENCY.md §1.7): file watching for
//! live runs.
//!
//! Go wraps `radovskyb/watcher` — an mtime poller (500ms default,
//! core/internal/watcher/impl.go:29) running two goroutines per watcher
//! instance, one instance per `WatcherManager` (watchermanager.go:25). The
//! port keeps the polling semantics verbatim — mtime+size compare per
//! registered path every 500ms, NO notify crate — on ONE process-wide
//! watcher thread (§2.3): registrations arrive over its command channel,
//! each carrying the notify side of that registration's cap-1 channel
//! ([`WatchReceiver::channel`]).
//!
//! Delivery (§2.5): on change the poller `try_send`s `()` and drops the
//! notification when the slot is full — Go's `select`+`default` drop into
//! the manager's out chan (watchermanager.go:42-47); a burst of changes
//! coalesces to one notification (C3; cap-1 is observably equivalent to the
//! single-run mode's cap-4096 chan because every read drains all available
//! data). Go's blocking `WaitForMsg` pump (watchermanager.go:83-90) is
//! [`crate::command::Command::AwaitWatcherMsg`] /
//! [`crate::command::Command::AwaitWorkspaceWatcher`] doing ONE `recv` on
//! the [`WatchReceiver`]; unregistering drops the notify sender, so a
//! pending pump sees `Err(Disconnected)` and exits silently — replacing the
//! C4 nil-send handshake (watchermanager.go:70-74). No nil events exist.
//!
//! Caveats ported as-is (§1.7):
//!
//!   - Write and Create are indistinguishable (impl.go:93-99 upstream race);
//!     both notify.
//!   - A file modified rapidly enough that mtime AND size are unchanged
//!     emits nothing — there is NO guarantee the final change to a file is
//!     observed (core/internal/watcher/watcher.go:12-24).
//!   - Remove events are filtered out (`FilterOps(Write, Create)`,
//!     impl.go:99), but deletion of a watched file is handled UPSTREAM of
//!     the filter: the delegate's poll cycle stats the path, hits
//!     `os.IsNotExist`, pushes `ErrWatchedFileDeleted` on its Error channel
//!     (leet logs it via `logger.CaptureError`, impl.go:161-166) and
//!     permanently unwatches the path (radovskyb/watcher@v1.0.7
//!     `retrieveFileList` → `w.Remove(name)` drops it from `w.names` and
//!     `w.files`). A deleted file therefore NEVER notifies again — even
//!     after recreation — and the run falls back to heartbeat-driven reads
//!     for the rest of the session; the `WatcherManager` still reports
//!     started (delegate errors never feed back into its state). Ported:
//!     on a NotFound stat the poller logs the CaptureError-equivalent and
//!     drops the registration; the dropped notify sender makes a pending
//!     pump exit silently. A non-NotFound stat error is logged and the
//!     path stays registered; a later successful stat is a Create, which
//!     passes the filter and notifies — mirroring the delegate, where the
//!     erroring path drops out of one cycle's snapshot and reappears as
//!     Create on recovery.
//!
//! `WatchDir` (core/internal/watcher/watcher.go:24-31) has no leet caller
//! and is not ported.

use std::collections::HashMap;
use std::fmt;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender, SyncSender, TrySendError};
use std::thread;
use std::time::{Duration, Instant, SystemTime};

use crate::command::WatchReceiver;

/// The default polling period (core/internal/watcher/impl.go:29). leet never
/// overrides it (`watcher.Params.PollingPeriod` is only set by the watcher
/// package's own tests).
pub const POLLING_PERIOD: Duration = Duration::from_millis(500);

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/// Errors from [`WatcherManager::start`] (Go: the `error` returned by
/// `watcher.Watch`, logged and propagated at watchermanager.go:50-53). The
/// texts are log-only — no handler matches them.
#[derive(Debug)]
pub enum WatchError {
    /// The file must exist, or an error is returned
    /// (core/internal/watcher/watcher.go:21-22; the poller's `Add` stats the
    /// path and surfaces the `*os.PathError`).
    Stat { path: String, source: io::Error },
    /// Go: `fmt.Errorf("watcher: tried to call Watch() after Finish()")`
    /// (impl.go:54).
    Finished,
}

impl fmt::Display for WatchError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            // Mirrors Go's *os.PathError shape ("stat <path>: <reason>");
            // the io::Error reason text differs from errno strings, which is
            // fine — the message is log-only.
            WatchError::Stat { path, source } => write!(f, "stat {path}: {source}"),
            WatchError::Finished => f.write_str("watcher: tried to call Watch() after Finish()"),
        }
    }
}

impl std::error::Error for WatchError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            WatchError::Stat { source, .. } => Some(source),
            WatchError::Finished => None,
        }
    }
}

// ---------------------------------------------------------------------------
// The watcher thread (CONCURRENCY.md §2.3 singleton; §1.7 semantics)
// ---------------------------------------------------------------------------

/// What the poller compares per registered path each cycle: the Go delegate
/// keys change detection off `os.FileInfo` (mtime + size cover every change
/// leet cares about — appends to a `.wandb` transaction log).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct FileState {
    mtime: SystemTime,
    size: u64,
}

fn stat_file(path: &Path) -> io::Result<FileState> {
    let meta = fs::metadata(path)?;
    Ok(FileState {
        mtime: meta.modified()?,
        size: meta.len(),
    })
}

/// One watched path. `state == None` means the last stat failed with a
/// non-NotFound error (Go delegate: the raw error is pushed and the path
/// drops out of that cycle's snapshot; the next successful stat is a
/// Create). NotFound removes the registration entirely — see [`poll_one`]
/// and the module notes on `ErrWatchedFileDeleted`.
struct Registration {
    path: PathBuf,
    state: Option<FileState>,
    /// The notify side of the registration's cap-1 channel (§2.5).
    notify: SyncSender<()>,
}

/// Commands understood by the watcher thread (the Go `Watch`/`Finish`
/// surface; per-registration rather than per-instance because all
/// registrations share the one thread).
enum PollerCmd {
    Register {
        id: u64,
        path: PathBuf,
        state: Option<FileState>,
        notify: SyncSender<()>,
    },
    /// Removes the registration, dropping its notify sender — a pending
    /// pump's `recv` returns `Err(Disconnected)` and it exits silently
    /// (replaces the C4 nil-send, watchermanager.go:70-74).
    Unregister { id: u64 },
}

/// Registration ids are process-unique so two managers watching the same
/// path (e.g. run view + workspace in Go, each with its own watcher
/// instance) stay independent. Starts at 1; 0 is never allocated.
static NEXT_REGISTRATION_ID: AtomicU64 = AtomicU64::new(1);

/// The singleton watcher thread's command sender, spawned on first use and
/// kept for the life of the process (like the runtime's input thread, §2.9:
/// it survives the alt+r restart loop; Go leaks one whole watcher per
/// restart instead, CONCURRENCY.md §1.6).
fn poller() -> &'static Sender<PollerCmd> {
    static POLLER: OnceLock<Sender<PollerCmd>> = OnceLock::new();
    POLLER.get_or_init(|| {
        let (tx, rx) = mpsc::channel();
        let spawned = thread::Builder::new()
            .name("watcher".into())
            .spawn(move || poll_loop(&rx));
        if let Err(err) = spawned {
            tracing::error!(%err, "watcher: failed to spawn poller thread");
        }
        tx
    })
}

/// The poll loop (impl.go:147-175 + the delegate's 500ms cycle). §2.8 note:
/// the body is panic-free by construction (no unwrap/indexing; every stat
/// and send error is handled), so it needs no `ThreadPanicked` reporting —
/// which it could not do anyway, having no event sender (it outlives
/// sessions).
fn poll_loop(cmds: &Receiver<PollerCmd>) {
    let mut registrations: HashMap<u64, Registration> = HashMap::new();
    let mut next_poll = Instant::now() + POLLING_PERIOD;
    loop {
        match cmds.recv_timeout(next_poll.saturating_duration_since(Instant::now())) {
            Ok(PollerCmd::Register {
                id,
                path,
                state,
                notify,
            }) => {
                registrations.insert(
                    id,
                    Registration {
                        path,
                        state,
                        notify,
                    },
                );
            }
            Ok(PollerCmd::Unregister { id }) => {
                registrations.remove(&id);
            }
            Err(RecvTimeoutError::Timeout) => {
                // `poll_one` returning false drops the registration — and
                // with it the notify sender — matching the delegate's
                // permanent `w.Remove` of a deleted watched file (§1.7).
                registrations.retain(|_, registration| poll_one(registration));
                next_poll = Instant::now() + POLLING_PERIOD;
            }
            // The static command sender never drops before process exit.
            Err(RecvTimeoutError::Disconnected) => return,
        }
    }
}

/// One poll cycle for one registration: stat, compare, notify on change.
/// Returns whether to keep the registration; `false` means the watched
/// file was deleted (Go: `ErrWatchedFileDeleted` + permanent unwatch — see
/// the module notes).
fn poll_one(registration: &mut Registration) -> bool {
    let new_state = match stat_file(&registration.path) {
        Ok(state) => Some(state),
        // radovskyb `retrieveFileList`: `os.IsNotExist` ⇒
        // `ErrWatchedFileDeleted` on the Error chan — leet logs it
        // (impl.go:161-166) — and `w.Remove(name)` permanently unwatches
        // the path; recreation never notifies again. Dropping the
        // registration drops its notify sender, so a pending pump exits
        // silently.
        Err(err) if err.kind() == io::ErrorKind::NotFound => {
            tracing::error!(
                path = %registration.path.display(),
                "watcher: error in file watcher: error: watched file or folder deleted"
            );
            return false;
        }
        // Other stat errors: the delegate pushes the raw error (logged,
        // impl.go:161-166) each cycle and keeps the path registered; the
        // path drops out of the cycle's snapshot, so a later successful
        // stat is a Create — which passes the filter and notifies.
        Err(err) => {
            tracing::error!(
                path = %registration.path.display(),
                "watcher: error in file watcher: {err}"
            );
            None
        }
    };
    let changed = match (registration.state, new_state) {
        // Write: mtime or size moved. PARITY(watcher.go:12-24): equal
        // mtime+size ⇒ no event, even if the contents changed.
        (Some(old), Some(new)) => old != new,
        // Create after a transient stat error — indistinguishable from
        // Write upstream (impl.go:93-99); both pass the Write|Create
        // filter and notify.
        (None, Some(_)) => true,
        // Still erroring: nothing to compare, nothing to send.
        (_, None) => false,
    };
    registration.state = new_state;
    if changed {
        tracing::debug!(path = %registration.path.display(), "watcher: file changed");
        // watchermanager.go:42-47: `select { case ch <- FileChangedMsg{}:
        // default: }` — cap-1 try_send, drop on full (§2.5).
        match registration.notify.try_send(()) {
            Ok(()) => tracing::debug!("watcher: FileChangedMsg sent"),
            Err(TrySendError::Full(())) => {
                tracing::warn!("watcher: outChan full, dropping FileChangedMsg");
            }
            // Every receiver clone is gone (the manager dropped without
            // finish); the Unregister from its Drop is already queued.
            Err(TrySendError::Disconnected(())) => {}
        }
    }
    true
}

// ---------------------------------------------------------------------------
// WatcherManager (watchermanager.go)
// ---------------------------------------------------------------------------

/// WatcherManager manages file watching for live runs.
///
/// Go's `NewWatcherManager(outChan, logger)` arguments die: the cap-1
/// notification channel is created per registration in [`start`]
/// (CONCURRENCY.md §2.5 — C1/C2's shared chans disappear; the main event
/// channel is the merge point) and the logger is `tracing`.
///
/// [`start`]: WatcherManager::start
#[derive(Debug, Default)]
pub struct WatcherManager {
    /// watchermanager.go:15.
    started: bool,
    /// The inner watcher's `isFinished` (core/internal/watcher/impl.go:22):
    /// in Go each manager owns a watcher instance, so `Start` after
    /// `Finish` fails on the finished delegate.
    finished: bool,
    /// The poller registration backing `started`; `None` when never
    /// started, after [`finish`], or when `started` was poked by tests.
    ///
    /// [`finish`]: WatcherManager::finish
    registration: Option<u64>,
    /// The pump side of the registration (see [`watch_receiver`]).
    ///
    /// [`watch_receiver`]: WatcherManager::watch_receiver
    rx: Option<WatchReceiver>,
}

impl WatcherManager {
    pub fn new() -> WatcherManager {
        WatcherManager::default()
    }

    /// Start starts watching the specified file (watchermanager.go:32-58).
    ///
    /// The file must exist, or an error is returned (watcher.go:21-22).
    /// Idempotent while started, exactly like Go (watchermanager.go:33-35).
    pub fn start(&mut self, run_path: &str) -> Result<(), WatchError> {
        if self.started {
            return Ok(());
        }
        // PARITY: after Finish, Go's Start reaches `watcher.Watch` on the
        // finished delegate, which errors (impl.go:53-55); the error is
        // logged and returned (watchermanager.go:50-53).
        if self.finished {
            let err = WatchError::Finished;
            tracing::error!("watcher: error starting: {err}");
            return Err(err);
        }

        tracing::debug!("watcher: starting for path: {run_path}");

        let state = match stat_file(Path::new(run_path)) {
            Ok(state) => state,
            Err(source) => {
                let err = WatchError::Stat {
                    path: run_path.to_string(),
                    source,
                };
                // Go: logger.CaptureError (watchermanager.go:51).
                tracing::error!("watcher: error starting: {err}");
                return Err(err);
            }
        };

        let (notify, rx) = WatchReceiver::channel();
        let id = NEXT_REGISTRATION_ID.fetch_add(1, Ordering::Relaxed);
        let _ = poller().send(PollerCmd::Register {
            id,
            path: PathBuf::from(run_path),
            state: Some(state),
            notify,
        });

        self.registration = Some(id);
        self.rx = Some(rx);
        self.started = true;
        tracing::debug!("watcher: started successfully");
        Ok(())
    }

    /// Finish stops the watcher (watchermanager.go:61-75).
    ///
    /// Unregistering drops the registration's notify sender inside the
    /// watcher thread; a pump blocked on [`WatchReceiver::recv`] returns
    /// `Err(Disconnected)` and exits silently — replacing Go's nil-send
    /// unblock (C4, watchermanager.go:70-74).
    pub fn finish(&mut self) {
        if !self.started {
            return;
        }
        tracing::debug!("watcher: finishing");
        if let Some(id) = self.registration.take() {
            let _ = poller().send(PollerCmd::Unregister { id });
        }
        self.rx = None;
        self.started = false;
        self.finished = true;
    }

    /// IsStarted returns whether the watcher is started
    /// (watchermanager.go:78-80).
    pub fn is_started(&self) -> bool {
        self.started
    }

    /// The pump side of the registration — Go's blocking `WaitForMsg`
    /// (watchermanager.go:83-90) runs as `Command::AwaitWatcherMsg` (run
    /// view) or `Command::AwaitWorkspaceWatcher` (workspace), each doing one
    /// `recv` and re-armed by the handler.
    ///
    /// Re-arm sites (Phase 5b) — run view: the runhandlers.go:908 equivalent
    /// (once, after boot load) and :950 (per handled file change) ONLY.
    /// Go's third site, :938 (`handleHeartbeat`), must NOT be ported: it is
    /// valid in Go only because the shared C1 chan carries BOTH HeartbeatMsg
    /// and FileChangedMsg, so a delivered heartbeat has consumed the pump.
    /// Here heartbeats bypass the pump (scheduler → main channel,
    /// runtime.rs `TimerId::Heartbeat`), the in-flight pump is still blocked
    /// on this receiver when one fires, and re-issuing the command would
    /// park an extra "watcher-pump" thread on the shared `Arc<Mutex<..>>`
    /// per heartbeat — an unbounded leak on a quiet live run (see the
    /// caveat on [`crate::command::Command::AwaitWatcherMsg`];
    /// CONCURRENCY.md §2.5 repeats the 908/938/950 list without it).
    /// Workspace: workspacehandlers.go:549 (initial) and :761 (file
    /// change), unchanged — Go's workspace heartbeat handler re-arms only
    /// `waitForLiveMsg` (C2), which has no Rust counterpart.
    ///
    /// `None` until [`start`] succeeds.
    ///
    /// [`start`]: WatcherManager::start
    pub fn watch_receiver(&self) -> Option<WatchReceiver> {
        self.rx.clone()
    }

    /// testhelpers.go `TestSetWatcherStarted`: pokes `started` without a
    /// real registration.
    #[cfg(test)]
    pub(crate) fn set_started_for_test(&mut self, started: bool) {
        self.started = started;
    }
}

/// §2.9: `Run`/`Workspace` cleanup calls [`WatcherManager::finish`]
/// explicitly (ordered teardown); `Drop` covers the paths Go leaks (the
/// alt+r restart loop, CONCURRENCY.md §1.6).
impl Drop for WatcherManager {
    fn drop(&mut self) {
        self.finish();
    }
}

#[cfg(test)]
mod tests {
    use std::thread;

    use leet_proto::wandb_internal::{HistoryItem, HistoryRecord, Record, record};
    use leet_wire::transaction_log;

    use super::*;

    fn history_record(step: i64) -> Record {
        Record {
            record_type: Some(record::RecordType::History(HistoryRecord {
                item: vec![HistoryItem {
                    nested_key: vec!["_step".into()],
                    value_json: format!("{step}"),
                    ..Default::default()
                }],
                ..Default::default()
            })),
            ..Default::default()
        }
    }

    /// Go: TestWatcherManager_FileChangeDetection. `WaitForMsg` is the
    /// pump's single `recv` on the registration's [`WatchReceiver`] (§2.5).
    #[test]
    fn watcher_manager_file_change_detection() {
        let mut wm = WatcherManager::new();
        assert!(!wm.is_started());

        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("test.wandb");
        let mut w = transaction_log::open_writer(&path).unwrap();

        wm.start(path.to_str().unwrap()).unwrap();
        assert!(wm.is_started());

        for i in 0..3 {
            w.write(&history_record(i)).unwrap();
            thread::sleep(Duration::from_millis(10));
            w.flush().unwrap();
        }
        w.close().unwrap();

        // Go: msg := wm.WaitForMsg(); require msg is FileChangedMsg. Here
        // Ok(()) IS the change notification; the pump command wraps it into
        // Event::FileChanged (runtime.rs).
        let rx = wm.watch_receiver().expect("started manager has a receiver");
        rx.recv().expect("expected a file-change notification");

        wm.finish();
        assert!(!wm.is_started());
    }

    /// Finish drops the notify sender: a pending pump recv unblocks with
    /// `Err(Disconnected)` and exits silently — the C4 nil-send replacement
    /// (watchermanager.go:70-74).
    #[test]
    fn watcher_manager_finish_disconnects_pump() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("static.wandb");
        std::fs::write(&path, b"header").unwrap();

        let mut wm = WatcherManager::new();
        wm.start(path.to_str().unwrap()).unwrap();
        let rx = wm.watch_receiver().unwrap();

        wm.finish();
        // No change ever occurred, so the slot is empty; the recv returns
        // once the watcher thread processes the unregister.
        assert!(rx.recv().is_err());
        assert!(!wm.is_started());
    }

    /// Start is a no-op while started (watchermanager.go:33-35) and fails
    /// after Finish with the finished-delegate error (impl.go:53-55).
    #[test]
    fn watcher_manager_start_idempotent_and_fails_after_finish() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("test.wandb");
        std::fs::write(&path, b"header").unwrap();
        let path = path.to_str().unwrap();

        let mut wm = WatcherManager::new();
        wm.start(path).unwrap();
        wm.start(path).unwrap(); // Go returns nil when already started.
        assert!(wm.is_started());

        wm.finish();
        let err = wm.start(path).unwrap_err();
        assert_eq!(
            err.to_string(),
            "watcher: tried to call Watch() after Finish()"
        );
        assert!(!wm.is_started());
    }

    /// The file must exist, or an error is returned (watcher.go:21-22).
    #[test]
    fn watcher_manager_start_missing_file_errors() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("missing.wandb");

        let mut wm = WatcherManager::new();
        let err = wm.start(path.to_str().unwrap()).unwrap_err();
        assert!(matches!(err, WatchError::Stat { .. }), "got {err:?}");
        assert!(!wm.is_started());
        assert!(wm.watch_receiver().is_none());
    }

    /// PARITY(radovskyb/watcher@v1.0.7 `retrieveFileList`): deleting a
    /// watched file pushes `ErrWatchedFileDeleted` (leet logs it,
    /// impl.go:161-166) and permanently unwatches the path — recreation
    /// never notifies again; the run falls back to heartbeat-driven reads.
    /// Here the poller drops the registration (the notify sender with it),
    /// so a pending pump recv unblocks with `Err(Disconnected)` and exits
    /// silently, while the manager — exactly like Go's, which never learns
    /// about delegate errors — still reports started.
    #[test]
    fn watcher_manager_unwatches_deleted_file() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("deleted.wandb");
        std::fs::write(&path, b"v1").unwrap();

        let mut wm = WatcherManager::new();
        wm.start(path.to_str().unwrap()).unwrap();
        let rx = wm.watch_receiver().unwrap();

        std::fs::remove_file(&path).unwrap();
        // The next poll cycle observes NotFound and drops the registration;
        // recv blocks until then and unblocks via sender disconnect, never
        // via a notification (the file did not change before deletion).
        assert!(
            rx.recv().is_err(),
            "deleted file must be unwatched, not notified"
        );

        // The manager is unaware, exactly like Go: the heartbeat re-arm
        // gate (`watcherMgr.IsStarted()`) keeps passing.
        assert!(wm.is_started());

        // Recreation cannot notify — the registration is gone for good.
        std::fs::write(&path, b"v2").unwrap();
        thread::sleep(POLLING_PERIOD + Duration::from_millis(200));
        assert!(rx.recv().is_err(), "recreated file must stay unwatched");

        wm.finish();
        assert!(!wm.is_started());
    }
}

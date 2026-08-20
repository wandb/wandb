//! Port of `core/internal/leet/heartbeat.go`: periodic heartbeat messages
//! for live runs — the safety net behind file-change notifications, re-armed
//! on real data (CONCURRENCY.md T1/B6; re-arm gates run.go:444-448 and
//! workspace.go:862-868 port with run_handlers.rs / workspace_handlers.rs).
//!
//! All timers live on the scheduler thread (CONCURRENCY.md §2.4); the
//! manager is plain main-thread state that emits [`Command`]s.
//!
//! PARITY(§2.4) — what dies, and why it is safe:
//!
//!   - `generation atomic.Uint64` (heartbeat.go:22) + the bail-out at
//!     heartbeat.go:44: Go's `timer.Stop()` is best-effort — an `AfterFunc`
//!     callback may already be executing on the timer goroutine, so stale
//!     callbacks must self-identify. The scheduler is single-threaded:
//!     Arm/Cancel/fire are totally ordered inside one thread, and `Arm`
//!     REPLACES any pending entry for the id, so a replaced or cancelled
//!     timer literally cannot fire.
//!   - `mu sync.Mutex` (heartbeat.go:17): the manager is only touched on
//!     the update thread.
//!   - the `isRunning func() bool` callback (heartbeat.go:41-44, backed by
//!     the S2/S3 atomics): liveness is plain model state; callers pass its
//!     value, evaluated on the main thread. The fire-time re-check moves to
//!     the model's Heartbeat handlers, which Go runs anyway
//!     (runhandlers.go:931-934, workspacehandlers.go:733-736) — they cover
//!     the one residual race, a Heartbeat event already sitting in the main
//!     queue when the state changes.
//!   - `outChan` (heartbeat.go:21, C1/C2): heartbeats go scheduler → main
//!     channel directly (§2.5); the runtime translates the timer fire into
//!     `Event::Heartbeat` (runtime.rs `TimerId::Heartbeat` handling).

use std::time::Duration;

use crate::command::{Command, HeartbeatOwner, TimerId};

/// HeartbeatManager manages periodic heartbeat messages for live runs.
#[derive(Debug)]
pub struct HeartbeatManager {
    interval: Duration,
    /// Keys the scheduler entry: `Run.heartbeatMgr` and
    /// `Workspace.heartbeatMgr` are independent timers (see the
    /// `HeartbeatOwner` DIVERGENCE note in command.rs).
    owner: HeartbeatOwner,
    /// Mirrors Go's `hm.timer != nil` (testhelpers.go:68/:351
    /// `TestHeartbeatTimerArmed`): set on arm, cleared ONLY by [`stop`]
    /// (see the PARITY note in [`start`]).
    ///
    /// [`start`]: HeartbeatManager::start
    /// [`stop`]: HeartbeatManager::stop
    timer_armed: bool,
}

impl HeartbeatManager {
    /// Go `NewHeartbeatManager(interval, outChan, logger)`
    /// (heartbeat.go:25-35): `outChan` dies (see the module PARITY notes),
    /// the logger is `tracing`, and `owner` names the scheduler key.
    pub fn new(interval: Duration, owner: HeartbeatOwner) -> HeartbeatManager {
        HeartbeatManager {
            interval,
            owner,
            timer_armed: false,
        }
    }

    fn timer_id(&self) -> TimerId {
        TimerId::Heartbeat(self.owner)
    }

    /// Start starts the heartbeat timer (heartbeat.go:62-81).
    ///
    /// `is_running` is Go's `isRunning()` gate evaluated by the caller on
    /// the main thread. Returns the scheduler command to dispatch: Go's
    /// "invalidate generation + best-effort Stop + AfterFunc" collapses to
    /// one `Arm` (which replaces any pending entry), or a `Cancel` on the
    /// not-running leg (Go stops the existing timer and does not arm,
    /// heartbeat.go:69-77).
    pub fn start(&mut self, is_running: bool) -> Command {
        if !is_running {
            tracing::debug!("heartbeat: not starting - run not active");
            // PARITY: Go stops the pending timer on this leg but does NOT
            // clear the `timer` pointer — only `Stop` does — so
            // `timer_armed` keeps its previous value here.
            return Command::CancelTimer {
                id: self.timer_id(),
            };
        }
        tracing::debug!("heartbeat: starting with interval {:?}", self.interval);
        self.timer_armed = true;
        Command::Tick {
            id: self.timer_id(),
            duration: self.interval,
        }
    }

    /// Reset resets the heartbeat timer (heartbeat.go:86-104). Identical to
    /// [`start`] up to log text, like Go.
    ///
    /// [`start`]: HeartbeatManager::start
    pub fn reset(&mut self, is_running: bool) -> Command {
        if !is_running {
            // PARITY: same pointer-not-cleared quirk as in `start`; this
            // leg is silent in Go (heartbeat.go:98-100).
            return Command::CancelTimer {
                id: self.timer_id(),
            };
        }
        tracing::debug!("heartbeat: resetting timer");
        self.timer_armed = true;
        Command::Tick {
            id: self.timer_id(),
            duration: self.interval,
        }
    }

    /// Stop stops the heartbeat timer (heartbeat.go:107-121).
    pub fn stop(&mut self) -> Command {
        if self.timer_armed {
            tracing::debug!("heartbeat: stopped");
        } else {
            tracing::debug!("heartbeat: stopped (no timer)");
        }
        self.timer_armed = false;
        Command::CancelTimer {
            id: self.timer_id(),
        }
    }

    /// Whether a heartbeat timer has been armed and not stopped — Go's
    /// `hm.timer != nil` (testhelpers.go `TestHeartbeatTimerArmed`).
    pub fn timer_armed(&self) -> bool {
        self.timer_armed
    }
}

#[cfg(test)]
mod tests {
    use std::sync::mpsc::{Receiver, Sender};
    use std::thread;
    use std::time::Instant;

    use super::*;
    use crate::runtime::{RuntimeEvent, TimerCmd, spawn_scheduler};
    use crate::watcher_manager::WatcherManager;

    // ADAPTED(heartbeat_test.go): the Go tests drive a real
    // `time.AfterFunc` inside the manager and assert on `outChan`. Here the
    // manager emits commands and the SCHEDULER owns firing (§2.4), so each
    // test routes the manager's commands to a live scheduler thread and
    // asserts on the `RuntimeEvent::Tick` it delivers — the runtime
    // translates that fire into `Event::Heartbeat` (covered by runtime.rs
    // tests), so a Tick here is Go's HeartbeatMsg on the out chan.

    /// Routes a manager command to the scheduler, as the effect runner does
    /// (runtime.rs `Command::Tick`/`Command::CancelTimer` dispatch).
    fn dispatch(cmd: Command, timers: &Sender<TimerCmd>) {
        match cmd {
            Command::Tick { id, duration } => timers.send(TimerCmd::Arm(id, duration)).unwrap(),
            Command::CancelTimer { id } => timers.send(TimerCmd::Cancel(id)).unwrap(),
            other => panic!("heartbeat manager produced unexpected command: {other:?}"),
        }
    }

    fn recv_tick(events: &Receiver<RuntimeEvent>, timeout: Duration) -> Option<TimerId> {
        match events.recv_timeout(timeout) {
            Ok(RuntimeEvent::Tick(id)) => Some(id),
            Ok(other) => panic!("unexpected runtime event: {other:?}"),
            Err(_) => None,
        }
    }

    fn scheduler() -> (Sender<TimerCmd>, Receiver<RuntimeEvent>) {
        let (events_tx, events_rx) = std::sync::mpsc::channel();
        (spawn_scheduler(events_tx), events_rx)
    }

    /// Go: TestHeartbeatManager_StartsAndSendsMessages.
    #[test]
    fn heartbeat_manager_starts_and_sends_messages() {
        let (timers, events) = scheduler();
        let mut hm = HeartbeatManager::new(Duration::from_millis(100), HeartbeatOwner::Run);

        dispatch(hm.start(true), &timers);
        assert!(hm.timer_armed());

        let id = recv_tick(&events, Duration::from_millis(200))
            .expect("heartbeat not received within timeout");
        assert_eq!(id, TimerId::Heartbeat(HeartbeatOwner::Run));

        dispatch(hm.stop(), &timers);
    }

    /// Go: TestHeartbeatManager_DoesNotStartWhenNotRunning.
    #[test]
    fn heartbeat_manager_does_not_start_when_not_running() {
        let (timers, events) = scheduler();
        let mut hm = HeartbeatManager::new(Duration::from_millis(50), HeartbeatOwner::Run);

        // Go: Start bails before arming when !isRunning() (heartbeat.go:74-77)
        // after a best-effort Stop; the emitted command is the Cancel.
        let cmd = hm.start(false);
        assert!(matches!(cmd, Command::CancelTimer { .. }), "got {cmd:?}");
        dispatch(cmd, &timers);
        assert!(!hm.timer_armed());

        assert_eq!(
            recv_tick(&events, Duration::from_millis(150)),
            None,
            "heartbeat sent when run not active"
        );
    }

    /// Go: TestHeartbeatManager_StopsProperly. Cancel is totally ordered
    /// with the fire inside the scheduler thread (§2.4).
    #[test]
    fn heartbeat_manager_stops_properly() {
        let (timers, events) = scheduler();
        let mut hm = HeartbeatManager::new(Duration::from_millis(100), HeartbeatOwner::Run);

        dispatch(hm.start(true), &timers);
        dispatch(hm.stop(), &timers);
        assert!(!hm.timer_armed());

        assert_eq!(
            recv_tick(&events, Duration::from_millis(200)),
            None,
            "heartbeat sent after Stop"
        );
    }

    /// Go: TestHeartbeatManager_ResetRestartsTimer. Reset's Arm replaces
    /// the pending deadline, pushing the fire a full interval out.
    #[test]
    fn heartbeat_manager_reset_restarts_timer() {
        const INTERVAL: Duration = Duration::from_millis(100);
        let (timers, events) = scheduler();
        let mut hm = HeartbeatManager::new(INTERVAL, HeartbeatOwner::Run);

        dispatch(hm.start(true), &timers);

        // Wait for a bit, but not too close to the interval boundary.
        thread::sleep(INTERVAL / 2);
        dispatch(hm.reset(true), &timers);

        // Original heartbeat shouldn't fire shortly after reset.
        assert_eq!(
            recv_tick(&events, INTERVAL / 3),
            None,
            "original heartbeat fired after reset"
        );

        // New heartbeat should fire after the full interval from reset.
        let id = recv_tick(&events, INTERVAL).expect("heartbeat not received after reset");
        assert_eq!(id, TimerId::Heartbeat(HeartbeatOwner::Run));

        dispatch(hm.stop(), &timers);
    }

    /// ADAPTED(TestHeartbeatManager_ChecksIsRunningBeforeSending): Go flips
    /// an atomic WITHOUT calling Stop, and the fire-time `isRunning()`
    /// re-check on the timer goroutine suppresses the send
    /// (heartbeat.go:44). That check dies (§2.4); its replacement is split
    /// in two:
    ///
    ///   1. liveness flips before the fire: the model stops/cancels the
    ///      heartbeat on the main thread, and Cancel is totally ordered
    ///      with the fire inside the scheduler — covered by
    ///      `heartbeat_manager_stops_properly` above.
    ///   2. the residual race — a Heartbeat already sitting in the main
    ///      queue when liveness flips — CANNOT be retracted; it must be
    ///      filtered by the model's `runState != Running` check
    ///      (runhandlers.go:931-934, workspacehandlers.go:733-736), which
    ///      Go performs on the main goroutine anyway.
    ///
    /// This test pins leg 2's premise: a Tick that fired before the Cancel
    /// reached the scheduler IS delivered, proving the manager/scheduler
    /// cannot do the fire-time suppression and the model-side filter is
    /// load-bearing.
    // TODO(phase-5b): port the filter half with run_handlers.rs /
    // workspace_handlers.rs — a stale Event::Heartbeat handled while
    // runState != Running must stop the heartbeat and produce no read/pump
    // commands (runhandlers.go:931-934; workspacehandlers.go:733-736).
    // Without that test, Go's fire-time-suppression assertion is lost.
    #[test]
    fn heartbeat_manager_checks_is_running_before_sending() {
        let (timers, events) = scheduler();
        let mut hm = HeartbeatManager::new(Duration::from_millis(50), HeartbeatOwner::Run);

        dispatch(hm.start(true), &timers);

        // Let the timer fire: the Tick now sits in the events queue, the
        // stale-Heartbeat-in-the-main-queue scenario.
        thread::sleep(Duration::from_millis(150));

        // The run stops only now — too late to retract the fired event.
        dispatch(hm.stop(), &timers);
        assert!(!hm.timer_armed());

        let id = recv_tick(&events, Duration::from_millis(100))
            .expect("stale heartbeat is delivered; the model's runState filter handles it");
        assert_eq!(id, TimerId::Heartbeat(HeartbeatOwner::Run));

        // The Cancel holds for the future: nothing further fires.
        assert_eq!(
            recv_tick(&events, Duration::from_millis(150)),
            None,
            "heartbeat sent after run stopped"
        );
    }

    /// ADAPTED(TestHeartbeatManager_MultipleStartsAndResets): the Go test
    /// exercises the generation counter — racing re-arms must yield exactly
    /// one heartbeat. The counter died (§2.4); the same guarantee is the
    /// scheduler's Arm-REPLACES-entry semantics, exercised here through the
    /// manager's command stream.
    #[test]
    fn heartbeat_manager_multiple_starts_and_resets() {
        let (timers, events) = scheduler();
        let mut hm = HeartbeatManager::new(Duration::from_millis(50), HeartbeatOwner::Run);

        dispatch(hm.start(true), &timers);
        dispatch(hm.reset(true), &timers);
        dispatch(hm.start(true), &timers);
        dispatch(hm.reset(true), &timers);

        // Should get exactly one heartbeat after the interval.
        let deadline = Instant::now() + Duration::from_millis(150);
        let mut msg_count = 0;
        while recv_tick(&events, deadline.saturating_duration_since(Instant::now())).is_some() {
            msg_count += 1;
        }
        assert_eq!(msg_count, 1, "expected exactly one heartbeat");

        dispatch(hm.stop(), &timers);
    }

    /// The `timer != nil` mirror: set on arm, cleared only by Stop —
    /// including the PARITY quirk where a not-running start/reset stops the
    /// pending timer without clearing the pointer (heartbeat.go:69-77).
    #[test]
    fn heartbeat_manager_timer_armed_mirrors_go_timer_pointer() {
        let mut hm = HeartbeatManager::new(Duration::from_secs(15), HeartbeatOwner::Workspace);
        assert!(!hm.timer_armed());

        // Not-running start before any arm: pointer stays nil.
        let cmd = hm.start(false);
        assert!(matches!(cmd, Command::CancelTimer { .. }));
        assert!(!hm.timer_armed());

        let cmd = hm.start(true);
        let Command::Tick { id, duration } = cmd else {
            panic!("expected Tick, got {cmd:?}");
        };
        assert_eq!(id, TimerId::Heartbeat(HeartbeatOwner::Workspace));
        assert_eq!(duration, Duration::from_secs(15));
        assert!(hm.timer_armed());

        // PARITY quirk: reset with !is_running stops the timer but leaves
        // the Go pointer (and therefore the armed flag) set.
        let cmd = hm.reset(false);
        assert!(matches!(cmd, Command::CancelTimer { .. }));
        assert!(hm.timer_armed());

        let _ = hm.stop();
        assert!(!hm.timer_armed());
    }

    // ADAPTED(heartbeat_lifecycle_test.go): the Go tests drive
    // Run.handleRecordMsg / Workspace.handleWorkspaceRecord, whose arming
    // gates are `shouldResetLiveHeartbeat` (run.go:444-448) and
    // `shouldResetRunHeartbeat` (workspace.go:862-868): reset only when the
    // run is live AND its WatcherManager reports started. Those handlers
    // port with run_handlers.rs / workspace_handlers.rs (Phase 5b); the
    // tests below transliterate the gate expression against the two
    // managers it composes, preserving the Go assertions on
    // TestHeartbeatTimerArmed.
    //
    // TODO(phase-5b): `reset_if_should` is a test-local copy of the gate —
    // these four tests cannot fail if the real handlers omit or invert it.
    // When run_handlers.rs / workspace_handlers.rs land, re-point them at
    // the production record handlers (as Go does) and delete
    // `reset_if_should`:
    //   - TestRunHandleRecordMsg_DoesNotArmHeartbeatBeforeWatcherStarts
    //   - TestRunHandleRecordMsg_ArmsHeartbeatAfterWatcherStarts
    //   - TestWorkspaceHandleWorkspaceRecord_DoesNotArmHeartbeatBeforeWatcherStarts
    //   - TestWorkspaceHandleWorkspaceRecord_ArmsHeartbeatAfterWatcherStarts

    /// run.go:444-448 as data arrives (runhandlers gate on HistoryMsg).
    fn reset_if_should(hm: &mut HeartbeatManager, run_state_running: bool, wm: &WatcherManager) {
        if run_state_running && wm.is_started() {
            let _ = hm.reset(true);
        }
    }

    /// Go: TestRunHandleRecordMsg_DoesNotArmHeartbeatBeforeWatcherStarts.
    #[test]
    fn run_does_not_arm_heartbeat_before_watcher_starts() {
        let mut hm = HeartbeatManager::new(Duration::from_secs(15), HeartbeatOwner::Run);
        let wm = WatcherManager::new();

        // Boot-load data for a live run, watcher not yet started.
        reset_if_should(&mut hm, true, &wm);

        assert!(!hm.timer_armed());
    }

    /// Go: TestRunHandleRecordMsg_ArmsHeartbeatAfterWatcherStarts.
    #[test]
    fn run_arms_heartbeat_after_watcher_starts() {
        let mut hm = HeartbeatManager::new(Duration::from_secs(15), HeartbeatOwner::Run);
        let mut wm = WatcherManager::new();
        wm.set_started_for_test(true);

        reset_if_should(&mut hm, true, &wm);

        assert!(hm.timer_armed());
        let _ = hm.stop(); // Go: run.TestStopHeartbeat()
        assert!(!hm.timer_armed());
    }

    /// Go: TestWorkspaceHandleWorkspaceRecord_DoesNotArmHeartbeatBeforeWatcherStarts
    /// (`shouldResetRunHeartbeat`, workspace.go:862-868: same gate shape,
    /// keyed on the per-run WatcherManager).
    #[test]
    fn workspace_does_not_arm_heartbeat_before_watcher_starts() {
        let mut hm = HeartbeatManager::new(Duration::from_secs(15), HeartbeatOwner::Workspace);
        let wm = WatcherManager::new();

        reset_if_should(&mut hm, true, &wm);

        assert!(!hm.timer_armed());
    }

    /// Go: TestWorkspaceHandleWorkspaceRecord_ArmsHeartbeatAfterWatcherStarts.
    #[test]
    fn workspace_arms_heartbeat_after_watcher_starts() {
        let mut hm = HeartbeatManager::new(Duration::from_secs(15), HeartbeatOwner::Workspace);
        let mut wm = WatcherManager::new();
        wm.set_started_for_test(true); // Go: run.TestSetWatcherStarted(true)

        reset_if_should(&mut hm, true, &wm);

        assert!(hm.timer_armed());
        let _ = hm.stop(); // Go: workspace.TestStopHeartbeat()
    }
}

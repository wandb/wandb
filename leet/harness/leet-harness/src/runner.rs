//! Scenario runner: drives one app process (the Go oracle now; the Rust
//! binary later — both speak the same env hooks and ack protocol) through a
//! scenario and captures named snapshots.

use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{Context, Result, bail};

use crate::ack::AckListener;
use crate::grid::Grid;
use crate::persona::{PersonaBackground, QueryLogEntry};
use crate::pty::{PtyProcess, SpawnSpec};
use crate::scenario::{
    Background, KEY_ACK_TYPE, MOUSE_ACK_TYPE, RESIZE_ACK_TYPE, Scenario, Step, encode_key,
    encode_mouse,
};

/// How to launch the app under test.
pub struct AppSpec {
    /// Binary path (oracle: the wandb-core build; later: wandb-leet).
    pub program: PathBuf,
    /// Arguments preceding scenario-derived ones ("leet" for wandb-core;
    /// empty for wandb-leet).
    pub base_args: Vec<String>,
}

pub struct RunOutput {
    pub snapshots: Vec<(String, Grid)>,
    pub persona_log: Vec<QueryLogEntry>,
    pub ack_tail: Vec<String>,
}

/// Output-drain window before every snapshot: the renderer may still be
/// flushing the frame whose View ack we just saw.
const SNAP_DRAIN_QUIET: Duration = Duration::from_millis(40);
const SNAP_DRAIN_TIMEOUT: Duration = Duration::from_millis(400);

pub fn run_scenario(app: &AppSpec, scenario: &Scenario, fixtures_root: &Path) -> Result<RunOutput> {
    let work = tempfile::TempDir::new().context("scenario temp dir")?;
    let ack_path = work.path().join("ack.fifo");
    let mut acks = AckListener::new(&ack_path)?;

    let mut args = app.base_args.clone();
    args.push("--no-observability".to_string());
    args.extend(scenario.args.iter().cloned());
    if let Some(fixture) = &scenario.fixture {
        let dir = fixtures_root.join(fixture).join("wandb");
        if !dir.is_dir() {
            bail!("fixture dir not found: {}", dir.display());
        }
        // The app renders the wandb-dir path it was given (status bar), so
        // frames must not depend on where the repo is checked out: copy the
        // fixture to a canonical path that is identical on every machine.
        // Scenarios run sequentially; the path is unique per scenario.
        let canon = PathBuf::from("/tmp/leet-parity").join(&scenario.name);
        if canon.exists() {
            std::fs::remove_dir_all(&canon).context("clear canonical fixture dir")?;
        }
        copy_dir_with_symlinks(&dir, &canon.join("wandb")).context("copy fixture to /tmp")?;
        args.push(canon.join("wandb").to_string_lossy().to_string());
    }

    let background = match scenario.background {
        Background::Dark => PersonaBackground::Dark,
        Background::Light => PersonaBackground::Light,
    };

    let mut env = vec![
        ("WANDB_LEET_TEST".to_string(), "1".to_string()),
        (
            "LEET_TEST_ACK_FILE".to_string(),
            ack_path.to_string_lossy().to_string(),
        ),
        (
            "HOME".to_string(),
            work.path().to_string_lossy().to_string(),
        ),
        (
            "WANDB_CONFIG_DIR".to_string(),
            work.path().join("config").to_string_lossy().to_string(),
        ),
        (
            "WANDB_DIR".to_string(),
            work.path().to_string_lossy().to_string(),
        ),
    ];
    if scenario.background == Background::Light {
        env.push(("WANDB_LEET_TEST_BG".to_string(), "light".to_string()));
    }
    std::fs::create_dir_all(work.path().join("config"))?;

    let mut pty = PtyProcess::spawn(&SpawnSpec {
        program: app.program.to_string_lossy().to_string(),
        args,
        cwd: work.path().to_path_buf(),
        env,
        cols: scenario.size.cols,
        rows: scenario.size.rows,
        background,
    })?;

    let result = drive(&mut pty, &mut acks, scenario);

    // Always try to shut down cleanly, even on step failure.
    let shutdown = pty.shutdown();

    let output = RunOutput {
        snapshots: match result {
            Ok(snaps) => snaps,
            Err(e) => {
                return Err(e.context(format!(
                    "scenario {:?} failed; persona log: {:?}; raw output tail: {}",
                    scenario.name,
                    pty.persona_log(),
                    pty.raw_tail()
                )));
            }
        },
        persona_log: pty.persona_log(),
        ack_tail: acks.tail(30),
    };
    shutdown?;
    Ok(output)
}

/// Recursive copy preserving symlinks (fixtures contain `latest-run`).
fn copy_dir_with_symlinks(src: &Path, dst: &Path) -> Result<()> {
    std::fs::create_dir_all(dst)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let ty = entry.file_type()?;
        let to = dst.join(entry.file_name());
        if ty.is_symlink() {
            let target = std::fs::read_link(entry.path())?;
            std::os::unix::fs::symlink(target, &to)?;
        } else if ty.is_dir() {
            copy_dir_with_symlinks(&entry.path(), &to)?;
        } else {
            std::fs::copy(entry.path(), &to)?;
        }
    }
    Ok(())
}

fn drive(
    pty: &mut PtyProcess,
    acks: &mut AckListener,
    scenario: &Scenario,
) -> Result<Vec<(String, Grid)>> {
    let mut snapshots = Vec::new();

    for (i, step) in scenario.steps.iter().enumerate() {
        let step_ctx = || format!("step {i}: {step:?}");
        if !pty.is_alive() {
            bail!("app exited prematurely before {}", step_ctx());
        }
        match step {
            Step::Key(name) => {
                acks.drain();
                let since = acks.history.len();
                pty.write_input(&encode_key(name)?)?;
                let seq = acks
                    .await_update(KEY_ACK_TYPE, 1, since, Duration::from_secs(10))
                    .with_context(step_ctx)?;
                acks.await_view(seq, Duration::from_secs(10))
                    .with_context(step_ctx)?;
                acks.await_quiet(Duration::from_millis(150), Duration::from_secs(10))
                    .with_context(step_ctx)?;
            }
            Step::KeyNoAwait(name) => {
                pty.write_input(&encode_key(name)?)?;
            }
            Step::Mouse(m) => {
                acks.drain();
                let since = acks.history.len();
                pty.write_input(&encode_mouse(m))?;
                let seq = acks
                    .await_update(MOUSE_ACK_TYPE, 1, since, Duration::from_secs(10))
                    .with_context(step_ctx)?;
                acks.await_view(seq, Duration::from_secs(10))
                    .with_context(step_ctx)?;
                acks.await_quiet(Duration::from_millis(150), Duration::from_secs(10))
                    .with_context(step_ctx)?;
            }
            Step::Resize { cols, rows } => {
                acks.drain();
                let since = acks.history.len();
                pty.resize(*cols, *rows)?;
                let seq = acks
                    .await_update(RESIZE_ACK_TYPE, 1, since, Duration::from_secs(10))
                    .with_context(step_ctx)?;
                acks.await_view(seq, Duration::from_secs(10))
                    .with_context(step_ctx)?;
                acks.await_quiet(Duration::from_millis(150), Duration::from_secs(10))
                    .with_context(step_ctx)?;
            }
            Step::AwaitUpdate {
                type_fragment,
                count,
                timeout_ms,
            } => {
                let seq = acks
                    .await_update(type_fragment, *count, 0, Duration::from_millis(*timeout_ms))
                    .with_context(step_ctx)?;
                acks.await_view(seq, Duration::from_secs(10))
                    .with_context(step_ctx)?;
            }
            Step::Quiesce {
                quiet_ms,
                timeout_ms,
            } => {
                acks.await_quiet(
                    Duration::from_millis(*quiet_ms),
                    Duration::from_millis(*timeout_ms),
                )
                .with_context(step_ctx)?;
            }
            Step::Snap(name) => {
                pty.await_output_quiet(SNAP_DRAIN_QUIET, SNAP_DRAIN_TIMEOUT);
                snapshots.push((name.clone(), pty.snapshot()));
            }
            Step::WaitMs(ms) => {
                std::thread::sleep(Duration::from_millis(*ms));
            }
        }
    }
    Ok(snapshots)
}

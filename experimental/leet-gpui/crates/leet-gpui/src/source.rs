//! Run discovery and the threads that feed runs into the workspace.

use std::path::{Path, PathBuf};
use std::thread;

use futures::channel::mpsc::UnboundedSender;
use leet_ingest::{Batch, RunInfo};

/// A run directory inside a wandb directory.
#[derive(Debug, Clone)]
pub struct RunDir {
    pub dir_name: String,
    pub wandb_file: PathBuf,
    pub id: String,
}

/// Splits a path into the wandb directory and the run to open, following
/// `wandb/cli/leet.py`: a `.wandb` file or a run directory selects that run;
/// any other directory is a wandb directory.
pub fn resolve(path: &Path) -> (PathBuf, Option<String>) {
    let run_dir = if path.is_file() {
        path.parent()
    } else if find_wandb_file(path).is_some() {
        Some(path)
    } else {
        None
    };
    match run_dir {
        Some(run_dir) => (
            run_dir.parent().unwrap_or(run_dir).to_path_buf(),
            run_dir
                .file_name()
                .map(|name| name.to_string_lossy().into_owned()),
        ),
        None => (path.to_path_buf(), None),
    }
}

fn find_wandb_file(dir: &Path) -> Option<PathBuf> {
    std::fs::read_dir(dir)
        .ok()?
        .flatten()
        .map(|e| e.path())
        .find(|p| {
            p.extension().is_some_and(|e| e == "wandb")
                && p.file_stem()
                    .is_some_and(|s| s.to_string_lossy().starts_with("run-"))
        })
}

/// The run directories under `wandb_dir`, newest first.
pub fn scan(wandb_dir: &Path) -> Vec<RunDir> {
    let Ok(entries) = std::fs::read_dir(wandb_dir) else {
        return Vec::new();
    };
    let mut runs: Vec<RunDir> = entries
        .flatten()
        .filter_map(|entry| {
            let dir_name = entry.file_name().to_string_lossy().into_owned();
            if !dir_name.contains("run-") || dir_name == "latest-run" {
                return None;
            }
            let wandb_file = find_wandb_file(&entry.path())?;
            let id = wandb_file
                .file_stem()?
                .to_string_lossy()
                .trim_start_matches("run-")
                .to_string();
            Some(RunDir {
                dir_name,
                wandb_file,
                id,
            })
        })
        .collect();
    runs.sort_by(|a, b| b.dir_name.cmp(&a.dir_name));
    runs
}

/// Follows a run's transaction log on its own thread, sending batches until
/// the run exits or the receiver is dropped.
pub fn spawn_follow(run: &RunDir, tx: UnboundedSender<Batch>) {
    let path = run.wandb_file.clone();
    thread::spawn(move || leet_ingest::follow(&path, |batch| tx.unbounded_send(batch).is_ok()));
}

/// Reads the run record of every file so the list shows display names and
/// config before a run is opened.
pub fn spawn_probe(runs: Vec<(String, PathBuf)>, tx: UnboundedSender<(String, RunInfo)>) {
    thread::spawn(move || {
        for (name, path) in runs {
            if let Some(info) = leet_ingest::probe(&path)
                && tx.unbounded_send((name, info)).is_err()
            {
                return;
            }
        }
    });
}

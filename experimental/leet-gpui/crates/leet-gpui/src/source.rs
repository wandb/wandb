//! Run discovery and background readers. Each reader owns a
//! `LevelDBHistorySource` on its own thread and forwards message batches
//! over a channel; the workspace applies them on the UI thread.

use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use futures::channel::mpsc::UnboundedSender;
use leet_data::history_source::{
    BOOT_LOAD_CHUNK_SIZE, BOOT_LOAD_MAX_TIME, HistorySource, RunMsg, SourceMsg,
};
use leet_data::leveldb_history_source::LevelDBHistorySource;

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

/// Streams the records of `run` as batches until the run's exit record has
/// been read. A file that is still being written is polled once a second; an
/// empty batch marks the moment the reader first catches up with the writer.
pub fn spawn_reader(run: &RunDir, tx: UnboundedSender<Vec<SourceMsg>>) {
    let path = run.wandb_file.to_string_lossy().into_owned();
    thread::spawn(move || {
        let mut source = match LevelDBHistorySource::new(&path) {
            Ok(source) => source,
            Err(err) => {
                let _ = tx.unbounded_send(vec![SourceMsg::Error(
                    leet_data::history_source::ErrorMsg { err: Box::new(err) },
                )]);
                return;
            }
        };
        let mut caught_up = false;
        loop {
            let (msg, err) = source.read(BOOT_LOAD_CHUNK_SIZE, BOOT_LOAD_MAX_TIME);
            let mut has_more = false;
            let mut batch = Vec::new();
            if let Some(msg) = msg {
                batch = match msg {
                    SourceMsg::ChunkedBatch(batch) => {
                        has_more = batch.has_more;
                        batch.msgs
                    }
                    other => vec![other],
                };
            }
            if err.is_some_and(|e| e.is_eof()) {
                let _ = tx.unbounded_send(batch);
                return;
            }
            let send = !batch.is_empty() || (!has_more && !caught_up);
            caught_up = !has_more;
            if send && tx.unbounded_send(batch).is_err() {
                return;
            }
            if !has_more {
                thread::sleep(Duration::from_secs(1));
            }
        }
    });
}

/// Reads the leading run record of every file so the list shows display names
/// before a run is opened.
pub fn spawn_probe(runs: Vec<(String, PathBuf)>, tx: UnboundedSender<(String, RunMsg)>) {
    thread::spawn(move || {
        for (name, path) in runs {
            let Ok(mut source) = LevelDBHistorySource::new(&path.to_string_lossy()) else {
                continue;
            };
            let (msg, _) = source.read(64, Duration::from_millis(50));
            let Some(SourceMsg::ChunkedBatch(batch)) = msg else {
                continue;
            };
            for msg in batch.msgs {
                if let SourceMsg::Run(run) = msg {
                    if tx.unbounded_send((name, run)).is_err() {
                        return;
                    }
                    break;
                }
            }
        }
    });
}

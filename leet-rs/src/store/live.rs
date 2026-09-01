//! Live reading of `.wandb` transaction logs.
//!
//! A background thread per open run tails the file: it reads records in
//! chunks (yielding to the UI between chunks), converts them to UI messages,
//! and, when it reaches EOF without an exit record, waits for file growth
//! (polling mtime/size) before retrying — mirroring the Go LiveStore +
//! watcher + heartbeat design.

use std::fs::File;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::Sender;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::msg::{
    ConsoleLogMsg, HistoryMsg, MediaPoint, MetricData, Msg, RecordMsg, RunMsg, StatsMsg,
};
use crate::store::leveldb::{Error, RecordReader, WANDB_STORE_VERSION};
use crate::store::proto::{self, HistoryRecord, OutputRawRecord, RecordData, StatsRecord};

/// Boot loading parameters.
pub const BOOT_LOAD_CHUNK_SIZE: usize = 1000;
pub const BOOT_LOAD_MAX_TIME: Duration = Duration::from_millis(100);

/// Live monitoring parameters.
pub const LIVE_MONITOR_CHUNK_SIZE: usize = 2000;
pub const LIVE_MONITOR_MAX_TIME: Duration = Duration::from_millis(50);

/// How often the tailing thread polls the file for changes.
const POLL_INTERVAL: Duration = Duration::from_millis(300);

static NEXT_SOURCE_ID: AtomicU64 = AtomicU64::new(1);

/// Allocates a unique reader instance id.
pub fn next_source_id() -> u64 {
    NEXT_SOURCE_ID.fetch_add(1, Ordering::Relaxed)
}

/// Handle used to stop a reader thread.
pub struct ReaderHandle {
    pub source_id: u64,
    stop: Arc<AtomicBool>,
}

impl ReaderHandle {
    pub fn stop(&self) {
        self.stop.store(true, Ordering::Relaxed);
    }
}

impl Drop for ReaderHandle {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Reads records from a `.wandb` file, converting them to `RecordMsg`s.
pub struct HistoryReader {
    run_path: String,
    reader: RecordReader<File>,
    header_verified: bool,
    last_read_offset: i64,
    exit_seen: bool,
    exit_code: i32,
    file_complete_emitted: bool,
}

/// Result of one chunked read.
pub struct Chunk {
    pub msgs: Vec<RecordMsg>,
    pub has_more: bool,
    pub progress: usize,
    /// True if reading should stop permanently (exit record emitted).
    pub done: bool,
}

impl HistoryReader {
    pub fn open(run_path: &str) -> Result<Self, String> {
        let file = File::open(run_path).map_err(|e| format!("failed to open {run_path}: {e}"))?;
        Ok(Self {
            run_path: run_path.to_string(),
            reader: RecordReader::new(file),
            header_verified: false,
            last_read_offset: 0,
            exit_seen: false,
            exit_code: 0,
            file_complete_emitted: false,
        })
    }

    /// Reads one record, transparently retrying the same offset on EOF-like
    /// errors so a growing file can be resumed.
    fn read_record(&mut self) -> Result<Option<RecordData>, Error> {
        self.last_read_offset = self.reader.next_offset();

        if !self.header_verified {
            if let Err(e) = self.reader.verify_wandb_header(WANDB_STORE_VERSION) {
                let _ = self.reader.seek_record(self.last_read_offset);
                return Err(e);
            }
            self.header_verified = true;
        }

        match self.reader.next_record() {
            Ok(payload) => {
                self.reader.recover();
                Ok(proto::parse_record(&payload))
            }
            Err(e) => {
                self.reader.recover();
                // Return to the previous position to retry later.
                let _ = self.reader.seek_record(self.last_read_offset);
                Err(e)
            }
        }
    }

    /// Reads up to `chunk_size` records or until `max_time` elapses.
    pub fn read_chunk(&mut self, chunk_size: usize, max_time: Duration) -> Chunk {
        if self.exit_seen && self.file_complete_emitted {
            return Chunk {
                msgs: vec![],
                has_more: false,
                progress: 0,
                done: true,
            };
        }

        let mut msgs: Vec<RecordMsg> = Vec::new();
        let mut histories: Vec<HistoryMsg> = Vec::new();
        let mut summaries = Vec::new();
        let mut scanned = 0usize;
        let start = Instant::now();

        while scanned < chunk_size && start.elapsed() < max_time {
            let record = match self.read_record() {
                Ok(Some(r)) => r,
                Ok(None) => {
                    scanned += 1;
                    continue;
                }
                Err(_) => break,
            };
            scanned += 1;

            match record {
                RecordData::Exit(exit) => {
                    self.exit_seen = true;
                    self.exit_code = exit.exit_code;
                    break;
                }
                RecordData::History(h) => {
                    if let Some(m) = parse_history(&self.run_path, &h) {
                        histories.push(m);
                    }
                }
                RecordData::Summary(s) => summaries.push(s),
                RecordData::Run(r) => msgs.push(RecordMsg::Run(RunMsg {
                    run_path: self.run_path.clone(),
                    id: r.run_id,
                    project: r.project,
                    display_name: r.display_name,
                    notes: r.notes,
                    tags: r.tags,
                    config: r.config,
                })),
                // Standalone config records are ignored, matching the Go
                // reader (config arrives via the RunRecord).
                RecordData::Config(_) => {}
                RecordData::Stats(s) => {
                    if let Some(m) = parse_stats(&self.run_path, &s) {
                        msgs.push(RecordMsg::Stats(m));
                    }
                }
                RecordData::Environment(e) => msgs.push(RecordMsg::SystemInfo {
                    run_path: self.run_path.clone(),
                    record: Box::new(e),
                }),
                RecordData::OutputRaw(o) => {
                    msgs.push(RecordMsg::ConsoleLog(parse_output_raw(&self.run_path, &o)));
                }
            }
        }

        if !histories.is_empty() {
            msgs.push(RecordMsg::History(concatenate_history(
                histories,
                &self.run_path,
            )));
        }
        if !summaries.is_empty() {
            msgs.push(RecordMsg::Summary {
                run_path: self.run_path.clone(),
                summary: summaries,
            });
        }

        let mut done = false;
        if self.exit_seen && !self.file_complete_emitted {
            msgs.push(RecordMsg::FileComplete {
                exit_code: self.exit_code,
            });
            self.file_complete_emitted = true;
            done = true;
        }

        Chunk {
            msgs,
            has_more: !self.exit_seen && scanned > 0,
            progress: scanned,
            done,
        }
    }
}

/// Spawns a thread that boots then live-tails `run_path`, sending batches to
/// `tx`. Returns a handle whose drop stops the thread.
pub fn spawn_reader(run_path: String, tx: Sender<Msg>) -> ReaderHandle {
    let source_id = next_source_id();
    let stop = Arc::new(AtomicBool::new(false));
    let stop2 = Arc::clone(&stop);

    std::thread::spawn(move || {
        let mut reader = match HistoryReader::open(&run_path) {
            Ok(r) => r,
            Err(e) => {
                let _ = tx.send(Msg::ReaderError {
                    source_id,
                    error: e,
                });
                return;
            }
        };

        let mut caught_up = false;
        let mut last_sig = file_signature(Path::new(&run_path));

        while !stop2.load(Ordering::Relaxed) {
            let (chunk_size, max_time) = if caught_up {
                (LIVE_MONITOR_CHUNK_SIZE, LIVE_MONITOR_MAX_TIME)
            } else {
                (BOOT_LOAD_CHUNK_SIZE, BOOT_LOAD_MAX_TIME)
            };
            let chunk = reader.read_chunk(chunk_size, max_time);

            let idle = chunk.msgs.is_empty() && chunk.progress == 0;
            if !chunk.has_more {
                caught_up = true;
            }
            if !idle
                && tx
                    .send(Msg::Batch {
                        source_id,
                        msgs: chunk.msgs,
                        progress: chunk.progress,
                        caught_up,
                    })
                    .is_err()
            {
                return;
            }
            if chunk.done {
                return;
            }
            if chunk.has_more {
                continue;
            }

            // At EOF on a live file: wait for it to change.
            loop {
                if stop2.load(Ordering::Relaxed) {
                    return;
                }
                std::thread::sleep(POLL_INTERVAL);
                let sig = file_signature(Path::new(&run_path));
                if sig != last_sig {
                    last_sig = sig;
                    break;
                }
            }
        }
    });

    ReaderHandle { source_id, stop }
}

/// Spawns a short-lived thread that scans `run_path` for the run record only,
/// used to preload workspace run metadata.
pub fn spawn_run_preload(run_key: String, run_path: String, tx: Sender<Msg>) {
    std::thread::spawn(move || {
        let run = preload_run(&run_path);
        let _ = tx.send(Msg::RunPreloaded {
            run_key,
            run: run.map(Box::new),
        });
    });
}

fn preload_run(run_path: &str) -> Option<RunMsg> {
    let mut reader = HistoryReader::open(run_path).ok()?;
    let deadline = Instant::now() + Duration::from_secs(2);
    while Instant::now() < deadline {
        match reader.read_record() {
            Ok(Some(RecordData::Run(r))) => {
                return Some(RunMsg {
                    run_path: run_path.to_string(),
                    id: r.run_id,
                    project: r.project,
                    display_name: r.display_name,
                    notes: r.notes,
                    tags: r.tags,
                    config: r.config,
                });
            }
            Ok(_) => continue,
            Err(_) => return None,
        }
    }
    None
}

fn file_signature(path: &Path) -> (u64, u64) {
    match std::fs::metadata(path) {
        Ok(md) => {
            let mtime = md
                .modified()
                .ok()
                .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
                .map(|d| d.as_millis() as u64)
                .unwrap_or(0);
            (md.len(), mtime)
        }
        Err(_) => (0, 0),
    }
}

// ---- Record conversion (ports of ParseHistory / ParseStats / parseOutputRaw) ----

/// Extracts metrics and media from a history record.
pub fn parse_history(run_path: &str, history: &HistoryRecord) -> Option<HistoryMsg> {
    let mut step = history.step.unwrap_or(0);
    let mut values: Vec<(String, f64)> = Vec::new();
    let mut media_fields: Vec<(String, Vec<(String, String)>)> = Vec::new();

    for item in &history.items {
        if let Some((media_key, field)) = history_media_field(item) {
            let value = trim_json_string(&item.value_json);
            match media_fields.iter_mut().find(|(k, _)| *k == media_key) {
                Some((_, fields)) => fields.push((field, value)),
                None => media_fields.push((media_key, vec![(field, value)])),
            }
            continue;
        }

        let key = if item.nested_key.is_empty() {
            item.key.clone()
        } else {
            item.nested_key.join(".")
        };
        if key.is_empty() {
            continue;
        }

        let v = trim_json_string(&item.value_json);
        if key == "_step" {
            if let Ok(s) = v.parse::<i64>() {
                step = s;
            }
            continue;
        }
        if key.starts_with('_') {
            continue;
        }
        if let Ok(val) = v.parse::<f64>() {
            values.push((key, val));
        }
    }

    let metrics: Vec<(String, MetricData)> = values
        .into_iter()
        .map(|(k, y)| {
            (
                k,
                MetricData {
                    x: vec![step as f64],
                    y: vec![y],
                },
            )
        })
        .collect();

    let media = parse_history_media(run_path, step, &media_fields);

    if metrics.is_empty() && media.is_empty() {
        return None;
    }
    Some(HistoryMsg {
        run_path: run_path.to_string(),
        metrics,
        media,
    })
}

fn history_media_field(item: &proto::KeyedJsonItem) -> Option<(String, String)> {
    let parts = &item.nested_key;
    if parts.len() < 2 {
        return None;
    }
    let field = parts.last().unwrap().as_str();
    match field {
        "_type" | "path" | "caption" | "format" | "width" | "height" | "sha256" | "size"
        | "count" | "filenames" | "captions" => {}
        _ => return None,
    }
    let media_key = parts[..parts.len() - 1].join(".");
    if media_key.is_empty() {
        return None;
    }
    Some((media_key, field.to_string()))
}

fn parse_history_media(
    run_path: &str,
    step: i64,
    media_fields: &[(String, Vec<(String, String)>)],
) -> Vec<(String, Vec<MediaPoint>)> {
    let mut media: Vec<(String, Vec<MediaPoint>)> = Vec::new();
    let mut push = |key: String, point: MediaPoint| match media.iter_mut().find(|(k, _)| *k == key)
    {
        Some((_, points)) => points.push(point),
        None => media.push((key, vec![point])),
    };

    for (media_key, fields) in media_fields {
        let get = |name: &str| -> &str {
            fields
                .iter()
                .find(|(f, _)| f == name)
                .map(|(_, v)| v.as_str())
                .unwrap_or("")
        };
        match get("_type") {
            "image-file" => {
                let rel_path = get("path");
                if rel_path.is_empty() {
                    continue;
                }
                push(
                    media_key.clone(),
                    MediaPoint {
                        x: step as f64,
                        file_path: resolve_media_path(run_path, rel_path),
                        relative_path: rel_path.to_string(),
                        caption: get("caption").to_string(),
                        format: get("format").to_string(),
                        width: get("width").parse().unwrap_or(0),
                        height: get("height").parse().unwrap_or(0),
                        sha256: get("sha256").to_string(),
                    },
                );
            }
            "images/separated" => {
                let captions = parse_json_string_array(get("captions"));
                for (i, rel_path) in parse_json_string_array(get("filenames")).iter().enumerate() {
                    if rel_path.is_empty() {
                        continue;
                    }
                    push(
                        format!("{media_key}[{i}]"),
                        MediaPoint {
                            x: step as f64,
                            file_path: resolve_media_path(run_path, rel_path),
                            relative_path: rel_path.clone(),
                            caption: captions.get(i).cloned().unwrap_or_default(),
                            format: get("format").to_string(),
                            width: get("width").parse().unwrap_or(0),
                            height: get("height").parse().unwrap_or(0),
                            sha256: String::new(),
                        },
                    );
                }
            }
            _ => {}
        }
    }
    media
}

fn parse_json_string_array(v: &str) -> Vec<String> {
    serde_json::from_str::<Vec<String>>(v).unwrap_or_default()
}

/// Removes surrounding JSON quotes from a value, if present.
pub fn trim_json_string(v: &str) -> String {
    if v.len() >= 2
        && v.starts_with('"')
        && let Ok(serde_json::Value::String(s)) = serde_json::from_str(v)
    {
        return s;
    }
    v.to_string()
}

/// Resolves a media file path relative to the run's `files/` directory.
pub fn resolve_media_path(run_path: &str, relative_path: &str) -> String {
    if relative_path.is_empty() {
        return String::new();
    }
    let rel = Path::new(relative_path);
    if rel.is_absolute() {
        return relative_path.to_string();
    }

    // Strip any leading separators / parent components for safety.
    let mut clean = PathBuf::new();
    for comp in rel.components() {
        use std::path::Component;
        match comp {
            Component::Normal(c) => clean.push(c),
            Component::ParentDir => {
                clean.pop();
            }
            _ => {}
        }
    }

    let dir = Path::new(run_path).parent().unwrap_or(Path::new(""));
    dir.join("files").join(clean).to_string_lossy().into_owned()
}

/// Extracts system metrics from a stats record.
pub fn parse_stats(run_path: &str, stats: &StatsRecord) -> Option<StatsMsg> {
    let timestamp = stats.timestamp.map(|t| t.seconds).unwrap_or(0);
    let mut metrics = Vec::with_capacity(stats.items.len());

    for item in &stats.items {
        let mut v = item.value_json.as_str();
        if v.len() >= 2 && v.starts_with('"') && v.ends_with('"') {
            v = &v[1..v.len() - 1];
        }
        if let Ok(value) = v.parse::<f64>() {
            metrics.push((item.key.clone(), value));
        }
    }

    if metrics.is_empty() {
        return None;
    }
    Some(StatsMsg {
        run_path: run_path.to_string(),
        timestamp,
        metrics,
    })
}

fn parse_output_raw(run_path: &str, rec: &OutputRawRecord) -> ConsoleLogMsg {
    ConsoleLogMsg {
        run_path: run_path.to_string(),
        text: rec.line.clone(),
        is_stderr: rec.output_type == 0,
        time: rec
            .timestamp
            .map(|t| UNIX_EPOCH + Duration::new(t.seconds.max(0) as u64, t.nanos.max(0) as u32)),
    }
}

/// Merges history messages accumulated within one chunk.
fn concatenate_history(messages: Vec<HistoryMsg>, run_path: &str) -> HistoryMsg {
    let mut out = HistoryMsg {
        run_path: run_path.to_string(),
        ..Default::default()
    };
    for msg in messages {
        for (name, data) in msg.metrics {
            match out.metrics.iter_mut().find(|(k, _)| *k == name) {
                Some((_, existing)) => {
                    existing.x.extend(data.x);
                    existing.y.extend(data.y);
                }
                None => out.metrics.push((name, data)),
            }
        }
        for (key, points) in msg.media {
            match out.media.iter_mut().find(|(k, _)| *k == key) {
                Some((_, existing)) => existing.extend(points),
                None => out.media.push((key, points)),
            }
        }
    }
    out
}

// Re-export for callers that need explicit types.
pub use std::sync::mpsc;

/// True if `t` looks like a run directory name inside a wandb dir.
pub fn is_run_dir_name(name: &str) -> bool {
    name.starts_with("run-") || name.starts_with("offline-run-")
}

/// How often the workspace polls its wandb directory for new runs.
pub const WANDB_DIR_POLL_INTERVAL: Duration = Duration::from_secs(5);

/// Extracts the run ID from a run directory name.
///
/// Expected formats: `run-YYYYMMDD_HHMMSS-<run_id>` or
/// `offline-run-YYYYMMDD_HHMMSS-<run_id>`. Returns `""` on mismatch.
pub fn extract_run_id(folder_name: &str) -> &str {
    let rest = folder_name
        .strip_prefix("offline-run-")
        .or_else(|| folder_name.strip_prefix("run-"))
        .unwrap_or("");
    match run_dir_timestamp(rest) {
        Some(_) if rest.len() > 16 && rest.as_bytes()[15] == b'-' => &rest[16..],
        _ => "",
    }
}

/// The full path to the `.wandb` file for the given run folder, derived
/// purely from the directory name (no filesystem access).
pub fn run_wandb_file(wandb_dir: &str, run_dir: &str) -> Option<PathBuf> {
    let run_id = extract_run_id(run_dir);
    if run_id.is_empty() {
        return None;
    }
    Some(
        Path::new(wandb_dir)
            .join(run_dir)
            .join(format!("run-{run_id}.wandb")),
    )
}

/// Parses the `YYYYMMDD_HHMMSS` timestamp prefix from the remainder of a run
/// directory name. The fixed-width digit format makes the string itself
/// chronologically ordered, so it is returned as an owned sort key.
fn run_dir_timestamp(rest: &str) -> Option<&str> {
    if rest.len() < 15 {
        return None;
    }
    let ts = &rest[..15];
    let bytes = ts.as_bytes();
    let digits_ok = bytes.iter().enumerate().all(|(i, &b)| {
        if i == 8 {
            b == b'_'
        } else {
            b.is_ascii_digit()
        }
    });
    if digits_ok { Some(ts) } else { None }
}

/// Scans a wandb directory for run folders, sorted most recent first
/// (ties broken by name ascending).
pub fn scan_wandb_run_dirs(wandb_dir: &str) -> std::io::Result<Vec<String>> {
    if wandb_dir.is_empty() {
        return Ok(Vec::new());
    }
    let mut run_keys: Vec<String> = std::fs::read_dir(wandb_dir)?
        .flatten()
        .filter_map(|e| e.file_name().into_string().ok())
        .filter(|name| is_run_dir_name(name))
        .collect();

    run_keys.sort_by(|a, b| {
        let ts = |name: &str| -> String {
            let rest = name
                .strip_prefix("offline-run-")
                .or_else(|| name.strip_prefix("run-"))
                .unwrap_or("");
            run_dir_timestamp(rest).unwrap_or("").to_string()
        };
        ts(b).cmp(&ts(a)).then_with(|| a.cmp(b))
    });
    Ok(run_keys)
}

/// Spawns a thread that polls `wandb_dir` for run directories every
/// [`WANDB_DIR_POLL_INTERVAL`], sending `Msg::RunDirs` snapshots.
pub fn spawn_dir_scanner(wandb_dir: String, tx: Sender<Msg>) -> ReaderHandle {
    let source_id = next_source_id();
    let stop = Arc::new(AtomicBool::new(false));
    let stop2 = Arc::clone(&stop);

    std::thread::spawn(move || {
        while !stop2.load(Ordering::Relaxed) {
            let keys = scan_wandb_run_dirs(&wandb_dir).unwrap_or_default();
            if tx.send(Msg::RunDirs { keys }).is_err() {
                return;
            }
            // Sleep in small increments so stop is responsive.
            let deadline = Instant::now() + WANDB_DIR_POLL_INTERVAL;
            while Instant::now() < deadline {
                if stop2.load(Ordering::Relaxed) {
                    return;
                }
                std::thread::sleep(POLL_INTERVAL);
            }
        }
    });

    ReaderHandle { source_id, stop }
}

/// Locates the `.wandb` file inside a run directory.
pub fn wandb_file_in_run_dir(dir: &Path) -> Option<PathBuf> {
    let entries = std::fs::read_dir(dir).ok()?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().is_some_and(|e| e == "wandb") {
            return Some(path);
        }
    }
    None
}

#[allow(dead_code)]
pub fn system_time_secs(t: SystemTime) -> f64 {
    t.duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

//! Decodes a run's transaction log into columnar batches: one `Column` per
//! metric per batch, console output assembled into lines, and the run,
//! environment, summary, and exit records passed through. A consumer appends
//! slices per series instead of walking records, which is what keeps the UI
//! thread cheap while a large run loads.

use std::collections::HashMap;
use std::path::Path;
use std::sync::LazyLock;
use std::thread;
use std::time::{Duration, Instant};

use leet_proto::wandb_internal::{
    ConfigRecord, EnvironmentRecord, HistoryRecord, OutputRawRecord, Record, StatsRecord,
    SummaryRecord, output_raw_record, record,
};
use leet_wire::transaction_log::open_reader;
use regex::Regex;

const BOOT_FLUSH: Duration = Duration::from_millis(100);
const LIVE_FLUSH: Duration = Duration::from_millis(50);
const POLL: Duration = Duration::from_millis(500);
const MAX_CONSECUTIVE_ERRORS: usize = 64;

#[derive(Debug, Clone, Default)]
pub struct RunInfo {
    pub id: String,
    pub display_name: String,
    pub project: String,
    pub notes: String,
    pub tags: Vec<String>,
    pub config: Option<ConfigRecord>,
}

/// Values appended to one series. `key` indexes the run's key list, which
/// grows by each batch's new keys in order.
#[derive(Debug, Default)]
pub struct Column {
    pub key: usize,
    pub x: Vec<f64>,
    pub y: Vec<f64>,
}

#[derive(Debug, Clone)]
pub struct ConsoleLine {
    /// Unix seconds of the output record, when it carried a timestamp.
    pub time: Option<i64>,
    pub stderr: bool,
    pub text: String,
}

#[derive(Debug, Default)]
pub struct Batch {
    pub metric_keys: Vec<String>,
    pub metrics: Vec<Column>,
    pub system_keys: Vec<String>,
    pub system: Vec<Column>,
    pub console: Vec<ConsoleLine>,
    pub run: Option<RunInfo>,
    pub environment: Option<Box<EnvironmentRecord>>,
    pub summary: Vec<SummaryRecord>,
    pub exit_code: Option<i32>,
    /// The reader has read everything written so far.
    pub caught_up: bool,
    pub records: usize,
}

impl Batch {
    pub fn is_empty(&self) -> bool {
        self.records == 0 && self.exit_code.is_none()
    }
}

#[derive(Default)]
struct Columns {
    index: HashMap<String, usize>,
    pending: Vec<Column>,
    new_keys: Vec<String>,
}

impl Columns {
    fn push(&mut self, key: &str, x: f64, y: f64) {
        let id = match self.index.get(key) {
            Some(&id) => id,
            None => {
                let id = self.pending.len();
                self.index.insert(key.to_string(), id);
                self.new_keys.push(key.to_string());
                self.pending.push(Column {
                    key: id,
                    ..Default::default()
                });
                id
            }
        };
        self.pending[id].x.push(x);
        self.pending[id].y.push(y);
    }

    fn take(&mut self) -> (Vec<String>, Vec<Column>) {
        let columns = self
            .pending
            .iter_mut()
            .filter(|column| !column.x.is_empty())
            .map(|column| Column {
                key: column.key,
                x: std::mem::take(&mut column.x),
                y: std::mem::take(&mut column.y),
            })
            .collect();
        (std::mem::take(&mut self.new_keys), columns)
    }
}

static ANSI: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*(\x07|\x1b\\)").unwrap());

/// Turns raw output records into lines: escape sequences stripped, partial
/// lines joined across records, and a carriage return restarting the line
/// the way a terminal would show a progress bar's final state.
#[derive(Default)]
struct Console {
    partial: [String; 2],
}

impl Console {
    fn push(&mut self, output: &OutputRawRecord, lines: &mut Vec<ConsoleLine>) {
        let stderr = output.output_type == output_raw_record::OutputType::Stderr as i32;
        let time = output.timestamp.as_ref().map(|t| t.seconds);
        let text = ANSI.replace_all(&output.line, "");
        let partial = &mut self.partial[stderr as usize];
        for segment in text.split_inclusive('\n') {
            let (body, complete) = match segment.strip_suffix('\n') {
                Some(body) => (body, true),
                None => (segment, false),
            };
            let body = body.strip_suffix('\r').unwrap_or(body);
            match body.rfind('\r') {
                Some(ix) => {
                    partial.clear();
                    partial.push_str(&body[ix + 1..]);
                }
                None => partial.push_str(body),
            }
            if complete {
                lines.push(ConsoleLine {
                    time,
                    stderr,
                    text: std::mem::take(partial),
                });
            }
        }
    }
}

/// Accumulates decoded records into the next [`Batch`].
#[derive(Default)]
pub struct Decoder {
    metrics: Columns,
    system: Columns,
    console: Console,
    batch: Batch,
    exit_seen: bool,
}

impl Decoder {
    pub fn record(&mut self, record: Record) {
        self.batch.records += 1;
        let Some(record_type) = record.record_type else {
            return;
        };
        match record_type {
            record::RecordType::History(history) => self.history(&history),
            record::RecordType::Stats(stats) => self.stats(&stats),
            record::RecordType::OutputRaw(output) => {
                self.console.push(&output, &mut self.batch.console)
            }
            record::RecordType::Run(run) => {
                self.batch.run = Some(RunInfo {
                    id: run.run_id,
                    display_name: run.display_name,
                    project: run.project,
                    notes: run.notes,
                    tags: run.tags,
                    config: run.config,
                });
            }
            record::RecordType::Summary(summary) => self.batch.summary.push(summary),
            record::RecordType::Environment(environment) => {
                self.batch.environment = Some(Box::new(environment));
            }
            record::RecordType::Exit(exit) => {
                self.batch.exit_code = Some(exit.exit_code);
                self.exit_seen = true;
            }
            _ => {}
        }
    }

    /// Keys join nested paths with dots and skip the `_` internals, the same
    /// rules as `core/internal/leet/leveldbhistorysource.go`.
    fn history(&mut self, history: &HistoryRecord) {
        let mut step = history.step.as_ref().map_or(0.0, |s| s.num as f64);
        for item in &history.item {
            if item.key == "_step"
                && item.nested_key.is_empty()
                && let Ok(s) = item.value_json.parse::<f64>()
            {
                step = s;
            }
        }
        for item in &history.item {
            let joined;
            let key: &str = if item.nested_key.is_empty() {
                &item.key
            } else {
                joined = item.nested_key.join(".");
                &joined
            };
            if key.starts_with('_') {
                continue;
            }
            if let Ok(value) = item.value_json.parse::<f64>() {
                self.metrics.push(key, step, value);
            }
        }
    }

    fn stats(&mut self, stats: &StatsRecord) {
        let Some(timestamp) = &stats.timestamp else {
            return;
        };
        let t = timestamp.seconds as f64 + f64::from(timestamp.nanos) * 1e-9;
        for item in &stats.item {
            if let Ok(value) = item.value_json.parse::<f64>() {
                self.system.push(&item.key, t, value);
            }
        }
    }

    pub fn flush(&mut self, caught_up: bool) -> Batch {
        let (metric_keys, metrics) = self.metrics.take();
        let (system_keys, system) = self.system.take();
        let mut batch = std::mem::take(&mut self.batch);
        batch.metric_keys = metric_keys;
        batch.metrics = metrics;
        batch.system_keys = system_keys;
        batch.system = system;
        batch.caught_up = caught_up;
        batch
    }
}

/// Reads `path` to its end and keeps following it until the exit record has
/// been read or `sink` returns false. Batches are flushed every 100 ms while
/// catching up and every 50 ms after that; the first batch after catching up
/// is sent even when empty so the consumer learns the run is live.
pub fn follow(path: &Path, mut sink: impl FnMut(Batch) -> bool) {
    let mut reader = match open_reader(path) {
        Ok(reader) => reader,
        Err(err) => {
            eprintln!("leet: {}: {err}", path.display());
            return;
        }
    };
    let mut decoder = Decoder::default();
    let mut caught_up = false;
    let mut errors = 0;
    let mut last_flush = Instant::now();
    loop {
        match reader.read() {
            Ok(record) => {
                errors = 0;
                decoder.record(record);
                let interval = if caught_up { LIVE_FLUSH } else { BOOT_FLUSH };
                if last_flush.elapsed() >= interval {
                    if !sink(decoder.flush(caught_up)) {
                        return;
                    }
                    last_flush = Instant::now();
                }
            }
            Err(err) if err.is_eof() || err.is_unexpected_eof() => {
                if err.is_unexpected_eof() {
                    let _ = reader.reset_last_read();
                }
                let first = !caught_up;
                caught_up = true;
                if (first || !decoder.batch.is_empty()) && !sink(decoder.flush(true)) {
                    return;
                }
                if decoder.exit_seen {
                    return;
                }
                last_flush = Instant::now();
                thread::sleep(POLL);
            }
            Err(err) => {
                errors += 1;
                if errors >= MAX_CONSECUTIVE_ERRORS {
                    eprintln!(
                        "leet: {}: giving up after {errors} errors: {err}",
                        path.display()
                    );
                    return;
                }
            }
        }
    }
}

/// The run record from the head of the file, read without following it.
pub fn probe(path: &Path) -> Option<RunInfo> {
    let mut reader = open_reader(path).ok()?;
    let mut decoder = Decoder::default();
    for _ in 0..64 {
        decoder.record(reader.read().ok()?);
        if decoder.batch.run.is_some() {
            return decoder.flush(false).run;
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use leet_proto::wandb_internal::{HistoryItem, HistoryStep, StatsItem};
    use prost_types::Timestamp;

    fn history(step: i64, items: &[(&str, &str)]) -> Record {
        Record {
            record_type: Some(record::RecordType::History(HistoryRecord {
                step: Some(HistoryStep { num: step }),
                item: items
                    .iter()
                    .map(|(key, value)| HistoryItem {
                        key: key.to_string(),
                        value_json: value.to_string(),
                        ..Default::default()
                    })
                    .collect(),
                ..Default::default()
            })),
            ..Default::default()
        }
    }

    fn output(line: &str) -> Record {
        Record {
            record_type: Some(record::RecordType::OutputRaw(OutputRawRecord {
                line: line.to_string(),
                timestamp: Some(Timestamp {
                    seconds: 7,
                    nanos: 0,
                }),
                ..Default::default()
            })),
            ..Default::default()
        }
    }

    #[test]
    fn history_becomes_columns_with_stable_key_ids() {
        let mut decoder = Decoder::default();
        decoder.record(history(
            0,
            &[("loss", "1.5"), ("_runtime", "3"), ("text", "\"hi\"")],
        ));
        decoder.record(history(1, &[("acc", "0.5"), ("loss", "NaN")]));
        let first = decoder.flush(false);
        assert_eq!(first.metric_keys, ["loss", "acc"]);
        assert_eq!(first.metrics.len(), 2);
        assert_eq!(
            (first.metrics[0].key, &first.metrics[0].x[..]),
            (0, &[0.0, 1.0][..])
        );
        assert!(first.metrics[0].y[1].is_nan());
        assert_eq!(
            (first.metrics[1].key, &first.metrics[1].y[..]),
            (1, &[0.5][..])
        );

        decoder.record(history(2, &[("acc", "0.75")]));
        let second = decoder.flush(true);
        assert!(second.metric_keys.is_empty());
        assert_eq!(
            (second.metrics[0].key, &second.metrics[0].x[..]),
            (1, &[2.0][..])
        );
        assert!(second.caught_up);
    }

    #[test]
    fn stats_use_the_record_timestamp() {
        let mut decoder = Decoder::default();
        decoder.record(Record {
            record_type: Some(record::RecordType::Stats(StatsRecord {
                timestamp: Some(Timestamp {
                    seconds: 10,
                    nanos: 500_000_000,
                }),
                item: vec![StatsItem {
                    key: "gpu.0.temp".into(),
                    value_json: "61".into(),
                }],
                ..Default::default()
            })),
            ..Default::default()
        });
        let batch = decoder.flush(false);
        assert_eq!(batch.system_keys, ["gpu.0.temp"]);
        assert_eq!((batch.system[0].x[0], batch.system[0].y[0]), (10.5, 61.0));
    }

    #[test]
    fn console_lines_join_partials_and_honor_carriage_returns() {
        let mut decoder = Decoder::default();
        decoder.record(output("\x1b[32mhello\x1b[0m wor"));
        decoder.record(output("ld\nprogress 10%\rprogress 20%\r\ntail"));
        let batch = decoder.flush(false);
        let lines: Vec<&str> = batch.console.iter().map(|l| l.text.as_str()).collect();
        assert_eq!(lines, ["hello world", "progress 20%"]);
        assert_eq!(batch.console[0].time, Some(7));
    }
}

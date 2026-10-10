//! Decodes a run's transaction log into columnar batches: one `Column` per
//! metric per batch, console output assembled into lines, and the run,
//! environment, summary, and exit records passed through. A consumer appends
//! slices per series instead of walking records, which is what keeps the UI
//! thread cheap while a large run loads.
//!
//! A file that already exists is split into block-aligned ranges that are
//! framed and decoded on all cores and merged back in file order, so the
//! output is the same for any worker count; the tail is then followed on one
//! thread.

mod wire;

use std::collections::{BTreeMap, HashMap};
use std::fs::File;
use std::io::BufReader;
use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc;
use std::sync::{LazyLock, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use leet_proto::prost::Message;
use leet_proto::wandb_internal::{
    ConfigRecord, EnvironmentRecord, RunExitRecord, RunRecord, SummaryItem, SummaryRecord,
};
use leet_wire::transaction_log::{Reader, new_reader};
use regex::Regex;

use crate::wire::{Value, walk};

const BOOT_FLUSH: Duration = Duration::from_millis(100);
const LIVE_FLUSH: Duration = Duration::from_millis(50);
const POLL: Duration = Duration::from_millis(500);
const MAX_CONSECUTIVE_ERRORS: usize = 64;
const READ_BUFFER: usize = 4 << 20;
const BLOCK_SIZE: u64 = 32 << 10;
const RANGE_BYTES: u64 = 8 << 20;
const FIRST_RANGE_BYTES: u64 = 1 << 20;
const PARALLEL_MIN: u64 = 4 << 20;
const MAX_WORKERS: usize = 16;
const POOL_CAP: usize = 64;

#[derive(Debug, Clone, Default)]
pub struct RunInfo {
    pub id: String,
    pub display_name: String,
    pub project: String,
    pub notes: String,
    pub tags: Vec<String>,
    pub config: Option<ConfigRecord>,
}

/// One series' slice of a [`ColumnSet`]. `key` indexes the run's key list,
/// which grows by each batch's new keys in order.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Column {
    pub key: usize,
    pub start: usize,
    pub end: usize,
}

/// The columns of one batch, packed back to back in `x` and `y` so a batch
/// is two allocations however many series it touches.
#[derive(Debug, Default)]
pub struct ColumnSet {
    pub new_keys: Vec<String>,
    pub columns: Vec<Column>,
    pub x: Vec<f64>,
    pub y: Vec<f64>,
}

impl ColumnSet {
    pub fn slices(&self, column: &Column) -> (&[f64], &[f64]) {
        (
            &self.x[column.start..column.end],
            &self.y[column.start..column.end],
        )
    }

    /// A set with buffers from the pool, sized for `total` points.
    fn with_capacity(total: usize) -> Self {
        let (mut x, mut y, mut columns) = POOL
            .lock()
            .ok()
            .and_then(|mut pool| pool.pop())
            .unwrap_or_default();
        x.clear();
        y.clear();
        columns.clear();
        x.resize(total, 0.0);
        y.resize(total, 0.0);
        ColumnSet {
            new_keys: Vec::new(),
            columns,
            x,
            y,
        }
    }
}

/// Buffers of consumed batches, reused by the decoders. Freeing a buffer that
/// another thread filled costs milliseconds on macOS; handing it back costs
/// nothing.
type Buffers = (Vec<f64>, Vec<f64>, Vec<Column>);
static POOL: LazyLock<Mutex<Vec<Buffers>>> = LazyLock::new(Mutex::default);

impl Batch {
    /// Returns the batch's buffers to the decoders once its contents have
    /// been copied out.
    pub fn recycle(self) {
        let Ok(mut pool) = POOL.lock() else {
            return;
        };
        for set in [self.metrics, self.system] {
            if pool.len() < POOL_CAP && set.x.capacity() > 0 {
                pool.push((set.x, set.y, set.columns));
            }
        }
    }
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
    pub metrics: ColumnSet,
    pub system: ColumnSet,
    pub console: Vec<ConsoleLine>,
    pub run: Option<RunInfo>,
    pub environment: Option<Box<EnvironmentRecord>>,
    /// At most one record: the summary updates and removals of this batch,
    /// collapsed so a key appears once with its last value.
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

/// Per-metric columns under construction. Items arrive as a flat list and
/// are bucketed by key when settled, so decoding a record costs two appends
/// per item rather than a hash lookup and a push into one of thousands of
/// small vectors.
#[derive(Default)]
struct Columns {
    index: HashMap<Vec<u8>, usize>,
    keys: Vec<String>,
    flushed_keys: usize,
    /// The key seen at each item position of the previous record; records
    /// usually repeat their key order, which makes the id a byte compare.
    positional: Vec<(Vec<u8>, usize)>,
    items: Vec<(u32, f64, f64)>,
}

impl Columns {
    fn intern(&mut self, key: &[u8]) -> usize {
        if let Some(&id) = self.index.get(key) {
            return id;
        }
        let id = self.keys.len();
        self.index.insert(key.to_vec(), id);
        self.keys.push(String::from_utf8_lossy(key).into_owned());
        id
    }

    fn id_at(&mut self, position: usize, key: &[u8]) -> usize {
        if let Some((cached, id)) = self.positional.get(position)
            && cached == key
        {
            return *id;
        }
        let id = self.intern(key);
        let known = self.positional.len();
        match self.positional.get_mut(position) {
            Some(slot) => {
                slot.0.clear();
                slot.0.extend_from_slice(key);
                slot.1 = id;
            }
            None if position == known => self.positional.push((key.to_vec(), id)),
            None => {}
        }
        id
    }

    fn push(&mut self, position: usize, key: &[u8], x: f64, y: f64) {
        let id = self.id_at(position, key);
        self.items.push((id as u32, x, y));
    }

    /// Keys interned since the last batch, in id order.
    fn new_keys(&mut self) -> Vec<String> {
        let keys = self.keys[self.flushed_keys..].to_vec();
        self.flushed_keys = self.keys.len();
        keys
    }

    /// Buckets the items so far into packed columns, in key order.
    fn settle(&mut self) -> ColumnSet {
        let mut counts = vec![0usize; self.keys.len()];
        for (id, _, _) in &self.items {
            counts[*id as usize] += 1;
        }
        let mut set = ColumnSet::with_capacity(self.items.len());
        let mut offsets = vec![0usize; self.keys.len()];
        let mut total = 0;
        for (key, count) in counts.iter().enumerate().filter(|(_, count)| **count > 0) {
            offsets[key] = total;
            set.columns.push(Column {
                key,
                start: total,
                end: total + count,
            });
            total += count;
        }
        for &(id, xv, yv) in &self.items {
            let at = &mut offsets[id as usize];
            set.x[*at] = xv;
            set.y[*at] = yv;
            *at += 1;
        }
        self.items.clear();
        set.new_keys = self.new_keys();
        set
    }

    /// Renames a set from another interner, whose keys are all listed in
    /// `new_keys` in local id order, to this interner's ids.
    fn rename(&mut self, mut set: ColumnSet) -> ColumnSet {
        let ids: Vec<usize> = set
            .new_keys
            .iter()
            .map(|key| self.intern(key.as_bytes()))
            .collect();
        for column in &mut set.columns {
            column.key = ids[column.key];
        }
        set.new_keys = self.new_keys();
        set
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
    fn push(&mut self, time: Option<i64>, stderr: bool, raw: &str, lines: &mut Vec<ConsoleLine>) {
        let text = ANSI.replace_all(raw, "");
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

/// A raw console record, assembled into lines only once chunks are merged
/// back in order.
struct Output {
    time: Option<i64>,
    stderr: bool,
    text: String,
}

/// One history item of the record being decoded. Nested keys are joined with
/// dots into the decoder's scratch arena and referenced by offset.
struct Item<'a> {
    plain: &'a [u8],
    joined: std::ops::Range<usize>,
    nested: bool,
    value: Option<&'a [u8]>,
}

impl<'a> Item<'a> {
    fn parse(item: &'a [u8], scratch: &mut Vec<u8>) -> Self {
        let start = scratch.len();
        let mut parsed = Item {
            plain: &[],
            joined: start..start,
            nested: false,
            value: None,
        };
        walk(item, |tag, v| match (tag, v) {
            (1, Value::Bytes(k)) => parsed.plain = k,
            (2, Value::Bytes(part)) => {
                if parsed.nested {
                    scratch.push(b'.');
                }
                scratch.extend_from_slice(part);
                parsed.nested = true;
            }
            (16, Value::Bytes(json)) => parsed.value = Some(json),
            _ => {}
        });
        parsed.joined = start..scratch.len();
        parsed
    }

    fn key<'s>(&self, scratch: &'s [u8]) -> &'s [u8]
    where
        'a: 's,
    {
        if self.nested {
            &scratch[self.joined.clone()]
        } else {
            self.plain
        }
    }
}

/// Accumulates decoded records into the next [`Batch`].
#[derive(Default)]
pub struct Decoder {
    metrics: Columns,
    system: Columns,
    outputs: Vec<Output>,
    console: Console,
    scratch: Vec<u8>,
    summary: Summary,
    batch: Batch,
    exit_seen: bool,
}

impl Decoder {
    /// Decodes one serialized `Record`.
    pub fn record(&mut self, bytes: &[u8]) {
        self.batch.records += 1;
        walk(bytes, |tag, value| {
            let Value::Bytes(payload) = value else {
                return;
            };
            match tag {
                2 => self.history(payload),
                7 => self.stats(payload),
                13 => self.output(payload),
                3 => self.summary.record(payload),
                17 => {
                    if let Ok(run) = RunRecord::decode(payload) {
                        self.batch.run = Some(RunInfo {
                            id: run.run_id,
                            display_name: run.display_name,
                            project: run.project,
                            notes: run.notes,
                            tags: run.tags,
                            config: run.config,
                        });
                    }
                }
                18 => {
                    if let Ok(exit) = RunExitRecord::decode(payload) {
                        self.batch.exit_code = Some(exit.exit_code);
                        self.exit_seen = true;
                    }
                }
                26 => {
                    if let Ok(environment) = EnvironmentRecord::decode(payload) {
                        self.batch.environment = Some(Box::new(environment));
                    }
                }
                _ => {}
            }
        });
    }

    /// Keys join nested paths with dots and skip the `_` internals, the same
    /// rules as `core/internal/leet/leveldbhistorysource.go`; a `_step` item
    /// overrides the record's step.
    fn history(&mut self, buf: &[u8]) {
        let mut record_step = 0.0;
        let mut step_item = None;
        let mut items: Vec<Item> = Vec::new();
        self.scratch.clear();
        walk(buf, |tag, value| match (tag, value) {
            (2, Value::Bytes(step_msg)) => {
                walk(step_msg, |tag, value| {
                    if let (1, Value::Varint(num)) = (tag, value) {
                        record_step = num as i64 as f64;
                    }
                });
            }
            (1, Value::Bytes(item)) => {
                let item = Item::parse(item, &mut self.scratch);
                if item.key(&self.scratch) == b"_step" && !item.nested {
                    step_item = item.value.and_then(wire::number);
                } else {
                    items.push(item);
                }
            }
            _ => {}
        });
        let step = step_item.unwrap_or(record_step);
        for (position, item) in items.iter().enumerate() {
            let key = item.key(&self.scratch);
            if key.first() == Some(&b'_') {
                continue;
            }
            if let Some(v) = item.value.and_then(wire::number) {
                self.metrics.push(position, key, step, v);
            }
        }
    }

    fn stats(&mut self, buf: &[u8]) {
        let mut time = None;
        walk(buf, |tag, value| {
            if let (2, Value::Bytes(ts)) = (tag, value) {
                time = wire::timestamp(ts);
            }
        });
        let Some(time) = time else {
            return;
        };
        let mut position = 0;
        walk(buf, |tag, value| {
            if let (3, Value::Bytes(item)) = (tag, value) {
                let mut key: &[u8] = &[];
                let mut number = None;
                walk(item, |tag, v| match (tag, v) {
                    (1, Value::Bytes(k)) => key = k,
                    (16, Value::Bytes(json)) => number = wire::number(json),
                    _ => {}
                });
                if let Some(v) = number {
                    self.system.push(position, key, time, v);
                }
                position += 1;
            }
        });
    }

    fn output(&mut self, buf: &[u8]) {
        let mut output = Output {
            time: None,
            stderr: false,
            text: String::new(),
        };
        walk(buf, |tag, value| match (tag, value) {
            (1, Value::Varint(kind)) => output.stderr = kind == 0,
            (2, Value::Bytes(ts)) => output.time = wire::timestamp(ts).map(|t| t as i64),
            (3, Value::Bytes(line)) => output.text = String::from_utf8_lossy(line).into_owned(),
            _ => {}
        });
        self.outputs.push(output);
    }

    /// Everything decoded so far, settled on this thread, for another decoder
    /// to adopt.
    fn finish(mut self) -> Part {
        Part {
            metrics: self.metrics.settle(),
            system: self.system.settle(),
            outputs: self.outputs,
            summary: self
                .summary
                .take_record()
                .map(|record| record.encode_to_vec())
                .unwrap_or_default(),
            batch: self.batch,
            exit_seen: self.exit_seen,
        }
    }

    /// The batch for a part decoded elsewhere: its keys renamed to this
    /// decoder's ids and its console output assembled after everything that
    /// came before. Columns move; nothing is copied.
    fn adopt(&mut self, part: Part) -> Batch {
        let Part {
            metrics,
            system,
            outputs,
            summary,
            mut batch,
            exit_seen,
        } = part;
        batch.metrics = self.metrics.rename(metrics);
        batch.system = self.system.rename(system);
        self.summary.record(&summary);
        for output in outputs {
            self.console
                .push(output.time, output.stderr, &output.text, &mut batch.console);
        }
        self.exit_seen |= exit_seen;
        batch
    }

    pub fn flush(&mut self, caught_up: bool) -> Batch {
        for output in std::mem::take(&mut self.outputs) {
            self.console.push(
                output.time,
                output.stderr,
                &output.text,
                &mut self.batch.console,
            );
        }
        let mut batch = std::mem::take(&mut self.batch);
        batch.metrics = self.metrics.settle();
        batch.system = self.system.settle();
        batch.summary = self.summary.take_record().into_iter().collect();
        batch.caught_up = caught_up;
        batch
    }
}

/// The latest summary value per path, folded from the summary records'
/// updates and removals. Records repeat their key order, so a key resolves
/// by position without hashing, and values are overwritten in place.
#[derive(Default)]
struct Summary {
    index: HashMap<Vec<u8>, usize>,
    paths: Vec<Vec<String>>,
    /// The latest `value_json`; `None` once removed.
    values: Vec<Option<Vec<u8>>>,
    changed: Vec<usize>,
    flagged: Vec<bool>,
    positional: Vec<(Vec<u8>, usize)>,
    scratch: Vec<u8>,
}

impl Summary {
    /// Folds one serialized `SummaryRecord`.
    fn record(&mut self, buf: &[u8]) {
        let mut position = 0;
        walk(buf, |tag, value| {
            if let (1 | 2, Value::Bytes(item)) = (tag, value) {
                self.item(item, tag == 2, position);
                position += 1;
            }
        });
    }

    fn item(&mut self, item: &[u8], removed: bool, position: usize) {
        let mut key: &[u8] = &[];
        let mut nested = 0;
        let mut value: &[u8] = &[];
        self.scratch.clear();
        walk(item, |tag, v| match (tag, v) {
            (1, Value::Bytes(k)) => key = k,
            (2, Value::Bytes(part)) => {
                if nested > 0 {
                    self.scratch.push(0x1f);
                }
                self.scratch.extend_from_slice(part);
                nested += 1;
            }
            (16, Value::Bytes(json)) => value = json,
            _ => {}
        });
        let path: &[u8] = if nested > 0 { &self.scratch } else { key };
        let id = match self.positional.get(position) {
            Some((cached, id)) if cached == path => *id,
            _ => {
                let id = match self.index.get(path) {
                    Some(&id) => id,
                    None => {
                        let id = self.paths.len();
                        self.index.insert(path.to_vec(), id);
                        let components = if nested > 0 {
                            path.split(|b| *b == 0x1f)
                                .map(|c| String::from_utf8_lossy(c).into_owned())
                                .collect()
                        } else {
                            vec![String::from_utf8_lossy(key).into_owned()]
                        };
                        self.paths.push(components);
                        self.values.push(None);
                        self.flagged.push(false);
                        id
                    }
                };
                if position == self.positional.len() {
                    self.positional.push((path.to_vec(), id));
                } else if let Some(slot) = self.positional.get_mut(position) {
                    slot.0.clear();
                    slot.0.extend_from_slice(path);
                    slot.1 = id;
                }
                id
            }
        };
        if removed {
            self.values[id] = None;
        } else {
            let slot = self.values[id].get_or_insert_with(Vec::new);
            slot.clear();
            slot.extend_from_slice(value);
        }
        if !self.flagged[id] {
            self.flagged[id] = true;
            self.changed.push(id);
        }
    }

    /// The updates and removals since the last call as one record.
    fn take_record(&mut self) -> Option<SummaryRecord> {
        if self.changed.is_empty() {
            return None;
        }
        let mut record = SummaryRecord::default();
        for id in std::mem::take(&mut self.changed) {
            self.flagged[id] = false;
            let path = &self.paths[id];
            let (key, nested_key) = match path.as_slice() {
                [key] => (key.clone(), Vec::new()),
                _ => (String::new(), path.clone()),
            };
            match &self.values[id] {
                Some(value) => record.update.push(SummaryItem {
                    key,
                    nested_key,
                    value_json: String::from_utf8_lossy(value).into_owned(),
                }),
                None => record.remove.push(SummaryItem {
                    key,
                    nested_key,
                    ..Default::default()
                }),
            }
        }
        Some(record)
    }
}

/// A decoded stretch of the file, settled but with its own key ids.
struct Part {
    metrics: ColumnSet,
    system: ColumnSet,
    outputs: Vec<Output>,
    /// The part's summary changes as one encoded `SummaryRecord`, folded into
    /// the adopting decoder's state rather than handed to the consumer.
    summary: Vec<u8>,
    batch: Batch,
    exit_seen: bool,
}

/// Block-aligned byte ranges covering `[0, size)`: a few small ones first so
/// the first batch lands quickly, then about `range_bytes` each.
fn ranges(size: u64, range_bytes: u64) -> Vec<(i64, i64)> {
    let blocks = |bytes: u64| bytes.max(BLOCK_SIZE) / BLOCK_SIZE * BLOCK_SIZE;
    let mut ranges = Vec::new();
    let mut start = 0;
    let mut step = blocks(FIRST_RANGE_BYTES.min(range_bytes));
    while start < size {
        let end = (start + step).min(size);
        ranges.push((start as i64, end as i64));
        start = end;
        step = (step * 2).min(blocks(range_bytes));
    }
    ranges
}

struct RangeResult {
    part: Part,
    /// Where a reader continues after this range: the next record start, or
    /// the start of a record cut short by the end of the file.
    resume: i64,
}

/// Frames and decodes the records that start inside `[start, end)`. A record
/// spilling past `end` belongs to this range; a reader seeking to `end` skips
/// its continuation chunks.
fn decode_range(path: &Path, start: i64, end: i64) -> Option<RangeResult> {
    let mut reader = open(path)?;
    if start > 0 {
        reader.seek_record(start).ok()?;
    }
    let mut decoder = Decoder::default();
    let mut errors = 0;
    let resume = loop {
        if reader.next_offset() >= end {
            break reader.next_offset();
        }
        match reader.read_raw_ref() {
            Ok(record) => {
                errors = 0;
                decoder.record(record);
            }
            Err(err) if err.is_eof() || err.is_unexpected_eof() => break reader.last_read_offset(),
            Err(_) => {
                errors += 1;
                if errors >= MAX_CONSECUTIVE_ERRORS {
                    break reader.next_offset();
                }
            }
        }
    };
    Some(RangeResult {
        part: decoder.finish(),
        resume,
    })
}

/// Decodes `[0, size)` on a pool and hands each range to `sink` in file
/// order as its own batch. Returns the offset to continue from, or `None`
/// when `sink` asked to stop.
fn load_parallel(
    path: &Path,
    size: u64,
    range_bytes: u64,
    decoder: &mut Decoder,
    sink: &mut impl FnMut(Batch) -> bool,
) -> Option<i64> {
    let ranges = ranges(size, range_bytes);
    let cores = thread::available_parallelism().map_or(4, |n| n.get());
    let workers = cores
        .saturating_sub(2)
        .clamp(1, MAX_WORKERS)
        .min(ranges.len());
    let next = AtomicUsize::new(0);
    let (tx, rx) = mpsc::channel();
    let mut resume = 0;
    let mut stopped = false;
    thread::scope(|scope| {
        for _ in 0..workers {
            let tx = tx.clone();
            let (next, ranges) = (&next, &ranges);
            scope.spawn(move || {
                loop {
                    let ix = next.fetch_add(1, Ordering::Relaxed);
                    let Some(&(start, end)) = ranges.get(ix) else {
                        return;
                    };
                    if tx.send((ix, decode_range(path, start, end))).is_err() {
                        return;
                    }
                }
            });
        }
        drop(tx);
        let mut pending = BTreeMap::new();
        let mut merged = 0;
        while merged < ranges.len() {
            let Ok((ix, result)) = rx.recv() else {
                break;
            };
            pending.insert(ix, result);
            while let Some(result) = pending.remove(&merged) {
                let Some(result) = result else {
                    return;
                };
                resume = result.resume;
                merged += 1;
                if !sink(decoder.adopt(result.part)) {
                    stopped = true;
                    return;
                }
            }
        }
    });
    (!stopped).then_some(resume)
}

fn open(path: &Path) -> Option<Reader<BufReader<File>>> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(err) => {
            eprintln!("leet: {}: {err}", path.display());
            return None;
        }
    };
    match new_reader(BufReader::with_capacity(READ_BUFFER, file)) {
        Ok(reader) => Some(reader),
        Err(err) => {
            eprintln!("leet: {}: {err}", path.display());
            None
        }
    }
}

/// Reads `path` to its end and, when `tail` is set, keeps following it until
/// the exit record has been read. Stops early when `sink` returns false.
/// Batches are flushed every 100 ms while catching up and every 50 ms after
/// that; the first batch after catching up is sent even when empty so the
/// consumer learns the run is live.
fn read(path: &Path, tail: bool, mut sink: impl FnMut(Batch) -> bool) {
    let mut decoder = Decoder::default();
    let mut resume = 0;
    let size = std::fs::metadata(path).map_or(0, |m| m.len());
    if size >= PARALLEL_MIN {
        match load_parallel(path, size, RANGE_BYTES, &mut decoder, &mut sink) {
            Some(offset) => resume = offset,
            None => return,
        }
    }
    let Some(mut reader) = open(path) else {
        return;
    };
    if resume > 0 && reader.seek_record(resume).is_err() {
        return;
    }
    let mut caught_up = false;
    let mut errors = 0;
    let mut last_flush = Instant::now();
    loop {
        match reader.read_raw_ref() {
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
                if decoder.exit_seen || !tail {
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

/// Follows a run until its exit record has been read; see [`read`].
pub fn follow(path: &Path, sink: impl FnMut(Batch) -> bool) {
    read(path, true, sink);
}

/// Decodes a file as it is now, without following it.
pub fn decode(path: &Path, sink: impl FnMut(Batch) -> bool) {
    read(path, false, sink);
}

/// The run record from the head of the file, read without following it.
pub fn probe(path: &Path) -> Option<RunInfo> {
    let mut reader = open(path)?;
    let mut decoder = Decoder::default();
    for _ in 0..64 {
        decoder.record(reader.read_raw_ref().ok()?);
        if decoder.batch.run.is_some() {
            return decoder.flush(false).run;
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use leet_proto::prost::Message;
    use leet_proto::wandb_internal::{
        HistoryItem, HistoryRecord, HistoryStep, OutputRawRecord, Record, StatsItem, StatsRecord,
        record,
    };
    use prost_types::Timestamp;

    fn history(step: i64, items: &[(&str, &str)]) -> Vec<u8> {
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
        .encode_to_vec()
    }

    fn output(line: &str) -> Vec<u8> {
        Record {
            record_type: Some(record::RecordType::OutputRaw(OutputRawRecord {
                line: line.to_string(),
                output_type: 1,
                timestamp: Some(Timestamp {
                    seconds: 7,
                    nanos: 0,
                }),
                ..Default::default()
            })),
            ..Default::default()
        }
        .encode_to_vec()
    }

    fn column<'a>(set: &'a ColumnSet, key: usize) -> (&'a [f64], &'a [f64]) {
        let column = set
            .columns
            .iter()
            .find(|c| c.key == key)
            .expect("column for key");
        set.slices(column)
    }

    #[test]
    fn history_becomes_columns_with_stable_key_ids() {
        let mut decoder = Decoder::default();
        decoder.record(&history(
            0,
            &[("loss", "1.5"), ("_runtime", "3"), ("text", "\"hi\"")],
        ));
        decoder.record(&history(1, &[("acc", "0.5"), ("loss", "NaN")]));
        let first = decoder.flush(false).metrics;
        assert_eq!(first.new_keys, ["loss", "acc"]);
        assert_eq!(first.columns.len(), 2);
        let (x, y) = column(&first, 0);
        assert_eq!(x, [0.0, 1.0]);
        assert!(y[1].is_nan());
        assert_eq!(column(&first, 1).1, [0.5]);

        decoder.record(&history(2, &[("acc", "0.75")]));
        let second = decoder.flush(true);
        assert!(second.metrics.new_keys.is_empty());
        assert_eq!(column(&second.metrics, 1).0, [2.0]);
        assert!(second.caught_up);
    }

    #[test]
    fn nested_keys_join_and_step_item_wins() {
        let record = Record {
            record_type: Some(record::RecordType::History(HistoryRecord {
                step: Some(HistoryStep { num: 4 }),
                item: vec![
                    HistoryItem {
                        key: "_step".into(),
                        value_json: "9".into(),
                        ..Default::default()
                    },
                    HistoryItem {
                        nested_key: vec!["train".into(), "loss".into()],
                        value_json: "2".into(),
                        ..Default::default()
                    },
                ],
                ..Default::default()
            })),
            ..Default::default()
        }
        .encode_to_vec();
        let mut decoder = Decoder::default();
        decoder.record(&record);
        let set = decoder.flush(false).metrics;
        assert_eq!(set.new_keys, ["train.loss"]);
        assert_eq!(column(&set, 0), (&[9.0][..], &[2.0][..]));
    }

    #[test]
    fn adopted_parts_share_key_ids_in_order() {
        let mut first = Decoder::default();
        first.record(&history(0, &[("a", "1")]));
        first.record(&history(1, &[("b", "2")]));
        let mut second = Decoder::default();
        second.record(&history(2, &[("b", "3"), ("a", "4")]));
        let mut merger = Decoder::default();
        let set = merger.adopt(first.finish()).metrics;
        assert_eq!(set.new_keys, ["a", "b"]);
        assert_eq!(column(&set, 0).1, [1.0]);
        let batch = merger.adopt(second.finish());
        assert!(batch.metrics.new_keys.is_empty());
        assert_eq!(column(&batch.metrics, 1).1, [3.0]);
        assert_eq!(column(&batch.metrics, 0).1, [4.0]);
        assert_eq!(batch.records, 1);
    }

    /// Every batch's columns folded into one table, for comparing two decodes.
    fn collect(
        path: &Path,
        range_bytes: Option<u64>,
    ) -> (usize, BTreeMap<String, (Vec<f64>, Vec<f64>)>) {
        let mut keys: Vec<String> = Vec::new();
        let mut table: BTreeMap<String, (Vec<f64>, Vec<f64>)> = BTreeMap::new();
        let mut records = 0;
        let mut sink = |batch: Batch| {
            records += batch.records;
            keys.extend(batch.metrics.new_keys.iter().cloned());
            for column in &batch.metrics.columns {
                let (x, y) = batch.metrics.slices(column);
                let entry = table.entry(keys[column.key].clone()).or_default();
                entry.0.extend_from_slice(x);
                entry.1.extend_from_slice(y);
            }
            true
        };
        match range_bytes {
            Some(range_bytes) => {
                let size = std::fs::metadata(path).unwrap().len();
                let mut decoder = Decoder::default();
                load_parallel(path, size, range_bytes, &mut decoder, &mut sink);
                sink(decoder.flush(true));
            }
            None => decode(path, sink),
        }
        (records, table)
    }

    #[test]
    fn parallel_ranges_decode_the_same_as_one_pass() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("run-abc.wandb");
        let mut writer = leet_wire::transaction_log::open_writer(&path).unwrap();
        let filler = format!("\"{}\"", "x".repeat(700));
        for step in 0..3000 {
            let mut items: Vec<(String, String)> = (0..6)
                .map(|m| (format!("m{m}"), format!("{}", step * m)))
                .collect();
            items.push(("note".into(), filler.clone()));
            let items: Vec<(&str, &str)> = items
                .iter()
                .map(|(k, v)| (k.as_str(), v.as_str()))
                .collect();
            let record = Record::decode(&history(step, &items)[..]).unwrap();
            writer.write(&record).unwrap();
        }
        writer.close().unwrap();

        let sequential = collect(&path, None);
        let parallel = collect(&path, Some(64 << 10));
        assert_eq!(sequential.0, 3000);
        assert_eq!(parallel, sequential);
    }

    fn summary(update: &[(&str, &str)], remove: &[&str]) -> Vec<u8> {
        let item = |key: &str, value: &str| SummaryItem {
            key: key.to_string(),
            value_json: value.to_string(),
            ..Default::default()
        };
        Record {
            record_type: Some(record::RecordType::Summary(SummaryRecord {
                update: update.iter().map(|(k, v)| item(k, v)).collect(),
                remove: remove.iter().map(|k| item(k, "")).collect(),
                ..Default::default()
            })),
            ..Default::default()
        }
        .encode_to_vec()
    }

    #[test]
    fn summary_folds_to_the_latest_value_per_key() {
        let mut worker = Decoder::default();
        worker.record(&summary(&[("loss", "1"), ("acc", "0.1")], &[]));
        worker.record(&summary(&[("loss", "2")], &["acc"]));
        let mut merger = Decoder::default();
        merger.adopt(worker.finish());
        merger.record(&summary(&[("acc", "0.9")], &[]));
        let folded = merger.flush(true).summary;
        assert_eq!(folded.len(), 1);
        let updates: Vec<(&str, &str)> = folded[0]
            .update
            .iter()
            .map(|i| (i.key.as_str(), i.value_json.as_str()))
            .collect();
        assert_eq!(updates, [("loss", "2"), ("acc", "0.9")]);
        assert!(folded[0].remove.is_empty());
        assert!(merger.flush(true).summary.is_empty());
    }

    #[test]
    fn stats_use_the_record_timestamp() {
        let record = Record {
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
        }
        .encode_to_vec();
        let mut decoder = Decoder::default();
        decoder.record(&record);
        let set = decoder.flush(false).system;
        assert_eq!(set.new_keys, ["gpu.0.temp"]);
        assert_eq!(column(&set, 0), (&[10.5][..], &[61.0][..]));
    }

    #[test]
    fn console_lines_join_partials_and_honor_carriage_returns() {
        let mut decoder = Decoder::default();
        decoder.record(&output("\x1b[32mhello\x1b[0m wor"));
        decoder.record(&output("ld\nprogress 10%\rprogress 20%\r\ntail"));
        let batch = decoder.flush(false);
        let lines: Vec<&str> = batch.console.iter().map(|l| l.text.as_str()).collect();
        assert_eq!(lines, ["hello world", "progress 20%"]);
        assert_eq!(batch.console[0].time, Some(7));
        assert!(!batch.console[0].stderr);
    }
}

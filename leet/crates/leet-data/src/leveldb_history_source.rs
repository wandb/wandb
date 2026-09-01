//! Port of `core/internal/leet/leveldbhistorysource.go` — reading records
//! from a W&B LevelDB-style transaction log (.wandb file).

use std::collections::HashMap;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use leet_proto::wandb_internal::{self, output_raw_record, record};
use leet_wire::live_store::{LiveStore, LiveStoreError};

use crate::history_source::{
    ChunkedBatchMsg, ConsoleLogMsg, FileCompleteMsg, HistoryMsg, HistorySource, HistorySourceError,
    MetricData, RunMsg, SourceMsg, StatsMsg, SummaryMsg, SystemInfoMsg, concatenate_history,
    concatenate_summary,
};
use crate::media::{MediaPoint, resolve_media_path};

/// LevelDBHistorySource handles reading records from a W&B LevelDB-style transaction log (.wandb file).
// PARITY: Go guards this with `mu sync.Mutex` because reads happen on tea.Cmd
// goroutines that could overlap; per docs/CONCURRENCY.md (S6) the Rust port
// gives the source to a single reader thread, so the mutex dies and
// `&mut self` enforces exclusive access.
#[derive(Debug)]
pub struct LevelDBHistorySource {
    run_path: String,

    /// store is a W&B LevelDB-style transaction log that may be actively
    /// written. (Go: nil after Close.)
    store: Option<LiveStore>,
    /// exit_seen is true if the exit record has been seen.
    exit_seen: bool,
    /// exit_code is the exit code of the run if the exit record has been seen.
    exit_code: i32,
    /// file_complete_emitted is true after the terminal FileCompleteMsg has been emitted.
    file_complete_emitted: bool,
}

impl LevelDBHistorySource {
    /// Go: `NewLevelDBHistorySource`.
    // PARITY: the Go constructor takes an *observability.CoreLogger for the
    // LiveStore; the Rust port logs via `tracing` at the same call sites
    // (workspace convention, see leet-wire).
    pub fn new(run_path: &str) -> Result<LevelDBHistorySource, LiveStoreError> {
        let store = LiveStore::new(run_path)?;
        Ok(LevelDBHistorySource {
            run_path: run_path.to_string(),
            store: Some(store),
            exit_seen: false,
            exit_code: 0,
            file_complete_emitted: false,
        })
    }

    // PARITY: Go's InitializeLevelDBHistorySource returns a tea.Cmd producing
    // InitMsg{Source} or ErrorMsg. The command wrapper and InitMsg port to
    // leet-tui with messages.go; on failure it must reproduce Go's exact
    // error string: "leveldbhistory: failed to create live store: {err}".

    /// recordToMsg converts a record to the appropriate message type.
    fn record_to_msg(&self, record: wandb_internal::Record) -> Option<SourceMsg> {
        match record.record_type? {
            record::RecordType::Run(run) => Some(SourceMsg::Run(RunMsg {
                run_path: self.run_path.clone(),
                id: run.run_id,
                display_name: run.display_name,
                project: run.project,
                notes: run.notes,
                // PARITY: Go slices.Clone(rec.Run.GetTags()); the record is
                // owned here, so moving the vec is the same copy-at-boundary.
                tags: run.tags,
                config: run.config,
            })),
            record::RecordType::History(history) => parse_history(&self.run_path, &history),
            record::RecordType::Stats(stats) => parse_stats(&self.run_path, &stats),
            record::RecordType::Summary(summary) => Some(SourceMsg::Summary(SummaryMsg {
                run_path: self.run_path.clone(),
                summary: vec![summary],
            })),
            record::RecordType::Environment(environment) => {
                Some(SourceMsg::SystemInfo(Box::new(SystemInfoMsg {
                    run_path: self.run_path.clone(),
                    record: environment,
                })))
            }
            record::RecordType::OutputRaw(output_raw) => {
                Some(parse_output_raw(&self.run_path, output_raw))
            }
            _ => None,
        }
    }
}

impl HistorySource for LevelDBHistorySource {
    /// Read implements HistorySource.Read.
    fn read(
        &mut self,
        chunk_size: usize,
        max_time_per_chunk: Duration,
    ) -> (Option<SourceMsg>, Option<HistorySourceError>) {
        if self.store.is_none() {
            return (
                Some(SourceMsg::ChunkedBatch(ChunkedBatchMsg {
                    msgs: Vec::new(),
                    has_more: false,
                    progress: 0,
                })),
                None,
            );
        }
        if self.exit_seen && self.file_complete_emitted {
            return (
                Some(SourceMsg::ChunkedBatch(ChunkedBatchMsg {
                    msgs: Vec::new(),
                    has_more: false,
                    progress: 0,
                })),
                Some(HistorySourceError::Eof),
            );
        }

        let mut msgs: Vec<SourceMsg> = Vec::new();
        let mut histories: Vec<HistoryMsg> = Vec::new();
        let mut summaries: Vec<SummaryMsg> = Vec::new();
        let mut scanned_count: usize = 0;
        let start_time = Instant::now();
        let mut err: Option<HistorySourceError> = None;

        while scanned_count < chunk_size && start_time.elapsed() < max_time_per_chunk {
            // (Re-borrowed per iteration; nil-checked at the top like Go.)
            let read_result = self
                .store
                .as_mut()
                .expect("store checked non-nil above")
                .read();
            let record = match read_result {
                Ok(record) => record,
                Err(read_err) => {
                    if read_err.is_eof() {
                        if self.exit_seen {
                            err = Some(HistorySourceError::Eof);
                        } else {
                            err = None;
                        }
                    } else {
                        err = Some(HistorySourceError::LiveStore(read_err));
                    }
                    break;
                }
            };
            // PARITY: Go `if record == nil { continue }` — unreachable in
            // both languages (LiveStore.Read never yields a nil record
            // without an error).
            scanned_count += 1;

            // Handle exit record first to avoid double FileComplete.
            // PARITY: Go also checks `exit.Exit != nil`; prost oneofs carry
            // the record by value, so it is always present.
            if let Some(record::RecordType::Exit(exit)) = &record.record_type {
                self.exit_seen = true;
                self.exit_code = exit.exit_code;
                break;
            }

            match self.record_to_msg(record) {
                Some(SourceMsg::History(m)) => histories.push(m),
                Some(SourceMsg::Summary(m)) => summaries.push(m),
                Some(msg) => msgs.push(msg),
                None => {}
            }
        }

        if !histories.is_empty() {
            msgs.push(SourceMsg::History(concatenate_history(
                &histories,
                &self.run_path,
            )));
        }
        if !summaries.is_empty() {
            msgs.push(SourceMsg::Summary(concatenate_summary(
                &summaries,
                &self.run_path,
            )));
        }

        if self.exit_seen && !self.file_complete_emitted {
            msgs.push(SourceMsg::FileComplete(FileCompleteMsg {
                exit_code: self.exit_code,
            }));
            self.file_complete_emitted = true;
        }

        // Determine if there's more to read,
        // i.e. whether we have records and didn't hit EOF, there might be more.
        let has_more = !self.exit_seen && scanned_count > 0;

        (
            Some(SourceMsg::ChunkedBatch(ChunkedBatchMsg {
                msgs,
                has_more,
                progress: scanned_count,
            })),
            err,
        )
    }

    fn close(&mut self) {
        if let Some(store) = self.store.as_mut() {
            store.close();
            self.store = None;
        }
    }
}

/// ParseHistory extracts metrics and media from a history record.
// PARITY: Go returns nil for a nil *spb.HistoryRecord; the reference cannot
// be nil here (prost oneofs are by value). Returns None where Go returns a
// nil tea.Msg.
pub fn parse_history(run_path: &str, history: &wandb_internal::HistoryRecord) -> Option<SourceMsg> {
    let mut step: i64 = history.step.as_ref().map_or(0, |s| s.num);
    let mut values: HashMap<String, f64> = HashMap::with_capacity(history.item.len());
    let mut media_fields_by_key: HashMap<String, HashMap<String, String>> = HashMap::new();

    for item in &history.item {
        // PARITY: Go skips nil items; prost repeated messages are by value.

        if let Some((media_key, field)) = history_media_field(item) {
            media_fields_by_key
                .entry(media_key)
                .or_default()
                .insert(field, trim_json_string(&item.value_json));
            continue;
        }

        let mut key = item.nested_key.join(".");
        if key.is_empty() {
            key = item.key.clone();
        }
        if key.is_empty() {
            continue;
        }

        let v = trim_json_string(&item.value_json);
        if key == "_step" {
            if let Some(s) = go_atoi(&v) {
                step = s;
            }
            continue;
        }
        if key.starts_with('_') {
            continue;
        }
        if let Some(val) = go_parse_float(&v) {
            values.insert(key, val);
        }
    }

    let mut metrics: HashMap<String, MetricData> = HashMap::with_capacity(values.len());
    if !values.is_empty() {
        // PARITY: Go shares one X slice across every MetricData (aliasing);
        // consumers only read/copy it, so per-entry clones are equivalent.
        let x = vec![step as f64];
        for (k, y) in values {
            metrics.insert(
                k,
                MetricData {
                    x: x.clone(),
                    y: vec![y],
                },
            );
        }
    }

    let media = parse_history_media(run_path, step, &media_fields_by_key);

    if metrics.is_empty() && media.is_empty() {
        return None;
    }

    // PARITY: Go leaves Metrics/Media nil when empty; empty maps are
    // indistinguishable (see history_source::HistoryMsg).
    Some(SourceMsg::History(HistoryMsg {
        run_path: run_path.to_string(),
        metrics,
        media,
    }))
}

/// Go: `trimJSONString` — strconv.Unquote with pass-through on failure.
fn trim_json_string(v: &str) -> String {
    if v.is_empty() {
        return String::new();
    }
    if let Some(unquoted) = go_strconv_unquote(v) {
        return unquoted;
    }
    v.to_string()
}

/// parseHistoryMedia builds media series from the per-key media fields of a
/// history record.
fn parse_history_media(
    run_path: &str,
    step: i64,
    media_fields_by_key: &HashMap<String, HashMap<String, String>>,
) -> HashMap<String, Vec<MediaPoint>> {
    let mut media: HashMap<String, Vec<MediaPoint>> = HashMap::new();
    // PARITY: Go iterates the map unordered; the output is keyed per media
    // key, so the result is order-independent.
    for (media_key, fields) in media_fields_by_key {
        // Go reads missing keys from the map as "" (zero value).
        let field = |name: &str| -> &str { fields.get(name).map_or("", String::as_str) };

        match field("_type") {
            "image-file" => {
                let rel_path = field("path");
                if rel_path.is_empty() {
                    continue;
                }
                media
                    .entry(media_key.clone())
                    .or_default()
                    .push(MediaPoint {
                        x: step as f64,
                        file_path: resolve_media_path(run_path, rel_path),
                        relative_path: rel_path.to_string(),
                        caption: field("caption").to_string(),
                        format: field("format").to_string(),
                        width: parse_history_int(field("width")),
                        height: parse_history_int(field("height")),
                        sha256: field("sha256").to_string(),
                    });
            }
            "images/separated" => {
                // A list of wandb.Image logged under one key: fan each image
                // out into its own "key[i]" series so every image gets a tile.
                let captions = parse_json_string_array(field("captions"));
                for (i, rel_path) in parse_json_string_array(field("filenames"))
                    .iter()
                    .enumerate()
                {
                    if rel_path.is_empty() {
                        continue;
                    }
                    let mut point = MediaPoint {
                        x: step as f64,
                        file_path: resolve_media_path(run_path, rel_path),
                        relative_path: rel_path.clone(),
                        format: field("format").to_string(),
                        width: parse_history_int(field("width")),
                        height: parse_history_int(field("height")),
                        ..Default::default()
                    };
                    if i < captions.len() {
                        point.caption = captions[i].clone();
                    }
                    let indexed_key = format!("{media_key}[{i}]");
                    media.entry(indexed_key).or_default().push(point);
                }
            }
            _ => {}
        }
    }
    media
}

/// parseJSONStringArray decodes a JSON array of strings, returning empty on
/// malformed input.
// PARITY: Go returns nil; nil and empty slices are indistinguishable here.
// Go's encoding/json leaves a null element as the zero value "" without
// error; serde_json's Vec<String> would reject the whole array, so decode
// via Value to preserve that.
fn parse_json_string_array(v: &str) -> Vec<String> {
    let Ok(serde_json::Value::Array(items)) = serde_json::from_str::<serde_json::Value>(v) else {
        return Vec::new();
    };
    let mut out = Vec::with_capacity(items.len());
    for item in items {
        match item {
            serde_json::Value::String(s) => out.push(s),
            serde_json::Value::Null => out.push(String::new()),
            _ => return Vec::new(),
        }
    }
    out
}

/// Go: `parseHistoryInt` — strconv.Atoi with 0 on failure.
fn parse_history_int(v: &str) -> i64 {
    go_atoi(v).unwrap_or(0)
}

/// Go: `strconv.Atoi` returning None on error.
// PARITY: Atoi is base-10 with an optional sign and 64-bit range here;
// parse::<i64> matches (precedent: system_metrics::is_numeric).
fn go_atoi(v: &str) -> Option<i64> {
    v.parse::<i64>().ok()
}

/// Go: `strconv.ParseFloat(v, 64)` returning None on error.
// PARITY: ParseFloat's grammar is wider than str::parse — full Go float
// syntax with digit-separating underscores ("1_000.5") and hex float
// literals ("0x1p3"). Both forms are reachable here: trimJSONString (and
// parse_stats' manual quote-strip) unquote user-logged JSON string values
// before parsing, so wandb.log({"m": "1_000"}) arrives as `1_000`. Go's
// grammar (special/readFloat/underscoreOK/atofHex from strconv/atof.go)
// is therefore ported below; validated decimal forms are delegated to
// str::parse, which rounds to nearest-even exactly like Go's atof64.
// Error shape (verified against Go 1.26): overflow ("1e999", "0x1p1024")
// is ErrRange — returned WITH ±Inf, so the `err == nil` callers skip it —
// while underflow ("1e-400") is (0, nil); str::parse's saturation to 0
// matches the latter, and the former maps to None.
fn go_parse_float(v: &str) -> Option<f64> {
    if let Some(f) = parse_float_special(v) {
        return Some(f);
    }
    let (mantissa, exp, neg, trunc, hex, consumed) = read_float(v)?;
    // Go: ParseFloat rejects any unconsumed suffix ("1.5x") as ErrSyntax.
    if consumed != v.len() {
        return None;
    }
    if hex {
        return atof_hex(mantissa, exp, neg, trunc);
    }
    // Decimal form, validated above; strip the underscores str::parse does
    // not accept. (The stripped form is always within str::parse's grammar,
    // so the ok()? is unreachable-defensive.)
    let value = if v.contains('_') {
        v.replace('_', "").parse::<f64>().ok()?
    } else {
        v.parse::<f64>().ok()?
    };
    if value.is_infinite() {
        // Go: decimal overflow is ErrRange (infinity literals were already
        // handled by parse_float_special).
        return None;
    }
    Some(value)
}

/// Go: strconv's `special`, folded with ParseFloat's whole-string check —
/// "inf"/"infinity" with optional sign, "nan" WITHOUT a sign (Go's sign
/// branch falls through to the infinity case only, so "+nan"/"-nan" are
/// syntax errors), all ASCII case-insensitive.
fn parse_float_special(s: &str) -> Option<f64> {
    let (sign, rest) = match s.as_bytes().first() {
        Some(b'+') => (1.0_f64, &s[1..]),
        Some(b'-') => (-1.0_f64, &s[1..]),
        _ => (1.0_f64, s),
    };
    if rest.eq_ignore_ascii_case("inf") || rest.eq_ignore_ascii_case("infinity") {
        return Some(sign * f64::INFINITY);
    }
    if s.eq_ignore_ascii_case("nan") {
        // PARITY: Go's math.NaN() payload (0x7ff8000000000001) differs from
        // f64::NAN's; NaN payloads are unobservable in leet.
        return Some(f64::NAN);
    }
    None
}

/// Go: strconv's `lower(c)` — ASCII case fold.
fn lower(c: u8) -> u8 {
    c | (b'x' - b'X')
}

/// Go: strconv's `readFloat` — parse a decimal or hex float prefix into
/// mantissa/exponent form. Returns None where Go returns ok=false;
/// `(mantissa, exp, neg, trunc, hex, i)` otherwise, where `i` is the number
/// of bytes consumed (Go's `i`; the caller enforces full consumption).
fn read_float(s: &str) -> Option<(u64, i64, bool, bool, bool, usize)> {
    let sb = s.as_bytes();
    let mut i = 0_usize;
    let mut mantissa: u64 = 0;
    let mut exp: i64 = 0;
    let mut neg = false;
    let mut trunc = false;

    let mut underscores = false;

    // optional sign
    if i >= sb.len() {
        return None;
    }
    match sb[i] {
        b'+' => i += 1,
        b'-' => {
            neg = true;
            i += 1;
        }
        _ => {}
    }

    // digits
    let mut base: u64 = 10;
    let mut max_mant_digits = 19; // 10^19 fits in uint64
    let mut exp_char = b'e';
    let mut hex = false;
    if i + 2 < sb.len() && sb[i] == b'0' && lower(sb[i + 1]) == b'x' {
        base = 16;
        max_mant_digits = 16; // 16^16 fits in uint64
        i += 2;
        exp_char = b'p';
        hex = true;
    }
    let mut sawdot = false;
    let mut sawdigits = false;
    let mut nd: i64 = 0;
    let mut nd_mant: i64 = 0;
    let mut dp: i64 = 0;
    while i < sb.len() {
        let c = sb[i];
        if c == b'_' {
            underscores = true;
            i += 1;
            continue;
        }
        if c == b'.' {
            if sawdot {
                break;
            }
            sawdot = true;
            dp = nd;
            i += 1;
            continue;
        }
        if c.is_ascii_digit() {
            sawdigits = true;
            if c == b'0' && nd == 0 {
                // ignore leading zeros
                dp -= 1;
                i += 1;
                continue;
            }
            nd += 1;
            if nd_mant < max_mant_digits {
                mantissa *= base;
                mantissa += u64::from(c - b'0');
                nd_mant += 1;
            } else if c != b'0' {
                trunc = true;
            }
            i += 1;
            continue;
        }
        if base == 16 && (b'a'..=b'f').contains(&lower(c)) {
            sawdigits = true;
            nd += 1;
            if nd_mant < max_mant_digits {
                mantissa = mantissa * 16 + u64::from(lower(c) - b'a' + 10);
                nd_mant += 1;
            } else {
                trunc = true;
            }
            i += 1;
            continue;
        }
        break;
    }
    if !sawdigits {
        return None;
    }
    if !sawdot {
        dp = nd;
    }

    if base == 16 {
        dp *= 4;
        nd_mant *= 4;
    }

    // optional exponent moves decimal point.
    // if we read a very large, very long number,
    // just be sure to move the decimal point by
    // a lot (say, 100000). it doesn't matter if it's
    // not the exact number.
    if i < sb.len() && lower(sb[i]) == exp_char {
        i += 1;
        if i >= sb.len() {
            return None;
        }
        let mut esign: i64 = 1;
        if sb[i] == b'+' {
            i += 1;
        } else if sb[i] == b'-' {
            i += 1;
            esign = -1;
        }
        if i >= sb.len() || !sb[i].is_ascii_digit() {
            return None;
        }
        let mut e: i64 = 0;
        while i < sb.len() && (sb[i].is_ascii_digit() || sb[i] == b'_') {
            if sb[i] == b'_' {
                underscores = true;
                i += 1;
                continue;
            }
            if e < 10000 {
                e = e * 10 + i64::from(sb[i] - b'0');
            }
            i += 1;
        }
        dp += e * esign;
    } else if base == 16 {
        // Must have exponent.
        return None;
    }

    if mantissa != 0 {
        exp = dp - nd_mant;
    }

    if underscores && !underscore_ok(&s[..i]) {
        return None;
    }

    Some((mantissa, exp, neg, trunc, hex, i))
}

/// Go: strconv's `underscoreOK` — underscores must appear only between
/// digits or between a base prefix and a digit.
fn underscore_ok(s: &str) -> bool {
    // saw tracks the last character (class) we saw:
    // ^ for beginning of number, 0 for a digit or base prefix,
    // _ for an underscore, and ! for none of the above.
    let mut saw = b'^';
    let mut i = 0_usize;
    let mut sb = s.as_bytes();
    // Optional sign.
    if !sb.is_empty() && (sb[0] == b'-' || sb[0] == b'+') {
        sb = &sb[1..];
    }
    // Optional base prefix.
    let mut hex = false;
    if sb.len() >= 2 && sb[0] == b'0' && matches!(lower(sb[1]), b'b' | b'o' | b'x') {
        i = 2;
        saw = b'0'; // base prefix counts as a digit for "underscore as digit separator"
        hex = lower(sb[1]) == b'x';
    }
    // Number proper.
    while i < sb.len() {
        // Digits are always okay.
        if sb[i].is_ascii_digit() || (hex && (b'a'..=b'f').contains(&lower(sb[i]))) {
            saw = b'0';
            i += 1;
            continue;
        }
        // Underscore must follow digit.
        if sb[i] == b'_' {
            if saw != b'0' {
                return false;
            }
            saw = b'_';
            i += 1;
            continue;
        }
        // Underscore must also be followed by digit.
        if saw == b'_' {
            return false;
        }
        // Saw non-digit, non-underscore.
        saw = b'!';
        i += 1;
    }
    saw != b'_'
}

/// Go: strconv's `atofHex`, specialized to float64 (flt = &float64info:
/// mantbits=52, expbits=11, bias=-1023). Converts the mantissa/exponent
/// form produced by [`read_float`] with IEEE754 unbiased rounding; `trunc`
/// means trailing non-zero mantissa digits were dropped. Returns None where
/// Go reports ErrRange (overflow to ±Inf — its only error; underflow
/// denormalizes to ±0 with a nil error).
fn atof_hex(mut mantissa: u64, mut exp: i64, neg: bool, trunc: bool) -> Option<f64> {
    const MANTBITS: u64 = 52;
    const EXPBITS: u64 = 11;
    const BIAS: i64 = -1023;
    let max_exp: i64 = (1 << EXPBITS) + BIAS - 2;
    let min_exp: i64 = BIAS + 1;
    exp += MANTBITS as i64; // mantissa now implicitly divided by 2^mantbits.

    // Shift mantissa and exponent to bring representation into float range.
    // Eventually we want a mantissa with a leading 1-bit followed by mantbits
    // other bits. For rounding, we need two more, where the bottom bit
    // represents whether that bit or any later bit was non-zero.
    // (If the mantissa has already lost non-zero bits, trunc is true,
    // and we OR in a 1 below after shifting left appropriately.)
    while mantissa != 0 && mantissa >> (MANTBITS + 2) == 0 {
        mantissa <<= 1;
        exp -= 1;
    }
    if trunc {
        mantissa |= 1;
    }
    while mantissa >> (1 + MANTBITS + 2) != 0 {
        mantissa = (mantissa >> 1) | (mantissa & 1);
        exp += 1;
    }

    // If exponent is too negative,
    // denormalize in hopes of making it representable.
    // (The -2 is for the rounding bits.)
    while mantissa > 1 && exp < min_exp - 2 {
        mantissa = (mantissa >> 1) | (mantissa & 1);
        exp += 1;
    }

    // Round using two bottom bits.
    let mut round = mantissa & 3;
    mantissa >>= 2;
    round |= mantissa & 1; // round to even (round up if mantissa is odd)
    exp += 2;
    if round == 3 {
        mantissa += 1;
        if mantissa == 1 << (1 + MANTBITS) {
            mantissa >>= 1;
            exp += 1;
        }
    }

    if mantissa >> MANTBITS == 0 {
        // Denormal or zero.
        exp = BIAS;
    }
    if exp > max_exp {
        // infinity and range error
        return None;
    }

    let mut bits = mantissa & ((1 << MANTBITS) - 1);
    bits |= (((exp - BIAS) as u64) & ((1 << EXPBITS) - 1)) << MANTBITS;
    if neg {
        bits |= 1 << (MANTBITS + EXPBITS);
    }
    Some(f64::from_bits(bits))
}

/// Go: `historyMediaField`.
fn history_media_field(item: &wandb_internal::HistoryItem) -> Option<(String, String)> {
    let parts = &item.nested_key;
    if parts.len() < 2 {
        return None;
    }
    let field = &parts[parts.len() - 1];
    match field.as_str() {
        "_type" | "path" | "caption" | "format" | "width" | "height" | "sha256" | "size"
        | "count" | "filenames" | "captions" => {}
        _ => return None,
    }
    let media_key = parts[..parts.len() - 1].join(".");
    if media_key.is_empty() {
        return None;
    }
    Some((media_key, field.clone()))
}

/// ParseStats extracts metrics from a stats record.
// PARITY: Go returns nil for a nil *spb.StatsRecord; unreachable here (see
// parse_history). Returns None where Go returns a nil tea.Msg.
pub fn parse_stats(run_path: &str, stats: &wandb_internal::StatsRecord) -> Option<SourceMsg> {
    let mut metrics: HashMap<String, f64> = HashMap::with_capacity(stats.item.len());
    let mut timestamp: i64 = 0;

    if let Some(ts) = &stats.timestamp {
        timestamp = ts.seconds;
    }

    for item in &stats.item {
        // PARITY: Go skips nil items; prost repeated messages are by value.

        let mut v = item.value_json.as_str();
        let n = v.len();
        if n >= 2 && v.as_bytes()[0] == b'"' && v.as_bytes()[n - 1] == b'"' {
            v = &v[1..n - 1];
        }
        if let Some(value) = go_parse_float(v) {
            metrics.insert(item.key.clone(), value);
        }
    }

    if !metrics.is_empty() {
        return Some(SourceMsg::Stats(StatsMsg {
            run_path: run_path.to_string(),
            timestamp,
            metrics,
        }));
    }
    None
}

/// parseOutputRaw extracts a ConsoleLogMsg from an OutputRawRecord.
// PARITY: Go returns nil for a nil *spb.OutputRawRecord; unreachable here
// (see parse_history), so the return is not optional.
fn parse_output_raw(run_path: &str, rec: wandb_internal::OutputRawRecord) -> SourceMsg {
    let ts = rec
        .timestamp
        .map(|t| go_time_unix(t.seconds, i64::from(t.nanos)));

    SourceMsg::ConsoleLog(ConsoleLogMsg {
        run_path: run_path.to_string(),
        text: rec.line,
        is_stderr: rec.output_type == output_raw_record::OutputType::Stderr as i32,
        time: ts,
    })
}

/// Go: `time.Unix(sec, nsec)` — nsec may lie outside [0, 1e9) and is
/// normalized into sec.
fn go_time_unix(mut sec: i64, mut nsec: i64) -> SystemTime {
    if !(0..1_000_000_000).contains(&nsec) {
        let n = nsec / 1_000_000_000;
        sec += n;
        nsec -= n * 1_000_000_000;
        if nsec < 0 {
            nsec += 1_000_000_000;
            sec -= 1;
        }
    }
    if sec >= 0 {
        UNIX_EPOCH + Duration::new(sec as u64, nsec as u32)
    } else {
        // PARITY: Go time.Time spans the far past; SystemTime subtraction
        // covers every timestamp a .wandb record can carry.
        UNIX_EPOCH - Duration::from_secs(sec.unsigned_abs()) + Duration::new(0, nsec as u32)
    }
}

// --- strconv.Unquote (Go stdlib strconv/quote.go), used by trimJSONString ---

/// Go: `strconv.Unquote` returning None where Go returns an error.
///
/// Verbatim port of `unquote(in, true)` with Unquote's "no remainder" rule.
/// leet applies it to JSON-encoded values, and Go's semantics are kept
/// exactly: Go escapes only — JSON's `\/` escape and its split
/// surrogate-pair `\u` escapes for astral-plane chars FAIL here, so such
/// strings pass through raw (trimJSONString falls back to the input).
fn go_strconv_unquote(input: &str) -> Option<String> {
    let b = input.as_bytes();
    // Determine the quote form and optimistically find the terminating quote.
    if b.len() < 2 {
        return None;
    }
    let quote = b[0];
    // Position just after the first terminating quote candidate; may be
    // wrong if escape sequences are present.
    let end = 2 + b[1..].iter().position(|&c| c == quote)?;

    match quote {
        b'`' => {
            // Unquote: any remainder after the closing quote is an error.
            if end != b.len() {
                return None;
            }
            let body = &input[1..end - 1];
            // Carriage return characters ('\r') inside raw string literals
            // are discarded from the raw string value.
            if body.as_bytes().contains(&b'\r') {
                Some(body.replace('\r', ""))
            } else {
                Some(body.to_string())
            }
        }
        b'"' | b'\'' => {
            // Handle quoted strings without any escape sequences.
            if !b[..end].contains(&b'\\') && !b[..end].contains(&b'\n') {
                let body = &input[1..end - 1];
                let valid = match quote {
                    // Go checks utf8.ValidString here; &str is always valid.
                    b'"' => true,
                    // Single-quoted strings must hold exactly one rune.
                    _ => {
                        let mut chars = body.chars();
                        chars.next().is_some() && chars.next().is_none()
                    }
                };
                if valid {
                    if end != b.len() {
                        return None;
                    }
                    return Some(body.to_string());
                }
            }

            // Handle quoted strings with escape sequences.
            let mut buf: Vec<u8> = Vec::with_capacity(3 * b.len() / 2);
            let mut s = &input[1..]; // skip starting quote
            while !s.is_empty() && s.as_bytes()[0] != quote {
                // Process the next character, rejecting any unescaped
                // newline characters which are invalid.
                if s.as_bytes()[0] == b'\n' {
                    return None;
                }
                let (r, multibyte, rest) = go_unquote_char(s, quote)?;
                s = rest;

                // Append the character.
                if r < 0x80 || !multibyte {
                    // PARITY: Go appends byte(r) — \xHH and octal escapes can
                    // emit raw non-UTF-8 bytes into a Go string; caught by
                    // the from_utf8 check below.
                    buf.push(r as u8);
                } else {
                    let mut tmp = [0u8; 4];
                    buf.extend_from_slice(
                        char::from_u32(r)
                            .expect("validated by go_unquote_char")
                            .encode_utf8(&mut tmp)
                            .as_bytes(),
                    );
                }

                // Single quoted strings must be a single character.
                if quote == b'\'' {
                    break;
                }
            }

            // Verify that the string ends with a terminating quote.
            if s.is_empty() || s.as_bytes()[0] != quote {
                return None;
            }
            s = &s[1..]; // skip terminating quote
            if !s.is_empty() {
                return None;
            }

            // PARITY(divergence): Go strings may hold invalid UTF-8 (from
            // \xHH/octal escapes ≥ 0x80); a Rust String cannot, so treat it
            // as a failure — trimJSONString then passes the raw input
            // through. Unreachable for JSON-encoded value_json.
            String::from_utf8(buf).ok()
        }
        _ => None,
    }
}

/// Go: `strconv.UnquoteChar` — decode the first character or escape sequence,
/// returning (rune value, multibyte, tail). None where Go returns an error.
///
/// `multibyte=false` with a value ≥ 0x80 means "append the raw byte"
/// (\xHH and octal escapes), exactly as in Go.
fn go_unquote_char(s: &str, quote: u8) -> Option<(u32, bool, &str)> {
    let b = s.as_bytes();

    // easy cases
    let c = *b.first()?;
    if c == quote && (quote == b'\'' || quote == b'"') {
        return None;
    }
    if c >= 0x80 {
        // Go: utf8.DecodeRuneInString — &str is valid UTF-8, so the
        // RuneError-for-invalid-encoding case is unreachable.
        let ch = s.chars().next().expect("checked non-empty");
        return Some((ch as u32, true, &s[ch.len_utf8()..]));
    }
    if c != b'\\' {
        return Some((u32::from(c), false, &s[1..]));
    }

    // hard case: c is backslash
    if b.len() <= 1 {
        return None;
    }
    let c = b[1];
    if c >= 0x80 {
        // Go's switch on the escape byte falls to the errSyntax default for
        // any non-ASCII byte (checked before slicing to stay on char
        // boundaries).
        return None;
    }
    let mut s = &s[2..];

    let value: u32;
    let mut multibyte = false;
    match c {
        b'a' => value = 0x07,
        b'b' => value = 0x08,
        b'f' => value = 0x0C,
        b'n' => value = u32::from(b'\n'),
        b'r' => value = u32::from(b'\r'),
        b't' => value = u32::from(b'\t'),
        b'v' => value = 0x0B,
        b'x' | b'u' | b'U' => {
            let n = match c {
                b'x' => 2,
                b'u' => 4,
                _ => 8,
            };
            let sb = s.as_bytes();
            if sb.len() < n {
                return None;
            }
            let mut v: u32 = 0;
            for &digit in &sb[..n] {
                let x = unhex(digit)?;
                v = (v << 4) | x;
            }
            s = &s[n..];
            if c == b'x' {
                // single-byte string, possibly not UTF-8
                value = v;
            } else {
                // Go: utf8.ValidRune — rejects surrogates and > U+10FFFF.
                char::from_u32(v)?;
                value = v;
                multibyte = true;
            }
        }
        b'0'..=b'7' => {
            let mut v: u32 = u32::from(c - b'0');
            let sb = s.as_bytes();
            if sb.len() < 2 {
                return None;
            }
            for &digit in &sb[..2] {
                // one digit already; two more
                let x = digit.wrapping_sub(b'0');
                if x > 7 {
                    return None;
                }
                v = (v << 3) | u32::from(x);
            }
            s = &s[2..];
            if v > 255 {
                return None;
            }
            value = v;
        }
        b'\\' => value = u32::from(b'\\'),
        b'\'' | b'"' => {
            if c != quote {
                return None;
            }
            value = u32::from(c);
        }
        _ => return None,
    }
    Some((value, multibyte, s))
}

/// Go: strconv's `unhex`.
fn unhex(b: u8) -> Option<u32> {
    match b {
        b'0'..=b'9' => Some(u32::from(b - b'0')),
        b'a'..=b'f' => Some(u32::from(b - b'a') + 10),
        b'A'..=b'F' => Some(u32::from(b - b'A') + 10),
        _ => None,
    }
}

// Tests transliterated from leveldbhistorysource_test.go, plus the four
// TestParseHistory_* cases from media_test.go (deferred by the media unit,
// see the PARITY block in media.rs) and liveread_test.go's
// TestParseHistory_UsesHistoryStepFallback (see history_source.rs).
#[cfg(test)]
mod tests {
    use std::path::Path;

    use leet_proto::wandb_internal::{
        HistoryItem, HistoryRecord, HistoryStep, Record, RunExitRecord, RunRecord, StatsItem,
        StatsRecord, SummaryItem, SummaryRecord, record,
    };
    use leet_wire::transaction_log;
    use pretty_assertions::assert_eq;

    use super::*;
    use crate::history_source::{BOOT_LOAD_CHUNK_SIZE, BOOT_LOAD_MAX_TIME, read_records};

    fn record_of(record_type: record::RecordType) -> Record {
        Record {
            record_type: Some(record_type),
            ..Default::default()
        }
    }

    fn history_item(nested_key: &[&str], value_json: &str) -> HistoryItem {
        HistoryItem {
            nested_key: nested_key.iter().map(ToString::to_string).collect(),
            value_json: value_json.to_string(),
            ..Default::default()
        }
    }

    fn write_records(path: &Path, records: Vec<Record>) {
        let mut w = transaction_log::open_writer(path).unwrap();
        for rec in &records {
            w.write(rec).unwrap();
        }
        w.close().unwrap();
    }

    // Go: proto timestamps are ::prost_types::Timestamp, which leet-data
    // cannot name (prost-types is not a direct dependency); build via
    // inference from the field type.
    fn stats_timestamp(seconds: i64) -> StatsRecord {
        let mut stats = StatsRecord {
            timestamp: Some(Default::default()),
            ..Default::default()
        };
        if let Some(ts) = stats.timestamp.as_mut() {
            ts.seconds = seconds;
        }
        stats
    }

    // Verifies the missing-file path in NewWandbReader. reader.go
    // returns a descriptive error when the file doesn't exist.
    //
    // Go: TestNewWandbReader_MissingFile.
    #[test]
    fn new_wandb_reader_missing_file() {
        assert!(LevelDBHistorySource::new("no/such/file.wandb").is_err());
    }

    // Go: TestParseHistory_StepAndMetrics.
    #[test]
    fn parse_history_step_and_metrics() {
        let h = HistoryRecord {
            item: vec![
                history_item(&["_step"], "2"),
                history_item(&["loss"], "0.5"),
                history_item(&["_runtime"], "1.2"),
            ],
            ..Default::default()
        };
        let Some(SourceMsg::History(msg)) = parse_history("/some/run/path", &h) else {
            panic!("expected HistoryMsg");
        };
        assert_eq!(msg.metrics["loss"].x[0], 2.0);
        assert_eq!(msg.metrics["loss"].y[0], 0.5);
    }

    // Go: TestReadAllRecordsChunked_HistoryThenExit.
    #[test]
    fn read_all_records_chunked_history_then_exit() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("chunky.wandb");

        // Write a valid header + two records (history, exit).
        let h = HistoryRecord {
            item: vec![
                history_item(&["_step"], "1"),
                history_item(&["loss"], "0.42"),
            ],
            ..Default::default()
        };
        write_records(
            &path,
            vec![
                record_of(record::RecordType::History(h)),
                record_of(record::RecordType::Exit(RunExitRecord {
                    exit_code: 0,
                    ..Default::default()
                })),
            ],
        );

        let mut s = LevelDBHistorySource::new(path.to_str().unwrap()).unwrap();

        let msg = read_records(&mut s, BOOT_LOAD_CHUNK_SIZE, BOOT_LOAD_MAX_TIME);
        let Some(SourceMsg::ChunkedBatch(batch)) = msg else {
            panic!("expected ChunkedBatchMsg");
        };
        assert!(!batch.has_more);
        assert_eq!(batch.progress, 2);
        assert_eq!(batch.msgs.len(), 2);

        let SourceMsg::History(hist) = &batch.msgs[0] else {
            panic!("expected HistoryMsg, got {:?}", batch.msgs[0]);
        };
        assert_eq!(hist.metrics["loss"].x[0], 1.0);
        assert_eq!(hist.metrics["loss"].y[0], 0.42);
        let SourceMsg::FileComplete(complete) = &batch.msgs[1] else {
            panic!("expected FileCompleteMsg, got {:?}", batch.msgs[1]);
        };
        assert_eq!(complete.exit_code, 0);
    }

    // Go: TestLevelDBHistorySource_FileCompleteEmittedOnce.
    #[test]
    fn leveldb_history_source_file_complete_emitted_once() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("complete-once.wandb");

        write_records(
            &path,
            vec![record_of(record::RecordType::Exit(RunExitRecord {
                exit_code: 0,
                ..Default::default()
            }))],
        );

        let mut reader = LevelDBHistorySource::new(path.to_str().unwrap()).unwrap();

        let (msg, err) = reader.read(BOOT_LOAD_CHUNK_SIZE, BOOT_LOAD_MAX_TIME);
        assert!(err.is_none());
        let Some(SourceMsg::ChunkedBatch(batch)) = msg else {
            panic!("expected ChunkedBatchMsg");
        };
        assert_eq!(batch.msgs.len(), 1);
        assert!(matches!(batch.msgs[0], SourceMsg::FileComplete(_)));

        let (msg, err) = reader.read(BOOT_LOAD_CHUNK_SIZE, BOOT_LOAD_MAX_TIME);
        assert!(err.expect("expected io.EOF").is_eof());
        let Some(SourceMsg::ChunkedBatch(batch)) = msg else {
            panic!("expected ChunkedBatchMsg");
        };
        assert!(batch.msgs.is_empty());
    }

    // Go: TestLevelDBHistorySource_UnsupportedRecordsKeepChunking.
    #[test]
    fn leveldb_history_source_unsupported_records_keep_chunking() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("unsupported-then-history.wandb");

        let mut records = Vec::new();
        for _ in 0..2 {
            records.push(record_of(record::RecordType::Files(Default::default())));
        }
        records.push(record_of(record::RecordType::History(HistoryRecord {
            item: vec![
                history_item(&["_step"], "3"),
                history_item(&["loss"], "0.25"),
            ],
            ..Default::default()
        })));
        write_records(&path, records);

        let mut reader = LevelDBHistorySource::new(path.to_str().unwrap()).unwrap();

        let (msg, err) = reader.read(2, BOOT_LOAD_MAX_TIME);
        assert!(err.is_none());
        let Some(SourceMsg::ChunkedBatch(batch)) = msg else {
            panic!("expected ChunkedBatchMsg");
        };
        assert!(batch.has_more);
        assert_eq!(batch.progress, 2);
        assert!(batch.msgs.is_empty());

        let (msg, err) = reader.read(2, BOOT_LOAD_MAX_TIME);
        assert!(err.is_none());
        let Some(SourceMsg::ChunkedBatch(batch)) = msg else {
            panic!("expected ChunkedBatchMsg");
        };
        assert_eq!(batch.msgs.len(), 1);
        let SourceMsg::History(hist) = &batch.msgs[0] else {
            panic!("expected HistoryMsg, got {:?}", batch.msgs[0]);
        };
        assert_eq!(hist.metrics["loss"].x[0], 3.0);
        assert_eq!(hist.metrics["loss"].y[0], 0.25);
    }

    // Go: TestReadNext_MultipleRecordTypes.
    // PARITY: the Go test builds records from prototext; struct literals
    // here express the same messages.
    #[test]
    fn read_next_multiple_record_types() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("readnext.wandb");

        // Write valid header and various record types
        let run = RunRecord {
            run_id: "test-run-123".to_string(),
            display_name: "Test Run".to_string(),
            project: "test-project".to_string(),
            notes: "Primary baseline run".to_string(),
            tags: vec!["baseline".to_string(), "vision".to_string()],
            ..Default::default()
        };
        let stats = StatsRecord {
            item: vec![
                StatsItem {
                    key: "cpu".to_string(),
                    value_json: "45.5".to_string(),
                },
                StatsItem {
                    key: "memory_percent".to_string(),
                    value_json: "78.2".to_string(),
                },
            ],
            ..stats_timestamp(123)
        };
        let summary = SummaryRecord {
            update: vec![SummaryItem {
                nested_key: vec!["best_loss".to_string()],
                value_json: "0.123".to_string(),
                ..Default::default()
            }],
            ..Default::default()
        };
        let environment = wandb_internal::EnvironmentRecord {
            writer_id: "writer-1".to_string(),
            python: "3.9.7".to_string(),
            os: "Linux".to_string(),
            ..Default::default()
        };
        write_records(
            &path,
            vec![
                record_of(record::RecordType::Run(run)),
                record_of(record::RecordType::Stats(stats)),
                record_of(record::RecordType::Summary(summary)),
                record_of(record::RecordType::Environment(environment)),
                record_of(record::RecordType::Exit(RunExitRecord {
                    exit_code: 0,
                    ..Default::default()
                })),
            ],
        );

        // Read back using ReadNext
        let mut reader = LevelDBHistorySource::new(path.to_str().unwrap()).unwrap();

        // Test ReadNext for each record type
        type ValidateFn = Box<dyn Fn(&SourceMsg)>;
        let tests: Vec<(&str, ValidateFn)> = vec![
            (
                "run",
                Box::new(|msg| {
                    let SourceMsg::Run(run_msg) = msg else {
                        panic!("expected RunMsg, got {msg:?}");
                    };
                    assert_eq!(run_msg.id, "test-run-123");
                    assert_eq!(run_msg.display_name, "Test Run");
                    assert_eq!(run_msg.project, "test-project");
                    assert_eq!(run_msg.notes, "Primary baseline run");
                    assert_eq!(run_msg.tags, vec!["baseline", "vision"]);
                }),
            ),
            (
                "stats",
                Box::new(|msg| {
                    let SourceMsg::Stats(stats_msg) = msg else {
                        panic!("expected StatsMsg, got {msg:?}");
                    };
                    assert_eq!(stats_msg.metrics["cpu"], 45.5);
                    assert_eq!(stats_msg.metrics["memory_percent"], 78.2);
                }),
            ),
            (
                "summary",
                Box::new(|msg| {
                    let SourceMsg::Summary(summary_msg) = msg else {
                        panic!("expected SummaryMsg, got {msg:?}");
                    };
                    assert!(!summary_msg.summary.is_empty());
                    assert_eq!(summary_msg.summary[0].update.len(), 1);
                }),
            ),
            (
                "environment",
                Box::new(|msg| {
                    let SourceMsg::SystemInfo(env_msg) = msg else {
                        panic!("expected SystemInfoMsg, got {msg:?}");
                    };
                    assert_eq!(env_msg.record.writer_id, "writer-1");
                    assert_eq!(env_msg.record.python, "3.9.7");
                }),
            ),
            (
                "exit",
                Box::new(|msg| {
                    let SourceMsg::FileComplete(exit_msg) = msg else {
                        panic!("expected FileCompleteMsg, got {msg:?}");
                    };
                    assert_eq!(exit_msg.exit_code, 0);
                }),
            ),
        ];

        for (name, validate) in tests {
            let (msg, err) = reader.read(1, Duration::from_millis(100));
            assert!(err.is_none(), "{name}: ReadNext error");
            let Some(SourceMsg::ChunkedBatch(batch)) = msg else {
                panic!("{name}: ReadNext returned wrong type");
            };
            assert_eq!(batch.msgs.len(), 1);
            validate(&batch.msgs[0]);
        }

        // After exit record, should get EOF
        let (_, err) = reader.read(1, Duration::from_millis(100));
        assert!(err.expect("expected io.EOF").is_eof());
    }

    // Go: TestParseStats_ComplexMetrics.
    #[test]
    fn parse_stats_complex_metrics() {
        let stats = StatsRecord {
            item: vec![
                StatsItem {
                    key: "cpu".to_string(),
                    value_json: "42.5".to_string(),
                },
                StatsItem {
                    key: "memory_percent".to_string(),
                    value_json: "85.3".to_string(),
                },
                StatsItem {
                    key: "gpu.0.temp".to_string(),
                    value_json: "75".to_string(),
                },
                StatsItem {
                    key: "invalid".to_string(),
                    value_json: "not_a_number".to_string(),
                },
                // Quoted number
                StatsItem {
                    key: "disk.used".to_string(),
                    value_json: "\"123.45\"".to_string(),
                },
                // Empty key
                StatsItem {
                    key: String::new(),
                    value_json: "100".to_string(),
                },
            ],
            ..stats_timestamp(1234567890)
        };

        let Some(SourceMsg::Stats(msg)) = parse_stats("/some/run/path", &stats) else {
            panic!("expected StatsMsg");
        };

        // Verify timestamp
        assert_eq!(msg.timestamp, 1234567890);

        // Verify valid metrics were parsed
        let expected_metrics = [
            ("cpu", 42.5),
            ("memory_percent", 85.3),
            ("gpu.0.temp", 75.0),
            ("disk.used", 123.45),
        ];
        for (key, expected_value) in expected_metrics {
            assert!(msg.metrics.contains_key(key), "missing {key}");
            assert_eq!(msg.metrics[key], expected_value);
        }

        // Verify invalid metrics were skipped
        assert!(!msg.metrics.contains_key("invalid"));
    }

    // Go: TestReadAvailableRecords_BatchProcessing.
    #[test]
    fn read_available_records_batch_processing() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("batch.wandb");

        // Write many history records
        const NUM_RECORDS: usize = 100;
        let mut records = Vec::with_capacity(NUM_RECORDS);
        for i in 0..NUM_RECORDS {
            let h = HistoryRecord {
                item: vec![
                    history_item(&["_step"], &format!("{i}")),
                    // Go: fmt.Sprintf("%f", float64(i)*0.1).
                    history_item(&["loss"], &format!("{:.6}", i as f64 * 0.1)),
                ],
                ..Default::default()
            };
            records.push(record_of(record::RecordType::History(h)));
        }
        write_records(&path, records);

        let mut s = LevelDBHistorySource::new(path.to_str().unwrap()).unwrap();

        // Test ReadAvailableRecords batching
        let msg = read_records(&mut s, BOOT_LOAD_CHUNK_SIZE, BOOT_LOAD_MAX_TIME);
        let Some(SourceMsg::ChunkedBatch(batch)) = msg else {
            panic!("expected ChunkedBatchMsg");
        };

        // Should have read multiple records in batch
        assert!(!batch.msgs.is_empty());

        // Verify first few messages
        for (i, sub_msg) in batch.msgs.iter().enumerate().take(3) {
            let SourceMsg::History(hist_msg) = sub_msg else {
                panic!("msg {i}: expected HistoryMsg, got {sub_msg:?}");
            };
            assert_eq!(hist_msg.metrics["loss"].x[0], i as f64, "msg {i}");
        }

        // Test reading when no more data available
        // First consume all remaining data
        loop {
            let msg = read_records(&mut s, BOOT_LOAD_CHUNK_SIZE, BOOT_LOAD_MAX_TIME);
            let Some(SourceMsg::ChunkedBatch(batch)) = msg else {
                panic!("expected ChunkedBatchMsg");
            };
            if !batch.has_more {
                break; // No more data
            }
        }

        // Now verify returns an empty batch when no data
        let msg = read_records(&mut s, BOOT_LOAD_CHUNK_SIZE, BOOT_LOAD_MAX_TIME);
        let Some(SourceMsg::ChunkedBatch(batch)) = msg else {
            panic!("expected ChunkedBatchMsg");
        };
        assert!(!batch.has_more);
        assert_eq!(batch.msgs.len(), 0);
    }

    // Go: TestParseHistory_UsesHistoryStepFallback (liveread_test.go).
    #[test]
    fn parse_history_uses_history_step_fallback() {
        let Some(SourceMsg::History(msg)) = parse_history(
            "dummy",
            &HistoryRecord {
                step: Some(HistoryStep { num: 7 }),
                item: vec![history_item(&["loss"], "0.5")],
                ..Default::default()
            },
        ) else {
            panic!("expected HistoryMsg");
        };

        assert_eq!(msg.metrics["loss"].x[0], 7.0);
    }

    // Go: TestParseHistory_ImageFile (media_test.go).
    #[test]
    fn parse_history_image_file() {
        let run_path = "tmp/offline-run-123/run-123.wandb";
        let rel_path = "media/images/media/generated_sample_7.png";

        let history = HistoryRecord {
            item: vec![
                history_item(&["_step"], "7"),
                history_item(&["media/generated_sample", "_type"], "\"image-file\""),
                history_item(
                    &["media/generated_sample", "path"],
                    &format!("\"{rel_path}\""),
                ),
                history_item(&["media/generated_sample", "format"], "\"png\""),
                history_item(&["media/generated_sample", "width"], "64"),
                history_item(&["media/generated_sample", "height"], "64"),
                history_item(&["media/generated_sample", "caption"], "\"step=7\""),
            ],
            ..Default::default()
        };

        let Some(SourceMsg::History(msg)) = parse_history(run_path, &history) else {
            panic!("expected HistoryMsg");
        };
        assert!(msg.media.contains_key("media/generated_sample"));
        assert_eq!(msg.media["media/generated_sample"].len(), 1);

        let point = &msg.media["media/generated_sample"][0];
        assert_eq!(point.x, 7.0);
        assert_eq!(
            point.file_path,
            format!("tmp/offline-run-123/files/{rel_path}"),
        );
        assert_eq!(point.relative_path, rel_path);
        assert_eq!(point.caption, "step=7");
        assert_eq!(point.format, "png");
        assert_eq!(point.width, 64);
        assert_eq!(point.height, 64);
    }

    // Go: TestParseHistory_ImageFile_NormalizesRelativePathWithinFilesDir
    // (media_test.go).
    #[test]
    fn parse_history_image_file_normalizes_relative_path_within_files_dir() {
        let run_path = "tmp/offline-run-123/run-123.wandb";
        let rel_path = "../outside/generated_sample_7.png";

        let history = HistoryRecord {
            item: vec![
                history_item(&["_step"], "7"),
                history_item(&["media/generated_sample", "_type"], "\"image-file\""),
                history_item(
                    &["media/generated_sample", "path"],
                    &format!("\"{rel_path}\""),
                ),
                history_item(&["media/generated_sample", "format"], "\"png\""),
                history_item(&["media/generated_sample", "width"], "64"),
                history_item(&["media/generated_sample", "height"], "64"),
            ],
            ..Default::default()
        };

        let Some(SourceMsg::History(msg)) = parse_history(run_path, &history) else {
            panic!("expected HistoryMsg");
        };
        assert!(msg.media.contains_key("media/generated_sample"));
        assert_eq!(msg.media["media/generated_sample"].len(), 1);

        let point = &msg.media["media/generated_sample"][0];
        assert_eq!(
            point.file_path,
            "tmp/offline-run-123/files/outside/generated_sample_7.png",
        );
    }

    // Go: TestParseHistory_ImagesSeparated (media_test.go).
    #[test]
    fn parse_history_images_separated() {
        let run_path = "tmp/offline-run-123/run-123.wandb";

        let history = HistoryRecord {
            item: vec![
                history_item(&["_step"], "7"),
                history_item(&["attention_maps", "_type"], "\"images/separated\""),
                history_item(
                    &["attention_maps", "filenames"],
                    r#"["media/images/maps_7_0.png","media/images/maps_7_1.png"]"#,
                ),
                history_item(&["attention_maps", "captions"], r#"["head 0","head 1"]"#),
                history_item(&["attention_maps", "format"], "\"png\""),
                history_item(&["attention_maps", "width"], "64"),
                history_item(&["attention_maps", "height"], "64"),
                history_item(&["attention_maps", "count"], "2"),
            ],
            ..Default::default()
        };

        let Some(SourceMsg::History(msg)) = parse_history(run_path, &history) else {
            panic!("expected HistoryMsg");
        };
        assert_eq!(msg.media.len(), 2);
        assert!(msg.media.contains_key("attention_maps[0]"));
        assert!(msg.media.contains_key("attention_maps[1]"));

        let point = &msg.media["attention_maps[1]"][0];
        assert_eq!(point.x, 7.0);
        assert_eq!(
            point.file_path,
            "tmp/offline-run-123/files/media/images/maps_7_1.png",
        );
        assert_eq!(point.relative_path, "media/images/maps_7_1.png");
        assert_eq!(point.caption, "head 1");
        assert_eq!(point.format, "png");
        assert_eq!(point.width, 64);
        assert_eq!(point.height, 64);

        // Media metadata must not leak into scalar metrics.
        assert!(!msg.metrics.contains_key("attention_maps.count"));
    }

    // Go: TestParseHistory_ImagesSeparated_NoCaptions (media_test.go).
    #[test]
    fn parse_history_images_separated_no_captions() {
        let run_path = "tmp/offline-run-123/run-123.wandb";

        let history = HistoryRecord {
            item: vec![
                history_item(&["_step"], "3"),
                history_item(&["samples", "_type"], "\"images/separated\""),
                history_item(&["samples", "filenames"], r#"["media/images/s_3_0.png"]"#),
                history_item(&["samples", "format"], "\"png\""),
            ],
            ..Default::default()
        };

        let Some(SourceMsg::History(msg)) = parse_history(run_path, &history) else {
            panic!("expected HistoryMsg");
        };
        assert_eq!(msg.media.len(), 1);
        assert!(msg.media.contains_key("samples[0]"));
        assert_eq!(msg.media["samples[0]"][0].caption, "");
    }

    // Port-added coverage (no Go counterpart): the strconv.Unquote port —
    // quoted/raw/rune forms, Go escapes, and the JSON-only escapes that fail
    // and fall through to the raw string in trimJSONString.
    #[test]
    fn trim_json_string_strconv_unquote_semantics() {
        // Unquotes Go-compatible forms.
        assert_eq!(trim_json_string("\"png\""), "png");
        assert_eq!(trim_json_string(r#""a\"b""#), "a\"b");
        assert_eq!(trim_json_string(r#""tab\there""#), "tab\there");
        assert_eq!(trim_json_string(r#""é""#), "é");
        assert_eq!(trim_json_string("\"héllo\""), "héllo");
        assert_eq!(trim_json_string("`raw\rstring`"), "rawstring");
        assert_eq!(trim_json_string("'x'"), "x");

        // Failures pass the input through unchanged.
        assert_eq!(trim_json_string(""), "");
        assert_eq!(trim_json_string("2"), "2");
        assert_eq!(trim_json_string("0.5"), "0.5");
        assert_eq!(trim_json_string(r#"["a","b"]"#), r#"["a","b"]"#);
        assert_eq!(trim_json_string("\"unterminated"), "\"unterminated");
        assert_eq!(trim_json_string("\"a\"trailing"), "\"a\"trailing");
        // JSON-only escapes are not Go escapes (quirk preserved).
        assert_eq!(trim_json_string(r#""a\/b""#), r#""a\/b""#);
        // JSON surrogate-pair escapes are invalid runes for Go (quirk
        // preserved); an unescaped astral-plane char unquotes fine.
        // (Spelled via concat! so no tooling collapses the escape text.)
        let surrogate_pair = concat!("\"", "\\", "uD83D", "\\", "uDE00", "\"");
        assert_eq!(trim_json_string(surrogate_pair), surrogate_pair);
        assert_eq!(trim_json_string("\"\u{10348}\""), "\u{10348}");
        assert_eq!(trim_json_string("'xy'"), "'xy'");
    }

    // Port-added coverage (no Go counterpart): the strconv.ParseFloat port —
    // Go float syntax (digit-separating underscores, hex float literals),
    // the inf/infinity/nan specials, and the ErrRange-only-on-overflow error
    // shape. Every expected value verified against Go 1.26
    // strconv.ParseFloat(input, 64): Some(v) where Go returns (v, nil), None
    // where Go returns a *NumError.
    #[test]
    fn go_parse_float_strconv_semantics() {
        let cases: &[(&str, Option<f64>)] = &[
            // plain decimal
            ("42.5", Some(42.5)),
            ("0.001", Some(0.001)),
            (".5", Some(0.5)),
            ("5.", Some(5.0)),
            ("1.e2", Some(100.0)),
            ("-12", Some(-12.0)),
            ("", None),
            ("not_a_number", None),
            ("1.5x", None),
            // digit-separating underscores (underscoreOK)
            ("1_000", Some(1000.0)),
            ("1_000.5", Some(1000.5)),
            ("-1_0.5", Some(-10.5)),
            ("1e1_0", Some(1e10)),
            ("1_000e1_0", Some(1e13)),
            ("_1000", None),
            ("1000_", None),
            ("1__000", None),
            ("1._5", None),
            ("1_.5", None),
            ("1_e5", None),
            ("1e_5", None),
            // hex floats (binary exponent is mandatory)
            ("0x1p3", Some(8.0)),
            ("0X1P3", Some(8.0)),
            ("0x1p+3", Some(8.0)),
            ("0x1.8p1", Some(3.0)),
            ("-0x1.8p-1", Some(-0.75)),
            ("0x.8p1", Some(1.0)),
            ("0x_1p3", Some(8.0)),
            ("0x1_0p3", Some(128.0)),
            ("0x1p_3", None),
            ("0x1", None),
            ("0x1p", None),
            ("0xp3", None),
            ("0b101", None),
            ("0o17", None),
            // hex mantissa truncation (17 digits) rounds up to exactly 2^68
            ("0xfffffffffffffffffp0", Some(295147905179352825856.0)),
            // hex denormals; underflow is (0, nil), overflow is ErrRange
            ("0x1p-1074", Some(5e-324)),
            ("0x1p-1075", Some(0.0)),
            ("0x1p1024", None),
            // specials: sign allowed for inf/infinity, prefixes rejected
            ("inf", Some(f64::INFINITY)),
            ("+inf", Some(f64::INFINITY)),
            ("-Infinity", Some(f64::NEG_INFINITY)),
            ("infi", None),
            // decimal overflow is ErrRange (skipped); underflow is (0, nil)
            ("1e309", None),
            ("-1e309", None),
            ("1e999", None),
            ("1e-400", Some(0.0)),
        ];
        for (input, expected) in cases {
            assert_eq!(go_parse_float(input), *expected, "input {input:?}");
        }
        // NaN compares unequal to itself; check separately. Go's special
        // consumes the sign only for infinity, so signed nan is an error.
        assert!(go_parse_float("nan").is_some_and(f64::is_nan));
        assert!(go_parse_float("NaN").is_some_and(f64::is_nan));
        assert_eq!(go_parse_float("+nan"), None);
        assert_eq!(go_parse_float("-nan"), None);
    }

    // Port-added coverage (no Go counterpart): trimJSONString unquotes
    // user-logged JSON string values before ParseFloat, so quoted Go-syntax
    // float forms (wandb.log({"m": "1_000"})) chart in both implementations.
    #[test]
    fn parse_history_quoted_go_float_forms() {
        let h = HistoryRecord {
            item: vec![
                history_item(&["_step"], "2"),
                history_item(&["underscored"], "\"1_000\""),
                history_item(&["hexfloat"], "\"0x1p3\""),
            ],
            ..Default::default()
        };
        let Some(SourceMsg::History(msg)) = parse_history("/some/run/path", &h) else {
            panic!("expected HistoryMsg");
        };
        assert_eq!(msg.metrics["underscored"].y[0], 1000.0);
        assert_eq!(msg.metrics["hexfloat"].y[0], 8.0);
    }

    // Port-added coverage (no Go counterpart): parse_stats' quote-strip
    // feeds ParseFloat the same way (see parse_history_quoted_go_float_forms).
    #[test]
    fn parse_stats_quoted_go_float_forms() {
        let stats = StatsRecord {
            item: vec![
                StatsItem {
                    key: "underscored".to_string(),
                    value_json: "\"1_000.5\"".to_string(),
                },
                StatsItem {
                    key: "hexfloat".to_string(),
                    value_json: "\"0x1p-1\"".to_string(),
                },
            ],
            ..stats_timestamp(1)
        };
        let Some(SourceMsg::Stats(msg)) = parse_stats("/some/run/path", &stats) else {
            panic!("expected StatsMsg");
        };
        assert_eq!(msg.metrics["underscored"], 1000.5);
        assert_eq!(msg.metrics["hexfloat"], 0.5);
    }

    // Port-added coverage (no Go counterpart): Go encoding/json semantics of
    // parseJSONStringArray — null elements become "", non-string elements
    // reject the whole array.
    #[test]
    fn parse_json_string_array_go_json_semantics() {
        assert_eq!(parse_json_string_array(r#"["a","b"]"#), vec!["a", "b"]);
        assert_eq!(parse_json_string_array(r#"["a",null]"#), vec!["a", ""]);
        assert!(parse_json_string_array(r#"["a",1]"#).is_empty());
        assert!(parse_json_string_array("not json").is_empty());
        assert!(parse_json_string_array("null").is_empty());
        assert!(parse_json_string_array("").is_empty());
    }
}

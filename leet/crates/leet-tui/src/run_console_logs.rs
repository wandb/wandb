//! Port of `core/internal/leet/runconsolelogs.go` — assembles raw
//! `output_raw` records into display-ready lines via the terminal emulator.
//!
//! Go wires the emulator back to `RunConsoleLogs` with owner pointers
//! (`consoleLineSupplier.owner` / `consoleLine.owner`); the pointer cycle
//! ports as `Rc<RefCell<ConsoleLogState>>` shared between the store, the two
//! suppliers, and every live line (the CONCURRENCY.md §2.6 shared-pointer
//! pattern — all single-threaded).

use std::cell::{Ref, RefCell};
use std::rc::Rc;
use std::time::{SystemTime, UNIX_EPOCH};

use leet_data::run_overview::KeyValuePair;

use crate::terminal_emulator::{Line, LineContent, LineSupplier, Terminal};

// Console log assembly constants.

/// maxConsoleTermLines is the terminal emulator window size.
///
/// This bounds memory for cursor-addressable output. Lines that scroll
/// out of the terminal window are preserved in the assembled slice.
const MAX_CONSOLE_TERM_LINES: usize = 64;

/// maxConsoleLineLength is the maximum rune length per assembled line.
const MAX_CONSOLE_LINE_LENGTH: usize = 4096;

/// Formats a timestamp for display (Go `consoleTimestampFormat = "15:04:05"`,
/// adapted from the structured format used by the filestreamWriter
/// (rfc3339Micro), but shortened for compact TUI display).
// DIVERGENCE: rendered in UTC, not local time. Go's Format renders in the
// time.Time's location — Local for the time.Unix-built record stamps
// (leveldbhistorysource.go:409-410) — so Go leet shows local wall-clock
// HH:MM:SS while this port shows UTC (keys shift by the machine's UTC offset
// on non-UTC hosts). Local rendering is not implementable in this module:
// std has no local-time API, the workspace denies unsafe_code (no libc
// localtime_r FFI), and a tz-database crate (time/chrono/jiff) is a
// workspace-level Cargo decision outside this unit. UTC matches Go's own
// behavior under TZ="" (Go treats empty/unresolvable TZ as UTC), so
// differential runs must pin the oracle to TZ=UTC. Go's zero time.Time
// (stand-in UNIX_EPOCH, see event.rs ConsoleLogMsg) still renders
// "00:00:00", and the Go unit tests fix UTC times. Pending: PARITY.md row
// (amend LOG-03) + reviewer sign-off; revisit if a tz crate is adopted.
fn format_console_timestamp(ts: SystemTime) -> String {
    let secs = match ts.duration_since(UNIX_EPOCH) {
        Ok(d) => d.as_secs() as i64,
        // Pre-epoch: floor to the started second, like Go's clock display.
        Err(e) => {
            let d = e.duration();
            -(d.as_secs() as i64) - i64::from(d.subsec_nanos() > 0)
        }
    };
    let second_of_day = secs.rem_euclid(86_400);
    format!(
        "{:02}:{:02}:{:02}",
        second_of_day / 3600,
        (second_of_day % 3600) / 60,
        second_of_day % 60
    )
}

/// ConsoleLogLine is an assembled, display-ready line of console output.
#[derive(Debug, Clone)]
pub struct ConsoleLogLine {
    pub timestamp: SystemTime,
    pub content: String,
    pub is_stderr: bool,
}

/// The fields of Go's `RunConsoleLogs` that the line supplier callbacks
/// mutate; shared between [`RunConsoleLogs`] and the emulator's lines.
#[derive(Debug)]
struct ConsoleLogState {
    /// currentTimestamp is set before each Write call so that newly
    /// created lines inherit the record's proto timestamp.
    // PARITY: Go's zero time.Time is stood in by UNIX_EPOCH (event.rs).
    current_timestamp: SystemTime,

    /// lines is the assembled, ordered log output. Lines from both
    /// streams are interleaved in arrival order.
    lines: Vec<ConsoleLogLine>,

    /// items mirrors lines in the KeyValuePair shape expected by
    /// ConsoleLogsPane. It is updated incrementally so View does not need to
    /// reformat every line on every render.
    items: Vec<KeyValuePair>,
}

impl ConsoleLogState {
    /// appendLine is called by the line supplier when a new terminal line is
    /// created. Returns the index for future PutChar callbacks.
    fn append_line(&mut self, is_stderr: bool) -> usize {
        let idx = self.lines.len();
        self.lines.push(ConsoleLogLine {
            timestamp: self.current_timestamp,
            content: String::new(),
            is_stderr,
        });
        self.items.push(KeyValuePair {
            key: format_console_timestamp(self.current_timestamp),
            ..Default::default()
        });
        idx
    }

    /// onLineChanged is called when the terminal emulator modifies a
    /// character on an existing line via PutChar.
    fn on_line_changed(&mut self, idx: usize, content: &[char]) {
        // PARITY: Go also guards idx < 0; unrepresentable with usize.
        if idx >= self.lines.len() {
            return;
        }
        let value: String = content
            .iter()
            .collect::<String>()
            .trim_end_matches([' ', '\t'])
            .to_string();
        self.lines[idx].content = value.clone();
        if idx < self.items.len() {
            self.items[idx].value = value;
        }
    }
}

/// RunConsoleLogs assembles raw output_raw records into display-ready lines.
///
/// Raw terminal output may contain ANSI escape codes, partial lines, and
/// carriage returns. This mirrors the approach used by the
/// runconsolelogs.Sender in the core library: each stream (stdout/stderr)
/// gets its own [`Terminal`] that correctly handles cursor
/// movements, overwrites, and newline assembly.
///
/// Like `RunOverview`, this is a data-model component; the `ConsoleLogsPane`
/// handles presentation.
pub struct RunConsoleLogs {
    stdout_term: Terminal,
    stderr_term: Terminal,

    state: Rc<RefCell<ConsoleLogState>>,
}

impl Default for RunConsoleLogs {
    fn default() -> Self {
        Self::new()
    }
}

impl RunConsoleLogs {
    /// Creates an empty console log store with terminal emulators for stdout
    /// and stderr.
    pub fn new() -> Self {
        let state = Rc::new(RefCell::new(ConsoleLogState {
            current_timestamp: UNIX_EPOCH,
            lines: Vec::new(),
            items: Vec::new(),
        }));

        let stdout_term = Terminal::new(
            Box::new(ConsoleLineSupplier {
                owner: Rc::clone(&state),
                is_stderr: false,
            }),
            MAX_CONSOLE_TERM_LINES,
        );
        let stderr_term = Terminal::new(
            Box::new(ConsoleLineSupplier {
                owner: Rc::clone(&state),
                is_stderr: true,
            }),
            MAX_CONSOLE_TERM_LINES,
        );

        RunConsoleLogs {
            stdout_term,
            stderr_term,
            state,
        }
    }

    /// Feeds a raw output record through the terminal emulator.
    ///
    /// The text may contain newlines, ANSI escape codes (e.g. cursor-up),
    /// and partial lines. The emulator handles all of this and calls back
    /// into the line supplier to create assembled lines — eliminating the
    /// extra-newline problem that occurs with naive line splitting.
    pub fn process_raw(&mut self, text: &str, is_stderr: bool, ts: SystemTime) {
        self.state.borrow_mut().current_timestamp = ts;

        if is_stderr {
            self.stderr_term.write(text);
        } else {
            self.stdout_term.write(text);
        }
    }

    /// Returns the assembled lines in [`KeyValuePair`] form.
    ///
    /// Callers must treat the returned slice as read-only.
    pub fn items(&self) -> Ref<'_, [KeyValuePair]> {
        {
            let mut state = self.state.borrow_mut();
            if state.items.len() != state.lines.len() {
                // Defensive rebuild for any future code path that
                // mutates lines without going through append_line/on_line_changed.
                state.items = state
                    .lines
                    .iter()
                    .map(|line| KeyValuePair {
                        key: format_console_timestamp(line.timestamp),
                        value: line.content.clone(),
                        ..Default::default()
                    })
                    .collect();
            }
        }
        Ref::map(self.state.borrow(), |state| state.items.as_slice())
    }
}

// ---- Terminal emulator integration ----

/// consoleLineSupplier implements [`LineSupplier`].
struct ConsoleLineSupplier {
    owner: Rc<RefCell<ConsoleLogState>>,
    is_stderr: bool,
}

impl LineSupplier for ConsoleLineSupplier {
    fn next_line(&mut self) -> Box<dyn Line> {
        let idx = self.owner.borrow_mut().append_line(self.is_stderr);
        Box::new(ConsoleLine {
            content: LineContent {
                max_length: MAX_CONSOLE_LINE_LENGTH,
                content: Vec::new(),
            },
            owner: Rc::clone(&self.owner),
            index: idx,
            // PARITY: Go's consoleLine carries isStderr but never reads it;
            // dropped here — the stream flag lives on ConsoleLogLine.
        })
    }
}

/// consoleLine implements [`Line`] for a single assembled line.
struct ConsoleLine {
    content: LineContent,
    owner: Rc<RefCell<ConsoleLogState>>,
    index: usize,
}

impl Line for ConsoleLine {
    fn put_char(&mut self, c: char, offset: usize) {
        if self.content.put_char(c, offset) {
            self.owner
                .borrow_mut()
                .on_line_changed(self.index, &self.content.content);
        }
    }
}

// Transliteration of core/internal/leet/runconsolelogs_test.go.
#[cfg(test)]
mod tests {
    use std::time::Duration;

    use pretty_assertions::assert_eq;

    use super::*;

    fn find_kv(items: &[KeyValuePair], value_substr: &str) -> Option<(KeyValuePair, usize)> {
        items
            .iter()
            .enumerate()
            .find(|(_, kv)| kv.value.contains(value_substr))
            .map(|(i, kv)| (kv.clone(), i))
    }

    #[test]
    fn test_run_console_logs_assembles_across_calls_and_preserves_timestamps() {
        let mut cl = RunConsoleLogs::new();

        // Use fixed UTC times for deterministic HH:MM:SS keys.
        // Go: time.Date(2026, time.February, 18, 10, 11, 12, 0, time.UTC).
        let ts1 = UNIX_EPOCH + Duration::from_secs(1_771_409_472);
        let ts2 = ts1 + Duration::from_secs(2);

        // First write starts the current line.
        cl.process_raw("first", false, ts1);

        // Second write begins with a newline, forcing a new line created under ts2.
        cl.process_raw("\nsecond", false, ts2);

        let items = cl.items().to_vec();
        assert!(!items.is_empty(), "expected assembled log items");

        let (kv1, i1) = find_kv(&items, "first").expect("expected to find first line");
        // Go: ts1.Format("15:04:05").
        assert_eq!(
            kv1.key, "10:11:12",
            "first line should keep its creation timestamp"
        );

        let (kv2, i2) = find_kv(&items, "second").expect("expected to find second line");
        // Go: ts2.Format("15:04:05").
        assert_eq!(
            kv2.key, "10:11:14",
            "second line should use the second record timestamp"
        );

        assert!(i1 < i2, "expected log lines to preserve arrival order");
    }
}

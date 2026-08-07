//! `wandb-leet` — the W&B terminal UI, a mechanical Rust port of
//! `core/internal/leet` (Go, Bubble Tea v2). The Go implementation is the
//! behavioral spec; see `leet/docs/PORTING.md` and `leet/docs/PARITY.md`.
//!
//! Port of the `leet` subcommand surface of `core/cmd/wandb-core/main.go`
//! (`leetMain`, `parseLeetOptions`, `bindLeetFlags`, `printLeetUsage`,
//! `validateLeetOptions`, `runLeetCommand`, `runLeetWorkspace`). The CLI
//! contract is snapshotted in PARITY.md §1; exit codes are Go's (§1.3):
//! 0 success (incl. `-h`), 1 internal error, 2 bad args.

use std::fs::OpenOptions;
use std::io;

use leet_data::remote::{RemoteRunParams, parse_remote_url};
use leet_tui::model::{Model, ModelParams};
use leet_tui::run::RunParams;
use leet_tui::runtime;

/// main.go:40-43.
const EXIT_CODE_SUCCESS: i32 = 0;
const EXIT_CODE_ERROR_INTERNAL: i32 = 1;
const EXIT_CODE_ERROR_ARGS: i32 = 2;

/// Go strconv's `errParse` / `errRange` texts as `flag.failf` renders them
/// in the `%v` slot of its error messages.
const ERR_PARSE: &str = "parse error";
const ERR_RANGE: &str = "value out of range";

/// Kind of a registered flag (the `flag.Value` implementations bindLeetFlags
/// registers). `parseOne` treats bool flags specially: they never consume
/// the next argument.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum FlagKind {
    Bool,
    Int,
    Str,
    Duration,
}

/// One row of the leet flag set: name, value kind, `flag.UnquoteUsage`-style
/// usage text, and the non-zero default `flag.PrintDefaults` displays
/// (Go DefValue; zero values are omitted).
struct FlagDef {
    name: &'static str,
    kind: FlagKind,
    usage: &'static str,
    def_value: Option<&'static str>,
}

/// Port of `bindLeetFlags` (main.go:287-327), pre-sorted by name because
/// `flag.PrintDefaults` visits flags in lexical order.
const LEET_FLAGS: &[FlagDef] = &[
    FlagDef {
        name: "config",
        kind: FlagKind::Bool,
        usage: "Open config editor.",
        def_value: None,
    },
    FlagDef {
        name: "interval",
        kind: FlagKind::Duration,
        usage: "Sampling interval for standalone system metrics (e.g. 500ms, 2s, 1m).",
        // PARITY: leet.DefaultSymonSamplingInterval (symonsampler.go:21),
        // rendered by Go as time.Duration.String().
        def_value: Some("2s"),
    },
    FlagDef {
        name: "log-level",
        kind: FlagKind::Int,
        usage: "Specifies the log level to use for logging. -4: debug, 0: info, 4: warn, 8: error.",
        def_value: None,
    },
    FlagDef {
        name: "no-observability",
        kind: FlagKind::Bool,
        usage: "Disables observability features such as metrics and logging analytics.",
        def_value: None,
    },
    FlagDef {
        name: "pprof",
        kind: FlagKind::Str,
        usage: "If set, serves /debug/pprof/* on this address (e.g. 127.0.0.1:6060).",
        def_value: None,
    },
    FlagDef {
        name: "remote-url",
        kind: FlagKind::Str,
        usage: "URL of a W&B run to open (e.g. https://api.wandb.ai/<entity>/<project>/runs/<run-id>).",
        def_value: None,
    },
    FlagDef {
        name: "run-file",
        kind: FlagKind::Str,
        usage: "Path to a .wandb file to open directly in single-run view.",
        def_value: None,
    },
    FlagDef {
        name: "symon",
        kind: FlagKind::Bool,
        usage: "Launch standalone system metrics mode.",
        def_value: None,
    },
];

/// The leet flag set: a hand-rolled port of Go's `flag` package parsing
/// (`flag.FlagSet.parseOne`, flag.go) over `bindLeetFlags`
/// (main.go:287-327).
///
/// clap cannot reproduce Go's flag grammar (PARITY.md §1.2 / SH-01, probed
/// against the Go binary): parsing stops at the first positional
/// (`./wandb --symon` leaves `--symon` an ignored positional), extra
/// positionals are ignored (only `fs.Arg(0)` is read), long flags accept a
/// single dash (`-run-file x`), bool flags accept `-symon=false` but never
/// consume the next argument, and `--` terminates flag parsing.
#[derive(Debug)]
struct LeetFlagSet {
    log_level: i64,
    no_observability: bool,
    run_file: String,
    pprof: String,
    config: bool,
    symon: bool,
    /// Nanoseconds (Go `time.Duration`).
    interval: i64,
    remote_url: String,
    /// Arguments after the last parsed flag (Go `fs.args`): `args[0]` is
    /// the wandb directory (`fs.Arg(0)`), the rest are ignored.
    args: Vec<String>,
}

impl Default for LeetFlagSet {
    /// The `bindLeetFlags` defaults (main.go:287-327).
    fn default() -> Self {
        LeetFlagSet {
            log_level: 0,
            no_observability: false,
            run_file: String::new(),
            pprof: String::new(),
            config: false,
            symon: false,
            // PARITY: leet.DefaultSymonSamplingInterval = 2s
            // (symonsampler.go:21).
            interval: 2_000_000_000,
            remote_url: String::new(),
            args: Vec::new(),
        }
    }
}

impl LeetFlagSet {
    /// Port of `flag.FlagSet.Parse` (ContinueOnError): parses flags until
    /// the first non-flag argument or the `--` terminator; the remainder
    /// becomes the positional args.
    ///
    /// `Err` carries the process exit code — EXIT_CODE_SUCCESS for
    /// `-h`/`-help` (Go `flag.ErrHelp`), EXIT_CODE_ERROR_ARGS for parse
    /// failures — with the message + usage already printed to stderr
    /// (Go: `fs.SetOutput(os.Stderr)`).
    fn parse(&mut self, arguments: &[String]) -> Result<(), i32> {
        let mut i = 0usize;
        while self.parse_one(arguments, &mut i)? {}
        self.args = arguments[i..].to_vec();
        Ok(())
    }

    /// Port of `flag.FlagSet.parseOne` (flag.go): handles one flag token;
    /// `Ok(false)` means parsing stops (positional, `--`, or end of argv).
    fn parse_one(&mut self, arguments: &[String], i: &mut usize) -> Result<bool, i32> {
        let Some(s) = arguments.get(*i).map(String::as_str) else {
            return Ok(false);
        };
        let b = s.as_bytes();
        if b.len() < 2 || b[0] != b'-' {
            // PARITY: "" and a bare "-" are positionals and stop parsing.
            return Ok(false);
        }
        let mut num_minuses = 1;
        if b[1] == b'-' {
            num_minuses += 1;
            if b.len() == 2 {
                // "--" terminates the flags
                *i += 1;
                return Ok(false);
            }
        }
        let mut name = &s[num_minuses..];
        if name.is_empty() || name.as_bytes()[0] == b'-' || name.as_bytes()[0] == b'=' {
            return Err(flag_failf(&format!("bad flag syntax: {s}")));
        }

        // it's a flag. does it have an argument?
        *i += 1;
        let mut has_value = false;
        let mut value = String::new();
        // equals cannot be first ('=' is ASCII, so byte offsets are char
        // boundaries).
        if let Some(eq) = name[1..].find('=') {
            value = name[eq + 2..].to_string();
            has_value = true;
            name = &name[..eq + 1];
        }

        let Some(def) = LEET_FLAGS.iter().find(|d| d.name == name) else {
            if name == "help" || name == "h" {
                // special case for nice help message.
                print_leet_usage();
                // Go flag.ErrHelp → leetMain returns exitCodeSuccess.
                return Err(EXIT_CODE_SUCCESS);
            }
            return Err(flag_failf(&format!(
                "flag provided but not defined: -{name}"
            )));
        };

        if def.kind == FlagKind::Bool {
            // special case: doesn't need an arg
            if has_value {
                if let Err(err) = self.set(def.name, &value) {
                    return Err(flag_failf(&format!(
                        "invalid boolean value {} for -{name}: {err}",
                        go_quote(&value)
                    )));
                }
            } else if let Err(err) = self.set(def.name, "true") {
                return Err(flag_failf(&format!("invalid boolean flag {name}: {err}")));
            }
        } else {
            // It must have a value, which might be the next argument.
            if !has_value && *i < arguments.len() {
                // value is the next arg (consumed verbatim — `--interval
                // -2s` parses, then fails the `> 0` validation).
                has_value = true;
                value = arguments[*i].clone();
                *i += 1;
            }
            if !has_value {
                return Err(flag_failf(&format!("flag needs an argument: -{name}")));
            }
            if let Err(err) = self.set(def.name, &value) {
                return Err(flag_failf(&format!(
                    "invalid value {} for flag -{name}: {err}",
                    go_quote(&value)
                )));
            }
        }
        Ok(true)
    }

    /// Port of the registered `flag.Value.Set` methods (bindLeetFlags): the
    /// returned string is Go's error text for the failf `%v` slot.
    fn set(&mut self, name: &str, value: &str) -> Result<(), &'static str> {
        match name {
            "log-level" => self.log_level = parse_go_int(value)?,
            "no-observability" => self.no_observability = parse_go_bool(value)?,
            "run-file" => self.run_file = value.to_string(),
            "pprof" => self.pprof = value.to_string(),
            "config" => self.config = parse_go_bool(value)?,
            "symon" => self.symon = parse_go_bool(value)?,
            // PARITY: flag.durationValue maps every time.ParseDuration
            // error to errParse.
            "interval" => self.interval = parse_go_duration(value).map_err(|_| ERR_PARSE)?,
            "remote-url" => self.remote_url = value.to_string(),
            _ => unreachable!("unknown flag {name}"),
        }
        Ok(())
    }
}

/// Port of `flag.FlagSet.failf`: print the message and the usage to stderr;
/// returns the exit code the caller propagates (Go returns the error and
/// `leetMain` maps any non-ErrHelp parse error to exitCodeErrorArgs).
fn flag_failf(msg: &str) -> i32 {
    eprintln!("{msg}");
    print_leet_usage();
    EXIT_CODE_ERROR_ARGS
}

/// Port of `printLeetUsage` (main.go:329-349) + `flag.PrintDefaults`.
/// Everything goes to stderr (Go: `fs.SetOutput(os.Stderr)`).
// PARITY: the Go text reads "wandb-core leet"; the standalone binary name
// "wandb-leet" is substituted (the only difference).
fn print_leet_usage() {
    let mut out = String::from(
        "wandb-leet - Lightweight Experiment Exploration Tool\n\
         A terminal UI for viewing your W&B runs locally.\n\
         \n\
         Usage:\n  \
         wandb-leet [flags] <wandb-directory>\n  \
         wandb-leet --run-file <wandb-file> <wandb-directory>\n  \
         wandb-leet --remote-url <wandb-run-url>\n  \
         wandb-leet --config\n  \
         wandb-leet --symon [flags]\n\
         \n\
         Arguments:\n  \
         <wandb-directory>  Path to the wandb directory containing run folders.\n\
         \n\
         Options:\n  \
         -h, --help         Show this help message\n\
         \n\
         Flags:\n",
    );
    // flag.PrintDefaults: "  -name type\n    \tusage"; non-zero defaults
    // appended as " (default v)". None of the leet flags is a single-letter
    // bool, so PrintDefaults' same-line special case never fires; none is a
    // string with a non-zero default, so the %q default form never fires.
    for def in LEET_FLAGS {
        out.push_str("  -");
        out.push_str(def.name);
        let type_name = match def.kind {
            FlagKind::Bool => "",
            FlagKind::Int => "int",
            FlagKind::Str => "string",
            FlagKind::Duration => "duration",
        };
        if !type_name.is_empty() {
            out.push(' ');
            out.push_str(type_name);
        }
        out.push_str("\n    \t");
        out.push_str(&def.usage.replace('\n', "\n    \t"));
        if let Some(dv) = def.def_value {
            out.push_str(&format!(" (default {dv})"));
        }
        out.push('\n');
    }
    eprint!("{out}");
}

/// Go `%q` (strconv.Quote) for the strings that reach flag error messages.
// PARITY: strconv.Quote also escapes non-printable Unicode with \u forms;
// argv slices this quotes are overwhelmingly printable ASCII, so only the
// standard escapes are implemented (same shape as leet-data config.rs).
fn go_quote(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\x07' => out.push_str("\\a"),
            '\x08' => out.push_str("\\b"),
            '\x0c' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\x0b' => out.push_str("\\v"),
            c if (c as u32) < 0x20 || c == '\x7f' => {
                out.push_str(&format!("\\x{:02x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

/// Port of `strconv.ParseBool` (flag.boolValue.Set maps its error to
/// errParse).
fn parse_go_bool(s: &str) -> Result<bool, &'static str> {
    match s {
        "1" | "t" | "T" | "true" | "TRUE" | "True" => Ok(true),
        "0" | "f" | "F" | "false" | "FALSE" | "False" => Ok(false),
        _ => Err(ERR_PARSE),
    }
}

/// Port of `strconv.ParseInt(value, 0, 64)` — the parser behind Go's
/// `flag.IntVar` (--log-level): optional sign, base prefixes 0b/0o/0x and
/// legacy leading-0 octal, `_` digit separators. Syntax errors map to
/// flag's "parse error", overflow to "value out of range".
fn parse_go_int(s0: &str) -> Result<i64, &'static str> {
    if s0.is_empty() {
        return Err(ERR_PARSE);
    }
    // Pick off leading sign (strconv.ParseInt).
    let mut s = s0;
    let mut neg = false;
    if let Some(rest) = s.strip_prefix('+') {
        s = rest;
    } else if let Some(rest) = s.strip_prefix('-') {
        neg = true;
        s = rest;
    }
    if s.is_empty() {
        return Err(ERR_PARSE);
    }
    // ParseUint's s0 — underscore placement is validated against it below.
    let s_uint = s;

    // Look for octal, hex prefix (ParseUint, base == 0).
    let b = s.as_bytes();
    let mut base: u64 = 10;
    if b[0] == b'0' {
        if b.len() >= 3 && (b[1] | 0x20) == b'b' {
            base = 2;
            s = &s[2..];
        } else if b.len() >= 3 && (b[1] | 0x20) == b'o' {
            base = 8;
            s = &s[2..];
        } else if b.len() >= 3 && (b[1] | 0x20) == b'x' {
            base = 16;
            s = &s[2..];
        } else {
            base = 8;
            s = &s[1..];
        }
    }

    // Cutoff is the smallest number such that cutoff*base > maxUint64.
    let cutoff = u64::MAX / base + 1;
    let mut n: u64 = 0;
    for &c in s.as_bytes() {
        let d: u8 = if c == b'_' {
            // Underscore placement is validated below (underscoreOK).
            continue;
        } else if c.is_ascii_digit() {
            c - b'0'
        } else if (c | 0x20).is_ascii_lowercase() {
            (c | 0x20) - b'a' + 10
        } else {
            return Err(ERR_PARSE);
        };
        if u64::from(d) >= base {
            return Err(ERR_PARSE);
        }
        if n >= cutoff {
            // n*base overflows
            return Err(ERR_RANGE);
        }
        n *= base;
        let n1 = n.wrapping_add(u64::from(d));
        if n1 < n {
            // n+d overflows (maxVal for bitSize 64 is maxUint64)
            return Err(ERR_RANGE);
        }
        n = n1;
    }
    if !underscore_ok(s_uint) {
        return Err(ERR_PARSE);
    }

    // ParseInt's signed range check (bitSize 64).
    let cutoff_i: u64 = 1 << 63;
    if !neg && n >= cutoff_i {
        return Err(ERR_RANGE);
    }
    if neg && n > cutoff_i {
        return Err(ERR_RANGE);
    }
    // n == 1<<63 with neg wraps to i64::MIN, like Go's int64(-n).
    Ok(if neg {
        (n as i64).wrapping_neg()
    } else {
        n as i64
    })
}

/// Port of strconv's `underscoreOK`: underscores must separate successive
/// digits or sit between the base prefix and the first digit.
fn underscore_ok(s: &str) -> bool {
    // saw tracks the last character (class) we saw:
    // ^ for beginning of number, 0 for a digit or base prefix,
    // _ for an underscore, ! for none of the above.
    let mut saw = b'^';
    let mut s = s.as_bytes();
    // Optional sign.
    if !s.is_empty() && (s[0] == b'-' || s[0] == b'+') {
        s = &s[1..];
    }
    // Optional base prefix.
    let mut i = 0usize;
    let mut hex = false;
    if s.len() >= 2 && s[0] == b'0' && matches!(s[1] | 0x20, b'b' | b'o' | b'x') {
        i = 2;
        saw = b'0'; // base prefix counts as a digit for "underscore as digit separator"
        hex = (s[1] | 0x20) == b'x';
    }
    // Number proper.
    while i < s.len() {
        let c = s[i];
        i += 1;
        // Digits are always okay.
        if c.is_ascii_digit() || (hex && matches!(c | 0x20, b'a'..=b'f')) {
            saw = b'0';
            continue;
        }
        // Underscore must follow digit.
        if c == b'_' {
            if saw != b'0' {
                return false;
            }
            saw = b'_';
            continue;
        }
        // Underscore must also be followed by digit.
        if saw == b'_' {
            return false;
        }
        // Saw non-digit, non-underscore.
        saw = b'!';
    }
    saw != b'_'
}

/// Port of `leetOptions` (main.go:248-265).
#[derive(Debug)]
struct LeetOptions {
    log_level: i64,
    /// Accepted for CLI compatibility; Sentry analytics are not wired yet
    /// (PARITY.md §4).
    #[allow(dead_code)]
    disable_analytics: bool,
    run_file: String,
    pprof_addr: String,
    edit_config: bool,
    symon_mode: bool,
    /// Nanoseconds (Go `time.Duration`).
    #[allow(dead_code)]
    symon_interval_ns: i64,
    wandb_dir: String,
    /// Whether any positional was present at all (Go `fs.NArg() != 0` vs
    /// `opts.wandbDir != ""` — the --symon check uses presence).
    wandb_dir_present: bool,

    /// remoteURL is the W&B URL of the run to open. Non-empty means we are
    /// in remote mode.
    remote_url: String,

    /// remoteRun is the parsed remoteURL. Set during validation.
    remote_run: Option<RemoteRunParams>,
}

fn main() {
    std::process::exit(leet_main());
}

/// Port of `leetMain` (main.go:219-246).
fn leet_main() -> i32 {
    // parseLeetOptions (main.go:267-285): flag parse failures (bad values,
    // unknown flags) print the failf message + usage and exit 2; -h/-help
    // prints usage and exits 0 (flag.ErrHelp).
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let mut fs = LeetFlagSet::default();
    if let Err(code) = fs.parse(&argv) {
        return code;
    }
    let opts = match validate_leet_options(fs) {
        Ok(opts) => opts,
        Err(code) => return code,
    };

    // PARITY: startLeetPprof (main.go:228-233). PARITY.md §4: the flag must
    // be accepted and must not error; the profiler itself is not served.
    if !opts.pprof_addr.is_empty() {
        eprintln!("wandb-leet: --pprof is accepted but not implemented; ignoring");
    }

    // PARITY: configureLeetSentry (main.go:235-236) — telemetry is off by
    // default until wired (PARITY.md §4); --no-observability is accepted.

    let _log_file = match new_leet_logger(opts.log_level) {
        Ok(file) => file,
        Err(err) => {
            // PARITY: Go prints this one to STDOUT (main.go:240).
            println!("fatal: {err}");
            return EXIT_CODE_ERROR_INTERNAL;
        }
    };

    run_leet_command(&opts)
}

/// Port of `validateLeetOptions` (main.go:351-386) plus the option
/// construction in `parseLeetOptions` (main.go:279 `opts.wandbDir =
/// fs.Arg(0)`): same check order, same `Error: …` + usage lines on stderr,
/// exit 2 on failure.
fn validate_leet_options(fs: LeetFlagSet) -> Result<LeetOptions, i32> {
    let mut opts = LeetOptions {
        log_level: fs.log_level,
        disable_analytics: fs.no_observability,
        run_file: fs.run_file,
        pprof_addr: fs.pprof,
        edit_config: fs.config,
        symon_mode: fs.symon,
        symon_interval_ns: fs.interval,
        // PARITY: Go reads only `fs.Arg(0)`; extra positionals are ignored.
        wandb_dir: fs.args.first().cloned().unwrap_or_default(),
        wandb_dir_present: !fs.args.is_empty(),
        remote_url: fs.remote_url,
        remote_run: None,
    };

    if !opts.remote_url.is_empty() {
        match parse_remote_url(&opts.remote_url) {
            Ok(remote) => opts.remote_run = Some(remote),
            Err(err) => return Err(usage_error(&err.to_string())),
        }
    }

    if opts.symon_interval_ns <= 0 {
        return Err(usage_error("--interval must be > 0"));
    }
    if opts.remote_run.is_some() && !opts.run_file.is_empty() {
        return Err(usage_error("--run-file cannot be used with --remote-url"));
    }
    if opts.remote_run.is_some() && !opts.wandb_dir.is_empty() {
        return Err(usage_error("--remote-url does not take a wandb directory"));
    }
    // PARITY: Go checks `fs.NArg() != 0` here, not the string value.
    if opts.symon_mode && opts.wandb_dir_present {
        return Err(usage_error("--symon does not take a wandb directory"));
    }
    if !opts.edit_config
        && !opts.symon_mode
        && opts.wandb_dir.is_empty()
        && opts.remote_run.is_none()
    {
        return Err(usage_error("wandb directory path or --remote-url required"));
    }

    Ok(opts)
}

/// The `fmt.Fprintln(os.Stderr, "Error:", …)` + `fs.Usage()` pair every
/// validation failure prints (main.go:355-381).
fn usage_error(msg: &str) -> i32 {
    eprintln!("Error: {msg}");
    print_leet_usage();
    EXIT_CODE_ERROR_ARGS
}

/// Port of `newLeetLogger` (main.go:435-461): `--log-level -4` creates and
/// truncates `wandb-leet.debug.log` in the cwd; any other level logs
/// nowhere (Go: io.Discard).
///
/// PHASE-5 NOTE: wiring library `tracing` events into the file needs a
/// `tracing-subscriber` writer, and neither `tracing` nor
/// `tracing-subscriber` is a dependency of this crate yet — until that dep
/// lands the file is created/truncated exactly like Go and stays empty
/// (PARITY.md §4 requires only that the flag parses and gates verbosity,
/// not byte-identical log content). The handle is held for the process
/// lifetime like Go's `closeLogWriter` deferred close.
fn new_leet_logger(log_level: i64) -> io::Result<Option<std::fs::File>> {
    // TODO: Create a log file not only if debug logging is requested.
    if log_level != -4 {
        return Ok(None);
    }
    OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open("wandb-leet.debug.log")
        .map(Some)
}

/// Port of `runLeetCommand` (main.go:463-471). The config-editor and symon
/// dispatch targets are unported phases; they exit with a clear message
/// instead of silently falling through to the workspace.
fn run_leet_command(opts: &LeetOptions) -> i32 {
    if opts.edit_config {
        // PHASE-6: configeditor.go.
        eprintln!(
            "wandb-leet: the config editor is not yet ported; use `wandb-core leet --config` meanwhile"
        );
        return EXIT_CODE_ERROR_INTERNAL;
    }
    if opts.symon_mode {
        // PHASE-6: symon.go.
        eprintln!(
            "wandb-leet: standalone system-metrics mode is not yet ported; use `wandb-core leet --symon` meanwhile"
        );
        return EXIT_CODE_ERROR_INTERNAL;
    }
    if opts.remote_run.is_some() {
        // PHASE-7: leet-remote. The URL was still parsed/validated above so
        // bad URLs fail with Go's exit code 2, not this message.
        eprintln!(
            "wandb-leet: remote mode (--remote-url) is not yet ported; use `wandb-core leet --remote-url` meanwhile"
        );
        return EXIT_CODE_ERROR_INTERNAL;
    }
    run_leet_workspace(opts)
}

/// Port of `runLeetWorkspace` (main.go:505-532): the alt+r restart loop.
fn run_leet_workspace(opts: &LeetOptions) -> i32 {
    let run_params = if let Some(remote) = &opts.remote_run {
        Some(RunParams {
            run_file: String::new(),
            remote: Some(remote.clone()),
        })
    } else if !opts.run_file.is_empty() {
        Some(RunParams {
            run_file: opts.run_file.clone(),
            remote: None,
        })
    } else {
        None
    };

    loop {
        let mut model = Model::new(ModelParams {
            wandb_dir: opts.wandb_dir.clone(),
            run_params: run_params.clone(),
            config: None,
        });

        if let Err(err) = runtime::run(&mut model) {
            // Go: logger.CaptureError(fmt.Errorf("wandb-leet: %v", err)).
            eprintln!("wandb-leet: {err}");
            return EXIT_CODE_ERROR_INTERNAL;
        }

        // PARITY(fixed Go bug, recorded in CONCURRENCY.md §1.6): Go's loop
        // never calls m.Cleanup() before constructing the next Model on
        // ShouldRestart (main.go:527), leaking watchers, the heartbeat
        // timer, and open readers per alt+r restart. Here `runtime::run`
        // calls `App::cleanup` on every session exit and the Model drops at
        // the end of each iteration (§2.9).
        if !model.should_restart() {
            return EXIT_CODE_SUCCESS;
        }
    }
}

/// Port of Go `time.ParseDuration` for the `--interval` flag
/// (`flag.DurationVar`, main.go:314-319): `[-+]?(<digits>[.<digits>]<unit>)+`
/// with units ns, us/µs/μs, ms, s, m, h; a bare signed "0" is allowed.
/// Returns nanoseconds.
///
/// The accumulation mirrors Go's uint64 shape exactly, including the
/// fraction path `v += uint64(float64(f) * (float64(unit) / scale))` —
/// "0.5337s" must yield 533700000ns, not the 533699999 that a float-only
/// `0.5337 * 1e9` double-rounding produces. Error wording may differ
/// (PARITY.md §4); the flag layer collapses it to "parse error" anyway,
/// like Go's flag.durationValue.
fn parse_go_duration(orig: &str) -> Result<i64, String> {
    let invalid = || format!("invalid duration {orig:?}");

    // Consume [-+]?
    let mut s = orig;
    let mut neg = false;
    if let Some(rest) = s.strip_prefix('-') {
        neg = true;
        s = rest;
    } else if let Some(rest) = s.strip_prefix('+') {
        s = rest;
    }
    // Special case: if all that is left is "0", this is zero.
    if s == "0" {
        return Ok(0);
    }
    if s.is_empty() {
        return Err(invalid());
    }

    let mut d: u64 = 0;
    while !s.is_empty() {
        // The next character must be [0-9.]
        let c = s.as_bytes()[0];
        if !(c == b'.' || c.is_ascii_digit()) {
            return Err(invalid());
        }
        // Consume [0-9]*
        let pl = s.len();
        let (mut v, rest) = leading_int(s).ok_or_else(invalid)?;
        s = rest;
        let pre = pl != s.len(); // whether we consumed anything before a period

        // Consume (\.[0-9]*)?
        let mut f: u64 = 0;
        let mut scale: f64 = 1.0;
        let mut post = false;
        if let Some(after_dot) = s.strip_prefix('.') {
            let pl = after_dot.len();
            let (ff, sc, rest) = leading_fraction(after_dot);
            f = ff;
            scale = sc;
            s = rest;
            post = pl != s.len();
        }
        if !pre && !post {
            // no digits (e.g. ".s" or "-.s")
            return Err(invalid());
        }

        // Consume unit.
        let unit_end = s
            .find(|c: char| c == '.' || c.is_ascii_digit())
            .unwrap_or(s.len());
        if unit_end == 0 {
            return Err(format!("missing unit in duration {orig:?}"));
        }
        let (u, rest) = s.split_at(unit_end);
        s = rest;
        let unit: u64 = match u {
            "ns" => 1,
            "us" | "µs" | "μs" => 1_000,
            "ms" => 1_000_000,
            "s" => 1_000_000_000,
            "m" => 60_000_000_000,
            "h" => 3_600_000_000_000,
            _ => return Err(format!("unknown unit {u:?} in duration {orig:?}")),
        };
        if v > (1 << 63) / unit {
            // overflow
            return Err(invalid());
        }
        v *= unit;
        if f > 0 {
            // float64 is needed to be nanosecond accurate for fractions of
            // hours. v >= 0 && (f*unit/scale) <= 3.6e+12 (ns/h, h is the
            // largest unit)
            v = v.wrapping_add((f as f64 * (unit as f64 / scale)) as u64);
            if v > 1 << 63 {
                // overflow
                return Err(invalid());
            }
        }
        // PARITY: Go's uint64 `d += v` wraps silently (both operands can be
        // 1<<63, so the sum can reach exactly 2^64 → 0).
        d = d.wrapping_add(v);
        if d > 1 << 63 {
            return Err(invalid());
        }
    }

    if neg {
        // PARITY: Go returns -Duration(d) before the max check, so
        // "-9223372036854775808ns" parses to i64::MIN (wrapping negate).
        return Ok((d as i64).wrapping_neg());
    }
    if d > (1 << 63) - 1 {
        return Err(invalid());
    }
    Ok(d as i64)
}

/// Port of `time.leadingInt`: consume [0-9]*; `None` on overflow past 1<<63.
fn leading_int(s: &str) -> Option<(u64, &str)> {
    let mut x: u64 = 0;
    let b = s.as_bytes();
    let mut i = 0usize;
    while i < b.len() {
        let c = b[i];
        if !c.is_ascii_digit() {
            break;
        }
        if x > (1 << 63) / 10 {
            // overflow
            return None;
        }
        x = x * 10 + u64::from(c - b'0');
        if x > 1 << 63 {
            // overflow
            return None;
        }
        i += 1;
    }
    Some((x, &s[i..]))
}

/// Port of `time.leadingFraction`: consume [0-9]*, accumulating the raw
/// digits into an integer `x` with `scale *= 10` per digit; once `x` would
/// overflow, further digits are consumed but ignored (and stop scaling).
fn leading_fraction(s: &str) -> (u64, f64, &str) {
    let mut x: u64 = 0;
    let mut scale: f64 = 1.0;
    let mut overflow = false;
    let b = s.as_bytes();
    let mut i = 0usize;
    while i < b.len() {
        let c = b[i];
        if !c.is_ascii_digit() {
            break;
        }
        i += 1;
        if overflow {
            continue;
        }
        if x > ((1 << 63) - 1) / 10 {
            // It's possible for overflow to give a positive number, so take care.
            overflow = true;
            continue;
        }
        let y = x * 10 + u64::from(c - b'0');
        if y > 1 << 63 {
            overflow = true;
            continue;
        }
        x = y;
        scale *= 10.0;
    }
    (x, scale, &s[i..])
}

#[cfg(test)]
mod tests {
    // std assert_eq: `pretty_assertions` is not a dev-dependency of this
    // crate (Cargo.toml is frozen for this unit).
    use super::*;

    /// Parses argv (WITHOUT the program name, like Go's `leetMain(args)`)
    /// through the ported flag set.
    fn try_parse(argv: &[&str]) -> Result<LeetFlagSet, i32> {
        let args: Vec<String> = argv.iter().map(|s| (*s).to_string()).collect();
        let mut fs = LeetFlagSet::default();
        fs.parse(&args).map(|()| fs)
    }

    fn parse(argv: &[&str]) -> LeetFlagSet {
        try_parse(argv).expect("flag parse failed")
    }

    #[test]
    fn parse_go_duration_cases() {
        // Table mirrors time.ParseDuration's documented syntax; case names
        // are the inputs.
        assert_eq!(parse_go_duration("0").unwrap(), 0);
        assert_eq!(parse_go_duration("-0").unwrap(), 0);
        assert_eq!(parse_go_duration("500ms").unwrap(), 500_000_000);
        assert_eq!(parse_go_duration("2s").unwrap(), 2_000_000_000);
        assert_eq!(parse_go_duration("1m").unwrap(), 60_000_000_000);
        assert_eq!(parse_go_duration("1m30s").unwrap(), 90_000_000_000);
        assert_eq!(parse_go_duration("1.5m").unwrap(), 90_000_000_000);
        assert_eq!(parse_go_duration("1h").unwrap(), 3_600_000_000_000);
        assert_eq!(parse_go_duration("1.5h").unwrap(), 5_400_000_000_000);
        assert_eq!(parse_go_duration("-2s").unwrap(), -2_000_000_000);
        assert_eq!(parse_go_duration("100us").unwrap(), 100_000);
        assert_eq!(parse_go_duration("100µs").unwrap(), 100_000);
        assert_eq!(parse_go_duration("300ns").unwrap(), 300);
        assert_eq!(parse_go_duration(".5s").unwrap(), 500_000_000);

        assert!(parse_go_duration("").is_err());
        assert!(parse_go_duration("2").is_err(), "missing unit");
        assert!(parse_go_duration("2x").is_err(), "unknown unit");
        assert!(parse_go_duration("s").is_err(), "no number");
        assert!(parse_go_duration("-").is_err());
    }

    /// The fraction path must reproduce Go's integer-digits × (unit/scale)
    /// arithmetic, not a float-literal multiply (review: 0.5337s parsed to
    /// 533699999ns with the `("0."+frac) * scale` shape; Go says 533700000).
    #[test]
    fn parse_go_duration_fraction_matches_go_rounding() {
        // Values verified with Go time.ParseDuration.
        assert_eq!(parse_go_duration("0.5337s").unwrap(), 533_700_000);
        assert_eq!(parse_go_duration("0.262024s").unwrap(), 262_024_000);
        assert_eq!(parse_go_duration("0.52051933s").unwrap(), 520_519_330);
    }

    /// Overflow boundaries from Go's time_test.go table.
    #[test]
    fn parse_go_duration_overflow_boundaries() {
        assert_eq!(
            parse_go_duration("9223372036854775.807us").unwrap(),
            i64::MAX
        );
        assert_eq!(
            parse_go_duration("-9223372036854775808ns").unwrap(),
            i64::MIN
        );
        assert!(parse_go_duration("9223372036854775808ns").is_err());
        assert!(parse_go_duration("9223372036854775808s").is_err());
    }

    /// PARITY.md §1.3 validation matrix (each failure exits 2 with an
    /// `Error:` line; combinations that pass produce options).
    #[test]
    fn validate_leet_options_matrix() {
        // wandb dir alone: ok.
        assert!(validate_leet_options(parse(&["./wandb"])).is_ok());
        // nothing: required error.
        assert_eq!(
            validate_leet_options(parse(&[])).unwrap_err(),
            EXIT_CODE_ERROR_ARGS
        );
        // --config alone: ok (no wandb dir required).
        assert!(validate_leet_options(parse(&["--config"])).is_ok());
        // --symon alone: ok; --symon with a dir (even ""): error.
        assert!(validate_leet_options(parse(&["--symon"])).is_ok());
        assert_eq!(
            validate_leet_options(parse(&["--symon", "./wandb"])).unwrap_err(),
            EXIT_CODE_ERROR_ARGS
        );
        assert_eq!(
            validate_leet_options(parse(&["--symon", ""])).unwrap_err(),
            EXIT_CODE_ERROR_ARGS,
            "Go checks fs.NArg() != 0, so an empty positional still errors"
        );
        // --interval must be > 0 (checked even outside --symon mode); the
        // flag package consumes the next argv verbatim, dashes and all.
        assert_eq!(
            validate_leet_options(parse(&["--interval", "-2s", "./wandb"])).unwrap_err(),
            EXIT_CODE_ERROR_ARGS
        );
        // --remote-url: parses, forbids --run-file and a wandb dir.
        let url = "https://api.wandb.ai/ent/proj/runs/r1";
        let opts = validate_leet_options(parse(&["--remote-url", url])).unwrap();
        assert!(opts.remote_run.is_some());
        assert_eq!(
            validate_leet_options(parse(&["--remote-url", url, "--run-file", "x.wandb"]))
                .unwrap_err(),
            EXIT_CODE_ERROR_ARGS
        );
        assert_eq!(
            validate_leet_options(parse(&["--remote-url", url, "./wandb"])).unwrap_err(),
            EXIT_CODE_ERROR_ARGS
        );
        assert_eq!(
            validate_leet_options(parse(&["--remote-url", "not a url"])).unwrap_err(),
            EXIT_CODE_ERROR_ARGS
        );
        // --run-file with a wandb dir: ok.
        let opts = validate_leet_options(parse(&["--run-file", "x.wandb", "./wandb"])).unwrap();
        assert_eq!(opts.run_file, "x.wandb");
        assert_eq!(opts.wandb_dir, "./wandb");
    }

    #[test]
    fn interval_default_is_2s() {
        // PARITY: leet.DefaultSymonSamplingInterval (symonsampler.go:21).
        assert_eq!(LeetFlagSet::default().interval, 2_000_000_000);
        assert_eq!(parse(&["./wandb"]).interval, 2_000_000_000);
    }

    #[test]
    fn bad_interval_is_a_parse_error() {
        // Go flag.DurationVar fails flag.Parse → exit 2 path.
        assert_eq!(
            try_parse(&["--interval", "nope", "./wandb"]).unwrap_err(),
            EXIT_CODE_ERROR_ARGS
        );
    }

    /// Probed Go behavior (review SH-01): flag parsing stops at the first
    /// positional; later flag-looking tokens are ignored positionals.
    /// `wandb-core leet ./wandb --symon` → symon=false, NArg=2.
    #[test]
    fn flag_parsing_stops_at_first_positional() {
        let fs = parse(&["./wandb", "--symon"]);
        assert!(!fs.symon);
        assert_eq!(fs.args, vec!["./wandb", "--symon"]);
        let opts = validate_leet_options(fs).unwrap();
        assert_eq!(opts.wandb_dir, "./wandb");
        assert!(!opts.symon_mode);

        // Same class: `./wandb --run-file x` ignores --run-file.
        let fs = parse(&["./wandb", "--run-file", "x.wandb"]);
        assert_eq!(fs.run_file, "");
        let opts = validate_leet_options(fs).unwrap();
        assert_eq!(opts.wandb_dir, "./wandb");
        assert!(opts.run_file.is_empty());
    }

    /// Probed Go behavior (review SH-01): extra positionals are ignored —
    /// only `fs.Arg(0)` is read. `wandb-core leet ./wandb extra` runs.
    #[test]
    fn extra_positionals_are_ignored() {
        let fs = parse(&["./wandb", "extra", "args"]);
        assert_eq!(fs.args, vec!["./wandb", "extra", "args"]);
        let opts = validate_leet_options(fs).unwrap();
        assert_eq!(opts.wandb_dir, "./wandb");
    }

    /// Probed Go behavior (review SH-01): the flag package accepts a single
    /// dash for long flags.
    #[test]
    fn single_dash_long_flags_parse() {
        let fs = parse(&["-run-file", "x.wandb", "./wandb"]);
        assert_eq!(fs.run_file, "x.wandb");
        assert_eq!(fs.args, vec!["./wandb"]);

        let fs = parse(&["-symon"]);
        assert!(fs.symon);
    }

    /// Probed Go behavior (review SH-01): bool flags take `=value` syntax
    /// and never consume the next argument.
    #[test]
    fn bool_flag_value_syntax() {
        let fs = parse(&["-symon=false", "./wandb"]);
        assert!(!fs.symon);
        assert!(validate_leet_options(fs).is_ok());

        let fs = parse(&["--symon=true"]);
        assert!(fs.symon);

        // strconv.ParseBool forms.
        assert!(parse(&["--symon=1"]).symon);
        assert!(!parse(&["--symon=F"]).symon);
        assert_eq!(
            try_parse(&["--symon=maybe"]).unwrap_err(),
            EXIT_CODE_ERROR_ARGS
        );

        // A bool flag does not eat the next token: it becomes a positional.
        let fs = parse(&["--symon", "true"]);
        assert!(fs.symon);
        assert_eq!(fs.args, vec!["true"]);
    }

    /// `--` terminates flag parsing; everything after is positional.
    #[test]
    fn double_dash_terminates_flags() {
        let fs = parse(&["--", "--symon"]);
        assert!(!fs.symon);
        assert_eq!(fs.args, vec!["--symon"]);
        let opts = validate_leet_options(fs).unwrap();
        assert_eq!(opts.wandb_dir, "--symon");

        // A bare "-" is a positional, not a flag.
        let fs = parse(&["-"]);
        assert_eq!(fs.args, vec!["-"]);
    }

    /// Go exit codes: -h/-help/--help → flag.ErrHelp → 0; unknown flags,
    /// missing values, and bad syntax → 2.
    #[test]
    fn flag_error_exit_codes() {
        assert_eq!(try_parse(&["-h"]).unwrap_err(), EXIT_CODE_SUCCESS);
        assert_eq!(try_parse(&["--help"]).unwrap_err(), EXIT_CODE_SUCCESS);
        assert_eq!(try_parse(&["-help"]).unwrap_err(), EXIT_CODE_SUCCESS);

        assert_eq!(try_parse(&["--nope"]).unwrap_err(), EXIT_CODE_ERROR_ARGS);
        assert_eq!(try_parse(&["-x"]).unwrap_err(), EXIT_CODE_ERROR_ARGS);
        assert_eq!(
            try_parse(&["--run-file"]).unwrap_err(),
            EXIT_CODE_ERROR_ARGS
        );
        assert_eq!(try_parse(&["---x"]).unwrap_err(), EXIT_CODE_ERROR_ARGS);
        assert_eq!(try_parse(&["--=x"]).unwrap_err(), EXIT_CODE_ERROR_ARGS);
    }

    /// --log-level goes through strconv.ParseInt(s, 0, 64): sign, base
    /// prefixes, and underscore separators.
    #[test]
    fn log_level_parses_like_go_int() {
        assert_eq!(parse(&["--log-level", "-4", "./wandb"]).log_level, -4);
        assert_eq!(parse(&["--log-level=-4", "./wandb"]).log_level, -4);
        assert_eq!(parse(&["--log-level", "0x10", "./wandb"]).log_level, 16);
        assert_eq!(parse(&["--log-level", "0b101", "./wandb"]).log_level, 5);
        assert_eq!(parse(&["--log-level", "010", "./wandb"]).log_level, 8);
        assert_eq!(parse(&["--log-level", "1_0", "./wandb"]).log_level, 10);

        assert_eq!(
            try_parse(&["--log-level", "abc", "./wandb"]).unwrap_err(),
            EXIT_CODE_ERROR_ARGS
        );
        assert_eq!(
            try_parse(&["--log-level", "_1", "./wandb"]).unwrap_err(),
            EXIT_CODE_ERROR_ARGS,
            "underscore must follow a digit"
        );
        assert_eq!(
            try_parse(&["--log-level", "99999999999999999999", "./wandb"]).unwrap_err(),
            EXIT_CODE_ERROR_ARGS,
            "value out of range"
        );
    }
}

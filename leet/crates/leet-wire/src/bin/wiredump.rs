//! Differential dump tool for the Go↔Rust record-stream diff.
//!
//! Prints one line per record of a .wandb file:
//!
//! ```text
//! REC <index> <record-oneof-case-name> <payload-len> <crc32c-hex>
//! ```
//!
//! followed by a final `OK <count>` on clean EOF, or `ERROR corrupt|eof` on
//! the first read failure (`eof` if the error may be resolved by waiting for
//! more data, i.e. Go's `io.ErrUnexpectedEOF`; `corrupt` otherwise).
//!
//! Output must be byte-identical to the Go oracle,
//! `core/internal/leet/fixturegen -dump <path>`. The digest is CRC-32C over
//! the raw record payload bytes as read from the log (no proto re-marshal),
//! so both sides hash identical bytes.

use std::process::ExitCode;

use leet_proto::wandb_internal;
use leet_proto::wandb_internal::record::RecordType;
use leet_wire::transaction_log;
use prost::Message as _;

fn main() -> ExitCode {
    let mut args = std::env::args().skip(1);
    let (Some(path), None) = (args.next(), args.next()) else {
        eprintln!("usage: wiredump <path-to-.wandb>");
        return ExitCode::from(2);
    };

    let mut reader = match transaction_log::open_reader(&path) {
        Ok(reader) => reader,
        Err(err) => {
            // Go: open errors are tool errors (stderr, exit 2), not part of
            // the diffed record stream.
            eprintln!("wiredump: {err}");
            return ExitCode::from(2);
        }
    };

    let mut count: u64 = 0;
    loop {
        let payload = match reader.read_raw() {
            Ok(payload) => payload,
            Err(err) if err.is_unexpected_eof() => {
                println!("ERROR eof");
                return ExitCode::SUCCESS;
            }
            Err(err) if err.is_eof() => {
                // Clean end of the record stream.
                println!("OK {count}");
                return ExitCode::SUCCESS;
            }
            Err(_) => {
                println!("ERROR corrupt");
                return ExitCode::SUCCESS;
            }
        };

        let Ok(msg) = wandb_internal::Record::decode(payload.as_slice()) else {
            // Go: transactionlog.Reader.Read wraps unmarshal errors with %v
            // (opaque, not EOF-like), so they classify as corrupt.
            println!("ERROR corrupt");
            return ExitCode::SUCCESS;
        };

        println!(
            "REC {count} {case} {len} {crc:08x}",
            case = record_case_name(&msg),
            len = payload.len(),
            crc = crc32c::crc32c(&payload),
        );
        count += 1;
    }
}

/// Returns the proto field name of the `record_type` oneof case ("history",
/// "run", "output_raw", ...), or "none" if no case is set.
///
/// Matches the Go oracle, which reads the field name off the protobuf
/// descriptor via reflection; prost has no descriptors, so the names are
/// spelled out (source of truth: `wandb/proto/wandb_internal.proto`).
fn record_case_name(msg: &wandb_internal::Record) -> &'static str {
    match msg.record_type {
        Some(RecordType::History(_)) => "history",
        Some(RecordType::Summary(_)) => "summary",
        Some(RecordType::Output(_)) => "output",
        Some(RecordType::Config(_)) => "config",
        Some(RecordType::Files(_)) => "files",
        Some(RecordType::Stats(_)) => "stats",
        Some(RecordType::Artifact(_)) => "artifact",
        Some(RecordType::Tbrecord(_)) => "tbrecord",
        Some(RecordType::Alert(_)) => "alert",
        Some(RecordType::Telemetry(_)) => "telemetry",
        Some(RecordType::Metric(_)) => "metric",
        Some(RecordType::OutputRaw(_)) => "output_raw",
        Some(RecordType::Run(_)) => "run",
        Some(RecordType::Exit(_)) => "exit",
        Some(RecordType::Final(_)) => "final",
        Some(RecordType::Header(_)) => "header",
        Some(RecordType::Footer(_)) => "footer",
        Some(RecordType::Preempting(_)) => "preempting",
        Some(RecordType::NoopLinkArtifact(())) => "noop_link_artifact",
        Some(RecordType::UseArtifact(_)) => "use_artifact",
        Some(RecordType::Environment(_)) => "environment",
        Some(RecordType::OutputLogger(_)) => "output_logger",
        Some(RecordType::Request(_)) => "request",
        None => "none",
    }
}

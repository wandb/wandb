//! `wandb-leet` — the W&B terminal UI, a mechanical Rust port of
//! `core/internal/leet` (Go, Bubble Tea v2). The Go implementation is the
//! behavioral spec; see `leet/docs/PORTING.md` and `leet/docs/PARITY.md`.

use clap::Parser;

/// CLI surface mirrors `wandb-core leet` flags (see `wandb/cli/leet.py`);
/// the flag set is a compatibility contract snapshotted in PARITY.md.
#[derive(Debug, Parser)]
#[command(name = "wandb-leet", version, about = "W&B terminal UI")]
struct Args {
    /// Directory containing wandb runs (the `wandb/` dir) or a single run dir.
    #[arg(value_name = "PATH")]
    path: Option<String>,

    /// Read a specific .wandb transaction log file.
    #[arg(long, value_name = "FILE")]
    run_file: Option<String>,

    /// Follow a run on the W&B backend instead of local files.
    #[arg(long, value_name = "URL")]
    remote_url: Option<String>,

    /// Standalone system monitor mode.
    #[arg(long)]
    symon: bool,

    /// Sampling interval for --symon, in seconds.
    #[arg(long, value_name = "SECONDS")]
    interval: Option<f64>,

    /// Open the configuration editor.
    #[arg(long)]
    config: bool,

    /// Disable error reporting / analytics.
    #[arg(long)]
    no_observability: bool,
}

fn main() -> anyhow::Result<()> {
    let _args = Args::parse();
    // Port pending: phases 1-7 fill this in (see leet/docs/PARITY.md).
    anyhow::bail!("wandb-leet: port in progress — use `wandb-core leet` meanwhile");
}

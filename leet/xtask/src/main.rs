//! Workspace chores: build the Go oracle, run the null test, record frozen
//! oracle snapshots. Invoke as `cargo xtask <command>` (alias in
//! .cargo/config.toml).

use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{Context, Result, bail};

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("oracle-build") => {
            oracle_build()?;
        }
        Some("null-test") => {
            let oracle = oracle_build()?;
            record(&oracle, &args[1..], true)?;
        }
        Some("record") => {
            let oracle = oracle_build()?;
            record(&oracle, &args[1..], false)?;
        }
        _ => {
            eprintln!("usage: cargo xtask <oracle-build|null-test|record> [--filter <s>] [--verbose]");
            std::process::exit(2);
        }
    }
    Ok(())
}

fn workspace_root() -> PathBuf {
    // xtask always runs from within the workspace via cargo.
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf()
}

/// Build wandb-core from the sibling core/ module — the pinned oracle.
/// The pin is the git checkout itself; docs/PARITY.md records the policy.
fn oracle_build() -> Result<PathBuf> {
    let root = workspace_root();
    let core_dir = root.parent().unwrap().join("core");
    if !core_dir.is_dir() {
        bail!("core/ not found next to leet/ (expected the wandb monorepo layout)");
    }
    let out = root.join("target/oracle/wandb-core");
    std::fs::create_dir_all(out.parent().unwrap())?;

    eprintln!("building oracle: go build ./cmd/wandb-core -> {}", out.display());
    let status = Command::new("go")
        .args(["build", "-o"])
        .arg(&out)
        .arg("./cmd/wandb-core")
        .current_dir(&core_dir)
        .status()
        .context("run go build (is Go installed?)")?;
    if !status.success() {
        bail!("go build failed");
    }
    Ok(out)
}

fn record(oracle: &Path, extra: &[String], null_test: bool) -> Result<()> {
    let root = workspace_root();
    let mut cmd = Command::new("cargo");
    cmd.current_dir(&root)
        .args(["run", "--quiet", "-p", "leet-harness", "--bin", "leet-record", "--"])
        .arg("--oracle")
        .arg(oracle)
        .arg("--scenarios")
        .arg(root.join("fixtures/scenarios"))
        .arg("--fixtures")
        .arg(root.join("fixtures/wandb"));
    if null_test {
        cmd.arg("--null-test");
    } else {
        cmd.arg("--out").arg(root.join("fixtures/expected"));
    }
    cmd.args(extra);
    let status = cmd.status().context("run leet-record")?;
    if !status.success() {
        bail!("leet-record failed");
    }
    Ok(())
}

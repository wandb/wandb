//! Oracle recorder + null test.
//!
//! ```text
//! # Record frozen oracle snapshots for all scenarios:
//! leet-record --oracle <wandb-core> --scenarios fixtures/scenarios \
//!             --fixtures fixtures/wandb --out fixtures/expected
//!
//! # Null test (Phase 0 gate): run every scenario twice, expect zero diff:
//! leet-record --oracle <wandb-core> --scenarios ... --fixtures ... --null-test
//! ```

use std::path::PathBuf;

use anyhow::{Context, Result, bail};
use clap::Parser;

use leet_harness::runner::{AppSpec, run_scenario};
use leet_harness::scenario::Scenario;
use leet_harness::{diff, snapshot};

#[derive(Debug, Parser)]
#[command(name = "leet-record")]
struct Args {
    /// Path to the oracle binary (wandb-core).
    #[arg(long)]
    oracle: PathBuf,

    /// Scenario file or directory of *.json scenarios.
    #[arg(long)]
    scenarios: PathBuf,

    /// Root of fixture trees (fixtures/wandb).
    #[arg(long)]
    fixtures: PathBuf,

    /// Output dir for frozen snapshots (fixtures/expected).
    #[arg(long)]
    out: Option<PathBuf>,

    /// Run each scenario twice and diff — proves determinism end to end.
    #[arg(long)]
    null_test: bool,

    /// Only run scenarios whose name contains this substring.
    #[arg(long)]
    filter: Option<String>,

    /// Print the persona query log after each run.
    #[arg(long)]
    verbose: bool,
}

fn main() -> Result<()> {
    let args = Args::parse();

    let mut scenario_files = Vec::new();
    if args.scenarios.is_file() {
        scenario_files.push(args.scenarios.clone());
    } else {
        for entry in std::fs::read_dir(&args.scenarios).context("read scenarios dir")? {
            let p = entry?.path();
            if p.extension().and_then(|e| e.to_str()) == Some("json") {
                scenario_files.push(p);
            }
        }
        scenario_files.sort();
    }
    if scenario_files.is_empty() {
        bail!("no scenarios found under {}", args.scenarios.display());
    }

    let app = AppSpec {
        program: args.oracle.clone(),
        base_args: vec!["leet".to_string()],
    };

    let mut failures = 0usize;
    for path in &scenario_files {
        let scenario = Scenario::load(path)?;
        if let Some(f) = &args.filter
            && !scenario.name.contains(f.as_str())
        {
            continue;
        }
        print!("{:<40}", scenario.name);

        if args.null_test {
            let run1 = run_scenario(&app, &scenario, &args.fixtures)
                .with_context(|| format!("{} run 1", scenario.name))?;
            let run2 = run_scenario(&app, &scenario, &args.fixtures)
                .with_context(|| format!("{} run 2", scenario.name))?;

            if run1.snapshots.len() != run2.snapshots.len() {
                println!("FAIL: snapshot count {} vs {}", run1.snapshots.len(), run2.snapshots.len());
                failures += 1;
                continue;
            }
            let mut scenario_clean = true;
            for ((name1, g1), (_, g2)) in run1.snapshots.iter().zip(&run2.snapshots) {
                let report = diff::diff_grids(g1, g2, &scenario.masks);
                if !report.clean_at(2) {
                    scenario_clean = false;
                    println!("\n--- {}::{} NOT deterministic:", scenario.name, name1);
                    print!("{}", diff::render_report(g1, g2, &report, "run1", "run2"));
                }
            }
            if scenario_clean {
                println!("OK ({} snaps, {} queries answered)", run1.snapshots.len(),
                    run1.persona_log.iter().filter(|q| q.reply.is_some()).count());
            } else {
                failures += 1;
            }
            if args.verbose {
                for q in &run1.persona_log {
                    println!("    query {} -> {:?}", q.query, q.reply);
                }
            }
        } else {
            let out_root = args.out.clone().context("--out required unless --null-test")?;
            let run = run_scenario(&app, &scenario, &args.fixtures)?;
            for (name, grid) in &run.snapshots {
                let path = out_root.join(&scenario.name).join(format!("{name}.frame"));
                snapshot::save(grid, &path)?;
            }
            println!("recorded {} snaps", run.snapshots.len());
            if args.verbose {
                for q in &run.persona_log {
                    println!("    query {} -> {:?}", q.query, q.reply);
                }
            }
        }
    }

    if failures > 0 {
        bail!("{failures} scenario(s) failed");
    }
    Ok(())
}

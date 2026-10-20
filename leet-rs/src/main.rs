//! `leet` binary entry point.

use std::path::Path;
use std::process::ExitCode;

use wandb_leet::app::App;
use wandb_leet::store::live::{is_run_dir_name, wandb_file_in_run_dir};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();

    let target = match args.first().map(String::as_str) {
        Some("-h") | Some("--help") => {
            print_usage();
            return ExitCode::SUCCESS;
        }
        Some(path) => resolve_target(Path::new(path)),
        None => Some(Target {
            wandb_dir: "wandb".to_string(),
            run_file: None,
        }),
    };

    let Some(target) = target else {
        eprintln!("leet: no wandb directory or .wandb run file found");
        print_usage();
        return ExitCode::FAILURE;
    };

    let mut app = App::new(target.wandb_dir, target.run_file);
    match app.run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            eprintln!("leet: {err}");
            ExitCode::FAILURE
        }
    }
}

fn print_usage() {
    eprintln!("usage: leet [PATH]");
    eprintln!();
    eprintln!("PATH may be a wandb/ directory (opens the workspace), a run");
    eprintln!("directory, or a .wandb file (opens the single-run view).");
    eprintln!("Without arguments, the workspace opens on ./wandb.");
}

struct Target {
    wandb_dir: String,
    run_file: Option<String>,
}

/// Resolves a user-supplied path to a wandb dir and an optional run file.
fn resolve_target(path: &Path) -> Option<Target> {
    let dir_string = |p: Option<&Path>| {
        p.filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."))
            .to_string_lossy()
            .into_owned()
    };

    // A .wandb file: single-run view; wandb dir is two levels up.
    if path.is_file() {
        return Some(Target {
            wandb_dir: dir_string(path.parent().and_then(Path::parent)),
            run_file: Some(path.to_string_lossy().into_owned()),
        });
    }

    if path.is_dir() {
        // A run directory: single-run view on its .wandb file.
        let is_run_dir = path
            .file_name()
            .and_then(|n| n.to_str())
            .is_some_and(is_run_dir_name);
        if is_run_dir && let Some(file) = wandb_file_in_run_dir(path) {
            return Some(Target {
                wandb_dir: dir_string(path.parent()),
                run_file: Some(file.to_string_lossy().into_owned()),
            });
        }
        // A wandb directory: workspace view.
        return Some(Target {
            wandb_dir: path.to_string_lossy().into_owned(),
            run_file: None,
        });
    }

    None
}

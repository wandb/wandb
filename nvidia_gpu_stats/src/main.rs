use clap::Parser;
use nix::unistd::getppid;
use sentry::types::Dsn;
use signal_hook::{consts::TERM_SIGNALS, iterator::Signals};
use std::env;
use std::io;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

mod gpu_nvidia;
mod metrics;

use crate::gpu_nvidia::NvidiaGpu;
use crate::metrics::Metrics;

// Define command-line arguments
#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// Monitor this process ID and its children for GPU usage
    #[arg(short, long, default_value_t = 0)]
    pid: i32,

    /// Parent process ID. The program will exit if the parent process is no longer alive.
    #[arg(short, long, default_value_t = 0)]
    ppid: i32,

    /// Sampling interval in seconds
    #[arg(short, long, default_value_t = 1.0)]
    interval: f64,
}

fn parse_bool(s: &str) -> bool {
    match s.to_lowercase().as_str() {
        "true" | "1" => true,
        "false" | "0" => false,
        _ => true,
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Parse command-line arguments
    let args = Args::parse();

    let error_reporting_enabled = env::var("WANDB_ERROR_REPORTING")
        .map(|v| parse_bool(&v))
        .unwrap_or(true);

    let dsn: Option<Dsn> = if error_reporting_enabled {
        "https://9e9d0694aa7ccd41aeb5bc34aadd716a@o151352.ingest.us.sentry.io/4506068829470720"
            .parse()
            .ok()
    } else {
        None
    };

    let _guard = sentry::init(sentry::ClientOptions {
        dsn,
        release: sentry::release_name!(),
        ..Default::default()
    });

    // Initialize NVIDIA GPU
    let nvidia_gpu = NvidiaGpu::new().map_err(|e| {
        // this typically means that the NVIDIA driver is not installed /
        // libnvidia-ml.so is not found / no NVIDIA GPU is present
        e
    })?;

    // Set up a flag to control the main sampling loop
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();

    // Set up signal handler for graceful shutdown
    let mut signals = Signals::new(TERM_SIGNALS)?;
    thread::spawn(move || {
        for _sig in signals.forever() {
            r.store(false, Ordering::Relaxed);
            break;
        }
    });

    // Main sampling loop. Will run until the parent process is no longer alive or a signal is received.
    while running.load(Ordering::Relaxed) {
        let sampling_start = Instant::now();
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();

        // Sample GPU metrics
        let mut metrics = Metrics::new();
        if let Err(e) = nvidia_gpu.sample_metrics(&mut metrics, args.pid) {
            sentry::capture_error(&e);
        }

        // Add timestamp to metrics
        metrics.add_timestamp(timestamp);

        // Convert metrics to JSON and print to stdout for collection
        if let Err(e) = metrics.print_json() {
            if e.kind() == io::ErrorKind::BrokenPipe {
                break;
            } else {
                sentry::capture_error(&e);
            }
        }

        // Check if parent process is still alive and break loop if not
        if getppid() != nix::unistd::Pid::from_raw(args.ppid) {
            break;
        }

        // Sleep to maintain requested sampling interval
        let loop_duration = sampling_start.elapsed();
        let sleep_duration = Duration::from_secs_f64(args.interval);
        if loop_duration < sleep_duration {
            thread::sleep(sleep_duration - loop_duration);
        }
    }

    // Graceful shutdown of NVML
    if let Err(e) = nvidia_gpu.shutdown() {
        sentry::capture_error(&e);
        eprintln!("Error shutting down NVML: {}", e);
    }

    Ok(())
}

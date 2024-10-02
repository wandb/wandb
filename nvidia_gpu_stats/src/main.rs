use clap::Parser;
use sentry::types::Dsn;
use std::collections::HashSet;
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

/// Listen for signals to gracefully shutdown the program
#[cfg(target_os = "linux")]
fn setup_signal_handler(running: Arc<AtomicBool>) -> Result<(), Box<dyn std::error::Error>> {
    use signal_hook::{consts::TERM_SIGNALS, iterator::Signals};
    let mut signals = Signals::new(TERM_SIGNALS)?;
    thread::spawn(move || {
        for _sig in signals.forever() {
            running.store(false, Ordering::Relaxed);
            break;
        }
    });
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn setup_signal_handler(_running: Arc<AtomicBool>) -> Result<(), Box<dyn std::error::Error>> {
    // Windows doesn't support the same signal handling as Unix, so we can't
    // gracefully shutdown the program. Instead, we rely on the parent process
    // to kill the program when it's done.
    Ok(())
}

/// Check if the parent process is still alive
#[cfg(target_os = "linux")]
fn is_parent_alive(ppid: i32) -> bool {
    use nix::unistd::getppid;
    getppid() == nix::unistd::Pid::from_raw(ppid)
}

#[cfg(not(target_os = "linux"))]
fn is_parent_alive(_ppid: i32) -> bool {
    // TODO: Implement for other platforms
    true
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
    let mut nvidia_gpu = NvidiaGpu::new().map_err(|e| {
        // this typically means that the NVIDIA driver is not installed /
        // libnvidia-ml.so is not found / no NVIDIA GPU is present
        e
    })?;

    // Set up a flag to control the main sampling loop
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();

    // Set up signal handler for graceful shutdown
    setup_signal_handler(r)?;

    // Error cache to minimize duplicate error messages sent to Sentry
    let mut error_cache: HashSet<String> = HashSet::new();

    // Main sampling loop. Will run until the parent process is no longer alive or a signal is received.
    while running.load(Ordering::Relaxed) {
        let sampling_start = Instant::now();

        // Check if parent process is still alive and break loop if not
        if !is_parent_alive(args.ppid) {
            break;
        }

        let mut metrics = Metrics::new();

        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();

        // Sample Nvidia GPU metrics
        if let Err(e) = nvidia_gpu.sample_metrics(&mut metrics, args.pid) {
            let error_message = e.to_string();
            if !error_cache.contains(&error_message) {
                error_cache.insert(error_message);
                sentry::capture_error(&e);
            }
        }

        // Add timestamp to metrics
        metrics.add_timestamp(timestamp);

        // Convert metrics to JSON and print to stdout for collection
        if let Err(e) = metrics.print_json() {
            if e.kind() == io::ErrorKind::BrokenPipe {
                break;
            } else {
                let error_message = e.to_string();
                if !error_cache.contains(&error_message) {
                    error_cache.insert(error_message);
                    sentry::capture_error(&e);
                }
            }
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
    }

    Ok(())
}

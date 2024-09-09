use clap::Parser;
use sentry::types::Dsn;
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
#[cfg(unix)]
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

#[cfg(windows)]
fn setup_signal_handler(_running: Arc<AtomicBool>) -> Result<(), Box<dyn std::error::Error>> {
    // Windows doesn't support the same signal handling as Unix, so we can't
    // gracefully shutdown the program. Instead, we rely on the parent process
    // to kill the program when it's done.
    Ok(())
}

/// Check if the parent process is still alive
#[cfg(unix)]
fn is_parent_alive(ppid: i32) -> bool {
    use nix::unistd::getppid;
    getppid() == nix::unistd::Pid::from_raw(ppid)
}

#[cfg(windows)]
fn is_parent_alive(ppid: i32) -> bool {
    // This function checks if the parent process is still alive by enumerating
    // all processes and checking if the parent process ID matches the given
    // parent process ID. This is a workaround for the lack of signal handling
    // on Windows.
    use winapi::um::handleapi::CloseHandle;
    use winapi::um::processthreadsapi::GetCurrentProcessId;
    use winapi::um::tlhelp32::{
        CreateToolhelp32Snapshot, Process32First, Process32Next, PROCESSENTRY32, TH32CS_SNAPPROCESS,
    };
    use winapi::um::winnt::HANDLE;

    unsafe {
        let snapshot: HANDLE = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if snapshot == winapi::um::handleapi::INVALID_HANDLE_VALUE {
            return false;
        }

        let mut pe32: PROCESSENTRY32 = std::mem::zeroed();
        pe32.dwSize = std::mem::size_of::<PROCESSENTRY32>() as u32;

        if Process32First(snapshot, &mut pe32) != 0 {
            loop {
                if pe32.th32ProcessID == GetCurrentProcessId() as u32
                    && pe32.th32ParentProcessID == ppid as u32
                {
                    CloseHandle(snapshot);
                    return true;
                }
                if Process32Next(snapshot, &mut pe32) == 0 {
                    break;
                }
            }
        }

        CloseHandle(snapshot);
    }
    false
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
    setup_signal_handler(r)?;

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
        if !is_parent_alive(args.ppid) {
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

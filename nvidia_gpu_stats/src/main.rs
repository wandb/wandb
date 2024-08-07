//! NVIDIA GPU Metrics Monitor
//!
//! This program continuosly collects and prints to stdout GPU metrics using NVML.

use clap::Parser;
use nix::unistd::getppid;
use nvml_wrapper::enum_wrappers::device::{Clock, TemperatureSensor};
use nvml_wrapper::error::NvmlError;
use nvml_wrapper::{Device, Nvml};
use serde::Serialize;
use serde_json::json;
use signal_hook::{consts::TERM_SIGNALS, iterator::Signals};
use std::collections::BTreeMap;
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

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

/// Struct to hold GPU metrics. Metrics are stored in a BTreeMap to ensure
/// consistent ordering of keys in the output JSON.
/// The output map is flat to make it easier to parse in downstream applications.
/// cuda_version: The version of CUDA installed on the system.
/// gpu.count: The total number of GPUs detected in the system.
/// gpu.{i}.name: The name of the GPU at index i (e.g., Tesla T4).
/// gpu.{i}.brand: The brand of the GPU at index i (e.g., GeForce, Nvidia).
/// gpu.{i}.fanSpeed: The current fan speed of the GPU at index i (in percentage).
/// gpu.{i}.encoderUtilization: The utilization of the GPU's encoder at index i (in percentage).
/// gpu.{i}.gpu: The overall GPU utilization at index i (in percentage).
/// gpu.{i}.memory: The GPU memory utilization at index i (in percentage).
/// gpu.{i}.memoryTotal: The total memory of the GPU at index i (in bytes).
/// gpu.{i}.memoryAllocated: The percentage of GPU memory allocated at index i.
/// gpu.{i}.memoryAllocatedBytes: The amount of GPU memory allocated at index i (in bytes).
/// gpu.{i}.temp: The temperature of the GPU at index i (in Celsius).
/// gpu.{i}.powerWatts: The power consumption of the GPU at index i (in Watts).
/// gpu.{i}.enforcedPowerLimitWatts: The enforced power limit of the GPU at index i (in Watts).
/// gpu.{i}.powerPercent: The percentage of power limit being used by the GPU at index i.
/// gpu.{i}.graphicsClock: The current graphics clock speed of the GPU at index i (in MHz).
/// gpu.{i}.memoryClock: The current memory clock speed of the GPU at index i (in MHz).
/// gpu.{i}.pcieLinkGen: The current PCIe link generation of the GPU at index i.
/// gpu.{i}.pcieLinkSpeed: The current PCIe link speed of the GPU at index i (in bits per second).
/// gpu.{i}.pcieLinkWidth: The current PCIe link width of the GPU at index i.
/// gpu.{i}.maxPcieLinkGen: The maximum PCIe link generation supported by the GPU at index i.
/// gpu.{i}.maxPcieLinkWidth: The maximum PCIe link width supported by the GPU at index i.
/// gpu.{i}.cudaCores: The number of CUDA cores in the GPU at index i.
/// gpu.{i}.architecture: The architecture of the GPU at index i (e.g., Ampere, Turing).
/// gpu.process.{i}.*: Various metrics specific to the monitored process
///    (if the GPU is in use by the process). These include GPU utilization, memory utilization,
///     temperature, and power consumption.
/// _timestamp: The Unix timestamp when the metrics were collected.
///
/// Note that {i} represents the index of each GPU in the system, starting from 0.
#[derive(Serialize)]
struct GpuMetrics {
    #[serde(flatten)]
    metrics: BTreeMap<String, serde_json::Value>,
}

/// Function to get child process IDs for a given parent PID
fn get_child_pids(pid: i32) -> Vec<i32> {
    let output = Command::new("pgrep")
        .args(&["-P", &pid.to_string()])
        .output()
        .expect("Failed to execute pgrep");

    String::from_utf8_lossy(&output.stdout)
        .split_whitespace()
        .filter_map(|s| s.parse().ok())
        .collect()
}

/// Function to check if a GPU is being used by a specific process or its children
fn gpu_in_use_by_process(device: &Device, pid: i32) -> bool {
    let our_pids: Vec<i32> = std::iter::once(pid).chain(get_child_pids(pid)).collect();

    let compute_processes = device.running_compute_processes().unwrap_or_default();
    let graphics_processes = device.running_graphics_processes().unwrap_or_default();

    let device_pids: Vec<i32> = compute_processes
        .iter()
        .chain(graphics_processes.iter())
        .map(|p| p.pid as i32)
        .collect();

    our_pids.iter().any(|&p| device_pids.contains(&p))
}

/// Fallback function to return minimal metrics when NVML fails/is not available
fn sample_metrics_fallback() -> GpuMetrics {
    let mut metrics = BTreeMap::new();
    metrics.insert("gpu.count".to_string(), json!(0));
    GpuMetrics { metrics }
}

/// Samples GPU metrics using NVML.
///
/// This function collects various metrics from all available GPUs, including
/// utilization, memory usage, temperature, and power consumption. It also
/// checks if the specified process is using each GPU and collects process-specific
/// metrics if applicable.
///
/// # Arguments
///
/// * `nvml` - A reference to the initialized NVML instance.
/// * `pid` - The process ID to monitor for GPU usage.
/// * `cuda_version` - A string representing the CUDA version.
///
/// # Returns
///
/// Returns a `Result` containing `GpuMetrics` if successful, or an `NvmlError` if
/// an error occurred while sampling metrics.
///
/// # Errors
///
/// This function will return an error if:
/// * NVML fails to retrieve device information
/// * Any of the metric collection operations fail
///
/// # Examples
///
/// ```
/// let nvml = Nvml::init().unwrap();
/// let pid = 1234;
/// let cuda_version = "11.2".to_string();
/// let metrics = sample_metrics(&nvml, pid, cuda_version).unwrap();
/// println!("GPU Count: {}", metrics.metrics["gpu.count"]);
/// ```
fn sample_metrics(nvml: &Nvml, pid: i32, cuda_version: String) -> Result<GpuMetrics, NvmlError> {
    let mut metrics = BTreeMap::new();

    metrics.insert("cuda_version".to_string(), json!(cuda_version));

    let device_count = nvml.device_count()?;
    metrics.insert("gpu.count".to_string(), json!(device_count));

    for di in 0..device_count {
        let device = nvml.device_by_index(di)?;
        let gpu_in_use = gpu_in_use_by_process(&device, pid);

        let name = device.name()?;
        metrics.insert(format!("gpu.{}.name", di), json!(name));

        let brand = device.brand()?;
        metrics.insert(format!("gpu.{}.brand", di), json!(format!("{:?}", brand)));

        if let Ok(fan_speed) = device.fan_speed(0) {
            metrics.insert(format!("gpu.{}.fanSpeed", di), json!(fan_speed));
        }

        if let Ok(encoder_util) = device.encoder_utilization() {
            metrics.insert(
                format!("gpu.{}.encoderUtilization", di),
                json!(encoder_util.utilization),
            );
        }

        let utilization = device.utilization_rates()?;
        metrics.insert(format!("gpu.{}.gpu", di), json!(utilization.gpu));
        metrics.insert(format!("gpu.{}.memory", di), json!(utilization.memory));

        if gpu_in_use {
            metrics.insert(format!("gpu.process.{}.gpu", di), json!(utilization.gpu));
            metrics.insert(
                format!("gpu.process.{}.memory", di),
                json!(utilization.memory),
            );
        }

        let memory_info = device.memory_info()?;
        metrics.insert(format!("gpu.{}.memoryTotal", di), json!(memory_info.total));
        let memory_allocated = (memory_info.used as f64 / memory_info.total as f64) * 100.0;
        metrics.insert(
            format!("gpu.{}.memoryAllocated", di),
            json!(memory_allocated),
        );
        metrics.insert(
            format!("gpu.{}.memoryAllocatedBytes", di),
            json!(memory_info.used),
        );

        if gpu_in_use {
            metrics.insert(
                format!("gpu.process.{}.memoryAllocated", di),
                json!(memory_allocated),
            );
            metrics.insert(
                format!("gpu.process.{}.memoryAllocatedBytes", di),
                json!(memory_info.used),
            );
        }

        let temperature = device.temperature(TemperatureSensor::Gpu)?;
        metrics.insert(format!("gpu.{}.temp", di), json!(temperature));
        if gpu_in_use {
            metrics.insert(format!("gpu.process.{}.temp", di), json!(temperature));
        }

        let power_usage = device.power_usage()? as f64 / 1000.0;
        metrics.insert(format!("gpu.{}.powerWatts", di), json!(power_usage));
        if gpu_in_use {
            metrics.insert(format!("gpu.process.{}.powerWatts", di), json!(power_usage));
        }

        if let Ok(power_limit) = device.enforced_power_limit() {
            let power_limit = power_limit as f64 / 1000.0;
            metrics.insert(
                format!("gpu.{}.enforcedPowerLimitWatts", di),
                json!(power_limit),
            );
            let power_percent = (power_usage / power_limit) * 100.0;
            metrics.insert(format!("gpu.{}.powerPercent", di), json!(power_percent));

            if gpu_in_use {
                metrics.insert(
                    format!("gpu.process.{}.enforcedPowerLimitWatts", di),
                    json!(power_limit),
                );
                metrics.insert(
                    format!("gpu.process.{}.powerPercent", di),
                    json!(power_percent),
                );
            }
        }

        let graphics_clock = device.clock_info(Clock::Graphics)?;
        metrics.insert(format!("gpu.{}.graphicsClock", di), json!(graphics_clock));

        let mem_clock = device.clock_info(Clock::Memory)?;
        metrics.insert(format!("gpu.{}.memoryClock", di), json!(mem_clock));

        let link_gen = device.current_pcie_link_gen()?;
        metrics.insert(format!("gpu.{}.pcieLinkGen", di), json!(link_gen));

        if let Ok(link_speed) = device.pcie_link_speed().map(u64::from).map(|x| x * 1000000) {
            metrics.insert(format!("gpu.{}.pcieLinkSpeed", di), json!(link_speed));
        }

        let link_width = device.current_pcie_link_width()?;
        metrics.insert(format!("gpu.{}.pcieLinkWidth", di), json!(link_width));

        let max_link_gen = device.max_pcie_link_gen()?;
        metrics.insert(format!("gpu.{}.maxPcieLinkGen", di), json!(max_link_gen));

        let max_link_width = device.max_pcie_link_width()?;
        metrics.insert(
            format!("gpu.{}.maxPcieLinkWidth", di),
            json!(max_link_width),
        );

        let cuda_cores = device.num_cores()?;
        metrics.insert(format!("gpu.{}.cudaCores", di), json!(cuda_cores));

        let architecture = device.architecture()?;
        metrics.insert(
            format!("gpu.{}.architecture", di),
            json!(format!("{:?}", architecture)),
        );
    }

    Ok(GpuMetrics { metrics })
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Parse command-line arguments
    let args = Args::parse();

    // Initialize NVML
    let nvml_result = nvml_wrapper::Nvml::init();

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
            .unwrap()
            .as_secs_f64();

        // Sample GPU metrics
        let mut gpu_metrics = match &nvml_result {
            Ok(nvml) => match nvml.sys_cuda_driver_version() {
                Ok(cuda_version) => {
                    let cuda_version = format!(
                        "{}.{}",
                        nvml_wrapper::cuda_driver_version_major(cuda_version),
                        nvml_wrapper::cuda_driver_version_minor(cuda_version)
                    );
                    match sample_metrics(nvml, args.pid, cuda_version) {
                        Ok(metrics) => metrics,
                        Err(_) => sample_metrics_fallback(),
                    }
                }
                Err(_) => sample_metrics_fallback(),
            },
            Err(_) => sample_metrics_fallback(),
        };

        // Add timestamp to metrics
        gpu_metrics
            .metrics
            .insert("_timestamp".to_string(), json!(timestamp));

        // Convert metrics to JSON and print to stdout for collection
        let json_output = serde_json::to_string(&gpu_metrics.metrics).unwrap();
        println!("{}", json_output);

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
    nvml_result.ok().map(|nvml| nvml.shutdown());

    Ok(())
}

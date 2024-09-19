use crate::metrics::Metrics;
use nvml_wrapper::enum_wrappers::device::{Clock, TemperatureSensor};
use nvml_wrapper::error::NvmlError;
use nvml_wrapper::{Device, Nvml};
use std::fs::read_to_string;

/// Static information about a GPU.
#[derive(Default)]
struct GpuStaticInfo {
    name: String,
    brand: String,
    cuda_cores: u32,
    architecture: String,
}

/// Tracks the availability of GPU metrics for the current system.
#[derive(Clone)]
struct GpuMetricAvailability {
    utilization: bool,
    memory_info: bool,
    temperature: bool,
    power_usage: bool,
    enforced_power_limit: bool,
    sm_clock: bool,
    mem_clock: bool,
    graphics_clock: bool,
    corrected_memory_errors: bool,
    uncorrected_memory_errors: bool,
    fan_speed: bool,
    encoder_utilization: bool,
    link_gen: bool,
    link_speed: bool,
    link_width: bool,
    max_link_gen: bool,
    max_link_width: bool,
}

impl Default for GpuMetricAvailability {
    fn default() -> Self {
        Self {
            utilization: true,
            memory_info: true,
            temperature: true,
            power_usage: true,
            enforced_power_limit: true,
            sm_clock: true,
            mem_clock: true,
            graphics_clock: false, // TODO: questionable utility, expensive to retrieve
            corrected_memory_errors: true,
            uncorrected_memory_errors: true,
            fan_speed: true,
            encoder_utilization: false, // TODO: questionable utility, expensive to retrieve
            link_gen: true,
            link_speed: true,
            link_width: true,
            max_link_gen: true,
            max_link_width: true,
        }
    }
}

pub struct NvidiaGpu {
    nvml: Nvml,
    cuda_version: String,
    device_count: u32,
    gpu_static_info: Vec<GpuStaticInfo>,
    gpu_metric_availability: Vec<GpuMetricAvailability>,
}

impl NvidiaGpu {
    pub fn new() -> Result<Self, NvmlError> {
        // Nvml::init() attempts to load libnvidia-ml.so which is usually a symlink
        // to libnvidia-ml.so.1 and not available in certain environments.
        // We follow go-nvml example and attempt to load libnvidia-ml.so.1 directly, see:
        // https://github.com/NVIDIA/go-nvml/blob/0e815c71ca6e8184387d8b502b2ef2d2722165b9/pkg/nvml/lib.go#L30
        let nvml = Nvml::builder()
            .lib_path("libnvidia-ml.so.1".as_ref())
            .init()?;
        let cuda_version = nvml.sys_cuda_driver_version()?;
        format!(
            "{}.{}",
            nvml_wrapper::cuda_driver_version_major(cuda_version),
            nvml_wrapper::cuda_driver_version_minor(cuda_version)
        );
        let device_count = nvml.device_count()?;

        // Collect static information about each GPU
        let mut gpu_static_info = Vec::new();
        for di in 0..device_count {
            let device = nvml.device_by_index(di)?;

            let mut static_info = GpuStaticInfo::default();

            if let Ok(name) = device.name() {
                static_info.name = name;
            }
            if let Ok(brand) = device.brand() {
                static_info.brand = format!("{:?}", brand);
            }
            if let Ok(cuda_cores) = device.num_cores() {
                static_info.cuda_cores = cuda_cores;
            }
            if let Ok(architecture) = device.architecture() {
                static_info.architecture = format!("{:?}", architecture);
            }

            gpu_static_info.push(static_info);
        }

        // Initialize metric availability with default (all true)
        let gpu_metric_availability = vec![GpuMetricAvailability::default(); device_count as usize];

        Ok(NvidiaGpu {
            nvml,
            cuda_version: format!(
                "{}.{}",
                nvml_wrapper::cuda_driver_version_major(cuda_version),
                nvml_wrapper::cuda_driver_version_minor(cuda_version)
            ),
            device_count,
            gpu_static_info,
            gpu_metric_availability,
        })
    }

    /// Check if a GPU is being used by a specific process or its children.
    fn gpu_in_use_by_process(&self, device: &Device, pid: i32) -> bool {
        let mut our_pids = vec![pid];
        if let Ok(child_pids) = self.get_child_pids(pid) {
            our_pids.extend(child_pids);
        }

        let compute_processes = device.running_compute_processes().unwrap_or_default();
        let graphics_processes = device.running_graphics_processes().unwrap_or_default();

        let device_pids: Vec<i32> = compute_processes
            .iter()
            .chain(graphics_processes.iter())
            .map(|p| p.pid as i32)
            .collect();

        our_pids.iter().any(|&p| device_pids.contains(&p))
    }

    /// Get child process IDs for a given parent PID.
    fn get_child_pids(&self, parent_pid: i32) -> Result<Vec<i32>, std::io::Error> {
        let mut descendant_pids = Vec::new();
        let mut stack = vec![parent_pid];

        while let Some(pid) = stack.pop() {
            let children_path = format!("/proc/{}/task/{}/children", pid, pid);
            if let Ok(contents) = read_to_string(&children_path) {
                let child_pids: Vec<i32> = contents
                    .split_whitespace()
                    .filter_map(|s| s.parse::<i32>().ok())
                    .collect();
                stack.extend(&child_pids);
                descendant_pids.extend(child_pids);
            }
        }

        Ok(descendant_pids)
    }

    /// Samples GPU metrics using NVML.
    ///
    /// This function collects various metrics from all available GPUs, including
    /// utilization, memory usage, temperature, and power consumption. It also
    /// checks if the specified process is using each GPU and collects process-specific
    /// metrics if applicable.
    ///
    /// Metrics captured include:
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
    ///
    /// # Arguments
    ///
    /// * `metrics` - A mutable reference to a `Metrics` struct to store the collected metrics.
    /// * `pid` - The process ID to monitor for GPU usage.
    ///
    /// # Returns
    ///
    /// Returns a `Result` with an empty tuple on success or an `NvmlError` on failure.
    /// The collected metrics are stored in the `Metrics` struct provided as an argument.
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
    /// use crate::gpu_nvidia::NvidiaGpu;
    /// use crate::metrics::Metrics;
    /// let nvidia_gpu = NvidiaGpu::new().unwrap();
    /// let mut metrics = Metrics::new();
    /// nvidia_gpu.sample_metrics(&mut metrics, 1234).unwrap();
    /// ```
    pub fn sample_metrics(&mut self, metrics: &mut Metrics, pid: i32) -> Result<(), NvmlError> {
        metrics.add_metric("cuda_version", &*self.cuda_version);
        metrics.add_metric("_gpu.count", self.device_count);

        for di in 0..self.device_count {
            let device = match self.nvml.device_by_index(di) {
                Ok(device) => device,
                Err(_e) => {
                    continue;
                }
            };

            // Populate static information about the GPU
            metrics.add_metric(
                &format!("gpu.{}.name", di),
                self.gpu_static_info[di as usize].name.as_str(),
            );
            metrics.add_metric(
                &format!("_gpu.{}.brand", di),
                self.gpu_static_info[di as usize].brand.as_str(),
            );
            metrics.add_metric(
                &format!("_gpu.{}.cudaCores", di),
                self.gpu_static_info[di as usize].cuda_cores,
            );
            metrics.add_metric(
                &format!("_gpu.{}.architecture", di),
                self.gpu_static_info[di as usize].architecture.as_str(),
            );

            // Collect dynamic metrics for the GPU if pid != 0
            let gpu_in_use = match pid {
                0 => false,
                _ => self.gpu_in_use_by_process(&device, pid),
            };

            let availability = &mut self.gpu_metric_availability[di as usize];

            // Utilization
            if availability.utilization {
                match device.utilization_rates() {
                    Ok(utilization) => {
                        metrics.add_metric(&format!("gpu.{}.gpu", di), utilization.gpu);
                        metrics.add_metric(&format!("gpu.{}.memory", di), utilization.memory);

                        if gpu_in_use {
                            metrics.add_metric(&format!("gpu.process.{}.gpu", di), utilization.gpu);
                            metrics.add_metric(
                                &format!("gpu.process.{}.memory", di),
                                utilization.memory,
                            );
                        }
                    }
                    Err(_) => {
                        availability.utilization = false;
                    }
                }
            }

            // Memory Info
            if availability.memory_info {
                match device.memory_info() {
                    Ok(memory_info) => {
                        metrics.add_metric(&format!("_gpu.{}.memoryTotal", di), memory_info.total);
                        let memory_allocated =
                            (memory_info.used as f64 / memory_info.total as f64) * 100.0;
                        metrics
                            .add_metric(&format!("gpu.{}.memoryAllocated", di), memory_allocated);
                        metrics.add_metric(
                            &format!("gpu.{}.memoryAllocatedBytes", di),
                            memory_info.used,
                        );

                        if gpu_in_use {
                            metrics.add_metric(
                                &format!("gpu.process.{}.memoryAllocated", di),
                                memory_allocated,
                            );
                            metrics.add_metric(
                                &format!("gpu.process.{}.memoryAllocatedBytes", di),
                                memory_info.used,
                            );
                        }
                    }
                    Err(_) => {
                        availability.memory_info = false;
                    }
                }
            }

            // Temperature
            if availability.temperature {
                match device.temperature(TemperatureSensor::Gpu) {
                    Ok(temperature) => {
                        metrics.add_metric(&format!("gpu.{}.temp", di), temperature);
                        if gpu_in_use {
                            metrics.add_metric(&format!("gpu.process.{}.temp", di), temperature);
                        }
                    }
                    Err(_) => {
                        availability.temperature = false;
                    }
                }
            }

            // Power Usage and Enforced Power Limit
            if availability.power_usage {
                match device.power_usage() {
                    Ok(power_usage) => {
                        let power_usage = power_usage as f64 / 1000.0;
                        metrics.add_metric(&format!("gpu.{}.powerWatts", di), power_usage);
                        if gpu_in_use {
                            metrics
                                .add_metric(&format!("gpu.process.{}.powerWatts", di), power_usage);
                        }

                        if availability.enforced_power_limit {
                            match device.enforced_power_limit() {
                                Ok(power_limit) => {
                                    let power_limit = power_limit as f64 / 1000.0;
                                    metrics.add_metric(
                                        &format!("gpu.{}.enforcedPowerLimitWatts", di),
                                        power_limit,
                                    );
                                    let power_percent = (power_usage / power_limit) * 100.0;
                                    metrics.add_metric(
                                        &format!("gpu.{}.powerPercent", di),
                                        power_percent,
                                    );

                                    if gpu_in_use {
                                        metrics.add_metric(
                                            &format!("gpu.process.{}.enforcedPowerLimitWatts", di),
                                            power_limit,
                                        );
                                        metrics.add_metric(
                                            &format!("gpu.process.{}.powerPercent", di),
                                            power_percent,
                                        );
                                    }
                                }
                                Err(_) => {
                                    availability.enforced_power_limit = false;
                                }
                            }
                        }
                    }
                    Err(_) => {
                        availability.power_usage = false;
                    }
                }
            }

            // SM Clock
            if availability.sm_clock {
                match device.clock_info(Clock::SM) {
                    Ok(sm_clock) => {
                        metrics.add_metric(&format!("gpu.{}.smClock", di), sm_clock);
                    }
                    Err(_) => {
                        availability.sm_clock = false;
                    }
                }
            }

            // Memory Clock
            if availability.mem_clock {
                match device.clock_info(Clock::Memory) {
                    Ok(mem_clock) => {
                        metrics.add_metric(&format!("gpu.{}.memoryClock", di), mem_clock);
                    }
                    Err(_) => {
                        availability.mem_clock = false;
                    }
                }
            }

            // Graphics Clock
            if availability.graphics_clock {
                match device.clock_info(Clock::Graphics) {
                    Ok(graphics_clock) => {
                        metrics.add_metric(&format!("gpu.{}.graphicsClock", di), graphics_clock);
                    }
                    Err(_) => {
                        availability.graphics_clock = false;
                    }
                }
            }

            // Corrected Memory Errors
            if availability.corrected_memory_errors {
                match device.memory_error_counter(
                    nvml_wrapper::enum_wrappers::device::MemoryError::Corrected,
                    nvml_wrapper::enum_wrappers::device::EccCounter::Aggregate,
                    nvml_wrapper::enum_wrappers::device::MemoryLocation::Device,
                ) {
                    Ok(errors) => {
                        metrics.add_metric(&format!("gpu.{}.correctedMemoryErrors", di), errors);
                    }
                    Err(_) => {
                        availability.corrected_memory_errors = false;
                    }
                }
            }

            // Uncorrected Memory Errors
            if availability.uncorrected_memory_errors {
                match device.memory_error_counter(
                    nvml_wrapper::enum_wrappers::device::MemoryError::Uncorrected,
                    nvml_wrapper::enum_wrappers::device::EccCounter::Aggregate,
                    nvml_wrapper::enum_wrappers::device::MemoryLocation::Device,
                ) {
                    Ok(errors) => {
                        metrics.add_metric(&format!("gpu.{}.uncorrectedMemoryErrors", di), errors);
                    }
                    Err(_) => {
                        availability.uncorrected_memory_errors = false;
                    }
                }
            }

            // Fan Speed
            if availability.fan_speed {
                match device.fan_speed(0) {
                    Ok(fan_speed) => {
                        metrics.add_metric(&format!("gpu.{}.fanSpeed", di), fan_speed);
                    }
                    Err(_) => {
                        availability.fan_speed = false;
                    }
                }
            }

            // Encoder Utilization
            if availability.encoder_utilization {
                match device.encoder_utilization() {
                    Ok(encoder_util) => {
                        metrics.add_metric(
                            &format!("gpu.{}.encoderUtilization", di),
                            encoder_util.utilization,
                        );
                    }
                    Err(_) => {
                        availability.encoder_utilization = false;
                    }
                }
            }

            // PCIe Link Generation
            if availability.link_gen {
                match device.current_pcie_link_gen() {
                    Ok(link_gen) => {
                        metrics.add_metric(&format!("_gpu.{}.pcieLinkGen", di), link_gen);
                    }
                    Err(_) => {
                        availability.link_gen = false;
                    }
                }
            }

            // PCIe Link Speed
            if availability.link_speed {
                match device
                    .pcie_link_speed()
                    .map(u64::from)
                    .map(|x| x * 1_000_000)
                {
                    Ok(link_speed) => {
                        metrics.add_metric(&format!("_gpu.{}.pcieLinkSpeed", di), link_speed);
                    }
                    Err(_) => {
                        availability.link_speed = false;
                    }
                }
            }

            // PCIe Link Width
            if availability.link_width {
                match device.current_pcie_link_width() {
                    Ok(link_width) => {
                        metrics.add_metric(&format!("_gpu.{}.pcieLinkWidth", di), link_width);
                    }
                    Err(_) => {
                        availability.link_width = false;
                    }
                }
            }

            // Max PCIe Link Generation
            if availability.max_link_gen {
                match device.max_pcie_link_gen() {
                    Ok(max_link_gen) => {
                        metrics.add_metric(&format!("_gpu.{}.maxPcieLinkGen", di), max_link_gen);
                    }
                    Err(_) => {
                        availability.max_link_gen = false;
                    }
                }
            }

            // Max PCIe Link Width
            if availability.max_link_width {
                match device.max_pcie_link_width() {
                    Ok(max_link_width) => {
                        metrics
                            .add_metric(&format!("_gpu.{}.maxPcieLinkWidth", di), max_link_width);
                    }
                    Err(_) => {
                        availability.max_link_width = false;
                    }
                }
            }
        }

        Ok(())
    }

    pub fn shutdown(self) -> Result<(), NvmlError> {
        self.nvml.shutdown()
    }
}

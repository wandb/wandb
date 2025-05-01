use crate::metrics::MetricValue;
use crate::wandb_internal::{GpuNvidiaInfo, MetadataRequest};

use nvml_wrapper::enum_wrappers::device::{Clock, TemperatureSensor};
use nvml_wrapper::error::NvmlError;
use nvml_wrapper::{Device, Nvml};
use std::collections::HashMap;
use std::path::PathBuf;

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
            // TODO: enable these metrics
            link_gen: false,
            link_speed: false,
            link_width: false,
            max_link_gen: false,
            max_link_width: false,
        }
    }
}

/// Get the path to the NVML library.
pub fn get_lib_path() -> Result<PathBuf, NvmlError> {
    #[cfg(target_os = "windows")]
    {
        use std::env;
        use std::path::Path;

        let mut search_paths = Vec::new();

        // First, check for nvml.dll in System32 for DCH drivers
        let windir = env::var("WINDIR").unwrap_or_else(|_| "C:\\Windows".to_string());
        let path1 = Path::new(&windir).join("System32").join("nvml.dll");
        search_paths.push(path1);

        // Then, check in Program Files
        let program_files =
            env::var("ProgramFiles").unwrap_or_else(|_| "C:\\Program Files".to_string());
        let path2 = Path::new(&program_files)
            .join("NVIDIA Corporation")
            .join("NVSMI")
            .join("nvml.dll");
        search_paths.push(path2);

        // Finally, check for NVML_DLL_PATH environment variable
        if let Ok(nvml_path) = env::var("NVML_DLL_PATH") {
            search_paths.push(PathBuf::from(nvml_path));
        }

        // Check if nvml.dll exists in any of the search paths
        for path in &search_paths {
            if path.exists() {
                return Ok(path.clone());
            }
        }

        return Err(NvmlError::NotFound);
    }

    #[cfg(not(target_os = "windows"))]
    {
        // On Linux, Nvml::init() attempts to load libnvidia-ml.so, which is usually a symlink
        // to libnvidia-ml.so.1 and not available in certain environments.
        // We follow NVIDIA's go-nvml example and attempt to load libnvidia-ml.so.1 directly, see:
        // https://github.com/NVIDIA/go-nvml/blob/0e815c71ca6e8184387d8b502b2ef2d2722165b9/pkg/nvml/lib.go#L30
        Ok(PathBuf::from("libnvidia-ml.so.1"))
    }
}

/// Struct to collect metrics from NVIDIA GPUs using NVML.
pub struct NvidiaGpu {
    nvml: Nvml,
    cuda_version: String,
    device_count: u32,
    gpu_static_info: Vec<GpuStaticInfo>,
    gpu_metric_availability: Vec<GpuMetricAvailability>,
}

impl NvidiaGpu {
    pub fn new() -> Result<Self, NvmlError> {
        let lib_path = get_lib_path()?;

        let nvml = Nvml::builder().lib_path(lib_path.as_os_str()).init()?;
        let cuda_version = nvml.sys_cuda_driver_version()?;
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

        // Initialize metric availability with default values.
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

    /// Check if a GPU is being used by a specific process or its descendants.
    #[cfg(target_os = "linux")]
    fn gpu_in_use_by_process(&self, device: &Device, pid: i32) -> bool {
        let mut our_pids = Vec::new();
        if let Ok(descendant_pids) = self.get_descendant_pids(pid) {
            our_pids.extend(descendant_pids);
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

    /// Get descendant process IDs for a given parent PID.
    #[cfg(target_os = "linux")]
    fn get_descendant_pids(&self, parent_pid: i32) -> Result<Vec<i32>, std::io::Error> {
        use std::collections::HashSet;
        use std::fs::read_to_string;

        let mut descendant_pids = Vec::new();
        let mut visited_pids = HashSet::new();
        let mut stack = vec![parent_pid];

        while let Some(pid) = stack.pop() {
            // Skip if we've already visited this PID
            if !visited_pids.insert(pid) {
                continue;
            }

            let children_path = format!("/proc/{}/task/{}/children", pid, pid);
            match read_to_string(&children_path) {
                Ok(contents) => {
                    let child_pids: Vec<i32> = contents
                        .split_whitespace()
                        .filter_map(|s| s.parse::<i32>().ok())
                        .collect();
                    stack.extend(&child_pids);
                    descendant_pids.extend(&child_pids);
                }
                Err(_) => {
                    continue; // Skip to the next PID
                }
            }
        }

        Ok(descendant_pids)
    }

    #[cfg(not(target_os = "linux"))]
    fn gpu_in_use_by_process(&self, _device: &Device, _pid: i32) -> bool {
        // TODO: Implement for other platforms
        false
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
    /// gpu.{i}.smClock: The current SM clock speed of the GPU at index i (in MHz).
    /// gpu.{i}.correctedMemoryErrors: The number of corrected memory errors on the GPU at index i.
    /// gpu.{i}.uncorrectedMemoryErrors: The number of uncorrected memory errors on the GPU at index i.
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
    ///
    /// Note that {i} represents the index of each GPU in the system, starting from 0.
    ///
    /// # Arguments
    ///
    /// * `pid` - The process ID to monitor for GPU usage.
    /// * `gpu_device_ids` - An optional list of GPU device IDs to monitor. If not provided,
    ///  all GPUs are monitored.
    ///
    /// # Returns
    ///
    /// A vector of tuples containing the metric name and value for each metric collected.
    /// If an error occurs while collecting metrics, an `NvmlError` is returned.
    ///
    /// # Errors
    ///
    /// This function should return an error only if an internal NVML call fails.
    /// ```
    pub fn get_metrics(
        &mut self,
        pid: i32,
        gpu_device_ids: Option<Vec<i32>>,
    ) -> Result<Vec<(String, MetricValue)>, NvmlError> {
        let mut metrics: Vec<(String, MetricValue)> = vec![];

        metrics.push((
            "_cuda_version".to_string(),
            MetricValue::String(self.cuda_version.clone()),
        ));
        metrics.push((
            "_gpu.count".to_string(),
            MetricValue::Int(self.device_count as i64),
        ));

        for di in 0..self.device_count {
            // Skip GPU if not in the list of device IDs to monitor.
            // If no device IDs are provided, monitor all GPUs.
            if let Some(ref gpu_device_ids) = gpu_device_ids {
                if !gpu_device_ids.contains(&(di as i32)) {
                    continue;
                }
            }

            let device = match self.nvml.device_by_index(di) {
                Ok(device) => device,
                Err(_e) => {
                    continue;
                }
            };

            // Populate static information about the GPU
            metrics.push((
                format!("_gpu.{}.name", di),
                MetricValue::String(self.gpu_static_info[di as usize].name.clone()),
            ));
            metrics.push((
                format!("_gpu.{}.brand", di),
                MetricValue::String(self.gpu_static_info[di as usize].brand.clone()),
            ));
            metrics.push((
                format!("_gpu.{}.cudaCores", di),
                MetricValue::Int(self.gpu_static_info[di as usize].cuda_cores as i64),
            ));
            metrics.push((
                format!("_gpu.{}.architecture", di),
                MetricValue::String(self.gpu_static_info[di as usize].architecture.clone()),
            ));

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
                        metrics.push((
                            format!("gpu.{}.gpu", di),
                            MetricValue::Float(utilization.gpu as f64),
                        ));
                        metrics.push((
                            format!("gpu.{}.memory", di),
                            MetricValue::Int(utilization.memory as i64),
                        ));

                        if gpu_in_use {
                            metrics.push((
                                format!("gpu.process.{}.gpu", di),
                                MetricValue::Float(utilization.gpu as f64),
                            ));
                            metrics.push((
                                format!("gpu.process.{}.memory", di),
                                MetricValue::Int(utilization.memory as i64),
                            ));
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
                        metrics.push((
                            format!("_gpu.{}.memoryTotal", di),
                            MetricValue::Int(memory_info.total as i64),
                        ));
                        let memory_allocated =
                            (memory_info.used as f64 / memory_info.total as f64) * 100.0;
                        metrics.push((
                            format!("gpu.{}.memoryAllocated", di),
                            MetricValue::Float(memory_allocated),
                        ));
                        metrics.push((
                            format!("gpu.{}.memoryAllocatedBytes", di),
                            MetricValue::Int(memory_info.used as i64),
                        ));

                        if gpu_in_use {
                            metrics.push((
                                format!("gpu.process.{}.memoryAllocated", di),
                                MetricValue::Float(memory_allocated),
                            ));
                            metrics.push((
                                format!("gpu.process.{}.memoryAllocatedBytes", di),
                                MetricValue::Int(memory_info.used as i64),
                            ));
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
                        metrics.push((
                            format!("gpu.{}.temp", di),
                            MetricValue::Float(temperature as f64),
                        ));
                        if gpu_in_use {
                            metrics.push((
                                format!("gpu.process.{}.temp", di),
                                MetricValue::Float(temperature as f64),
                            ));
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
                        metrics.push((
                            format!("gpu.{}.powerWatts", di),
                            MetricValue::Float(power_usage),
                        ));
                        if gpu_in_use {
                            metrics.push((
                                format!("gpu.process.{}.powerWatts", di),
                                MetricValue::Float(power_usage),
                            ));
                        }

                        if availability.enforced_power_limit {
                            match device.enforced_power_limit() {
                                Ok(power_limit) => {
                                    let power_limit = power_limit as f64 / 1000.0;
                                    metrics.push((
                                        format!("gpu.{}.enforcedPowerLimitWatts", di),
                                        MetricValue::Float(power_limit),
                                    ));
                                    let power_percent = (power_usage / power_limit) * 100.0;
                                    metrics.push((
                                        format!("gpu.{}.powerPercent", di),
                                        MetricValue::Float(power_percent),
                                    ));

                                    if gpu_in_use {
                                        metrics.push((
                                            format!("gpu.process.{}.enforcedPowerLimitWatts", di),
                                            MetricValue::Float(power_limit),
                                        ));
                                        metrics.push((
                                            format!("gpu.process.{}.powerPercent", di),
                                            MetricValue::Float(power_percent),
                                        ));
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
                        metrics.push((
                            format!("gpu.{}.smClock", di),
                            MetricValue::Int(sm_clock as i64),
                        ));
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
                        metrics.push((
                            format!("gpu.{}.memoryClock", di),
                            MetricValue::Int(mem_clock as i64),
                        ));
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
                        metrics.push((
                            format!("gpu.{}.graphicsClock", di),
                            MetricValue::Int(graphics_clock as i64),
                        ));
                    }
                    Err(_) => {
                        availability.graphics_clock = false;
                    }
                }
            }

            // Corrected Memory Errors
            if availability.corrected_memory_errors {
                // NOTE: Nvidia GPUs provide two ECC counters: volatile and aggregate.
                // The volatile counter resets on driver or GPU reset, while the
                // aggregate counter persists for the GPU's lifetime. After row
                // remapping repairs ECC errors, the aggregate counter remains
                // non-zero and can falsely indicate a problem. Using the volatile
                // counter avoids this confusion.
                match device.memory_error_counter(
                    nvml_wrapper::enum_wrappers::device::MemoryError::Corrected,
                    nvml_wrapper::enum_wrappers::device::EccCounter::Volatile,
                    nvml_wrapper::enum_wrappers::device::MemoryLocation::Device,
                ) {
                    Ok(errors) => {
                        metrics.push((
                            format!("gpu.{}.correctedMemoryErrors", di),
                            MetricValue::Int(errors as i64),
                        ));
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
                    nvml_wrapper::enum_wrappers::device::EccCounter::Volatile,
                    nvml_wrapper::enum_wrappers::device::MemoryLocation::Device,
                ) {
                    Ok(errors) => {
                        metrics.push((
                            format!("gpu.{}.uncorrectedMemoryErrors", di),
                            MetricValue::Int(errors as i64),
                        ));
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
                        metrics.push((
                            format!("gpu.{}.fanSpeed", di),
                            MetricValue::Int(fan_speed as i64),
                        ));
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
                        metrics.push((
                            format!("gpu.{}.encoderUtilization", di),
                            MetricValue::Float(encoder_util.utilization as f64),
                        ));
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
                        metrics.push((
                            format!("gpu.{}.pcieLinkGen", di),
                            MetricValue::Int(link_gen as i64),
                        ));
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
                        metrics.push((
                            format!("gpu.{}.pcieLinkSpeed", di),
                            MetricValue::Int(link_speed as i64),
                        ));
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
                        metrics.push((
                            format!("gpu.{}.pcieLinkWidth", di),
                            MetricValue::Int(link_width as i64),
                        ));
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
                        metrics.push((
                            format!("gpu.{}.maxPcieLinkGen", di),
                            MetricValue::Int(max_link_gen as i64),
                        ));
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
                        metrics.push((
                            format!("gpu.{}.maxPcieLinkWidth", di),
                            MetricValue::Int(max_link_width as i64),
                        ));
                    }
                    Err(_) => {
                        availability.max_link_width = false;
                    }
                }
            }
        }

        Ok(metrics)
    }

    /// Extract metadata about the GPUs in the system from the provided samples.
    pub fn get_metadata(&self, samples: &HashMap<String, &MetricValue>) -> MetadataRequest {
        let mut metadata_request = MetadataRequest {
            ..Default::default()
        };

        let n_gpu = match samples.get("_gpu.count") {
            Some(MetricValue::Int(n_gpu)) => *n_gpu as u32,
            _ => return metadata_request,
        };

        metadata_request.gpu_nvidia = [].to_vec();
        metadata_request.gpu_count = n_gpu;
        // TODO: do not assume all GPUs are the same
        if let Some(value) = samples.get("_gpu.0.name") {
            if let MetricValue::String(ref gpu_name) = value {
                metadata_request.gpu_type = gpu_name.clone();
            }
        }
        if let Some(value) = samples.get("_cuda_version") {
            if let MetricValue::String(ref cuda_version) = value {
                metadata_request.cuda_version = cuda_version.clone();
            }
        }

        for i in 0..n_gpu {
            let mut gpu_nvidia = GpuNvidiaInfo {
                ..Default::default()
            };
            if let Some(value) = samples.get(&format!("_gpu.{}.name", i)) {
                if let MetricValue::String(ref gpu_name) = value {
                    gpu_nvidia.name = gpu_name.clone();
                }
            }
            if let Some(value) = samples.get(&format!("_gpu.{}.memoryTotal", i)) {
                if let MetricValue::Int(memory_total) = value {
                    gpu_nvidia.memory_total = *memory_total as u64;
                }
            }
            // cuda cores
            if let Some(value) = samples.get(&format!("_gpu.{}.cudaCores", i)) {
                if let MetricValue::Int(cuda_cores) = value {
                    gpu_nvidia.cuda_cores = *cuda_cores as u32;
                }
            }
            // architecture
            if let Some(value) = samples.get(&format!("_gpu.{}.architecture", i)) {
                if let MetricValue::String(ref architecture) = value {
                    gpu_nvidia.architecture = architecture.clone();
                }
            }
            metadata_request.gpu_nvidia.push(gpu_nvidia);
        }
        metadata_request
    }
}

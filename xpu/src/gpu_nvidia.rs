use crate::metrics::{MetricValue, Sample};
use crate::wandb_internal::{EnvironmentRecord, GpuNvidiaInfo};

use nvml_wrapper::enum_wrappers::device::{Clock, PcieUtilCounter, TemperatureSensor};
use nvml_wrapper::enums::gpm::GpmMetricId;
use nvml_wrapper::error::NvmlError;
use nvml_wrapper::gpm;
use nvml_wrapper::{Device, Nvml};
use std::collections::HashMap;
use std::time::{Duration, Instant};

/// Minimum age of the previous GPM sample before a new one is paired with it.
/// NVML requires at least 100 ms between the two samples of a pair.
const GPM_MIN_SAMPLE_INTERVAL: Duration = Duration::from_millis(100);

/// GPM (GPU Performance Monitoring) metrics to collect and their output names.
///
/// These match the DCGM profiling metric names exactly so that downstream
/// consumers (LEET, the web UI, etc.) work identically regardless of whether
/// metrics came from DCGM or NVML GPM.
///
/// GPM is supported on Hopper+ architectures (H100 and newer). Each metric is
/// computed between the sample taken on the previous poll and a fresh one, so
/// it is an average over the whole polling interval.
///
/// The third element scales NVML's value into the unit the name implies:
/// percentages are used as is, throughput comes from NVML in MiB/s.
const GPM_METRICS: &[(GpmMetricId, &str, f64)] = &[
    (GpmMetricId::SmUtil, "smActive", 1.0),
    (GpmMetricId::SmOccupancy, "smOccupancy", 1.0),
    (GpmMetricId::AnyTensorUtil, "pipeTensorActive", 1.0),
    (GpmMetricId::DramBwUtil, "dramActive", 1.0),
    (GpmMetricId::Fp64Util, "pipeFp64Active", 1.0),
    (GpmMetricId::Fp32Util, "pipeFp32Active", 1.0),
    (GpmMetricId::Fp16Util, "pipeFp16Active", 1.0),
    (GpmMetricId::HmmaTensorUtil, "pipeTensorHmmaActive", 1.0),
    (GpmMetricId::PcieTxPerSec, "pcieTxBytes", MIB),
    (GpmMetricId::PcieRxPerSec, "pcieRxBytes", MIB),
    (GpmMetricId::NvlinkTotalTxPerSec, "nvlinkTxBytes", MIB),
    (GpmMetricId::NvlinkTotalRxPerSec, "nvlinkRxBytes", MIB),
];

const MIB: f64 = 1024.0 * 1024.0;

/// Static information about a GPU.
#[derive(Default)]
struct GpuStaticInfo {
    name: String,
    brand: String,
    cuda_cores: u32,
    architecture: String,

    /// Globally unique immutable UUID associated with this Device as a 5 part hex string.
    /// Note that when using the Multi-Instance GPU (MIG) feature, one physical GPU can be
    /// partitioned into multiple GPU instances, all sharing the same UUID.
    uuid: String,
    /// PCI bus ID as NVML formats it, e.g. "00000000:1B:00.0".
    pci_bus_id: String,
    /// NUMA node the GPU is attached to, when the platform reports one.
    numa_node: Option<u32>,
}

/// Tracks the availability of GPU metrics for the current system.
#[derive(Clone)]
struct GpuMetricAvailability {
    utilization: bool,
    memory_info: bool,
    temperature: bool,
    power_usage: bool,
    enforced_power_limit: bool,
    energy: bool,
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
    pcie_throughput: bool,
    gpm: bool,
}

impl Default for GpuMetricAvailability {
    fn default() -> Self {
        Self {
            utilization: true,
            memory_info: true,
            temperature: true,
            power_usage: true,
            enforced_power_limit: true,
            energy: true,
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
            pcie_throughput: true,
            gpm: false,
        }
    }
}

/// Get the path to the NVML library.
#[cfg(target_os = "windows")]
fn get_lib_path() -> Result<std::path::PathBuf, NvmlError> {
    use std::env;
    use std::path::{Path, PathBuf};

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

    Err(NvmlError::NotFound)
}

/// The NUMA node a PCI device is attached to, from sysfs. `None` where the
/// platform does not report one.
///
/// NVML's own `nvmlDeviceGetNumaNodeId` is not used: it applies only to
/// platforms where the GPU itself is a NUMA node.
#[cfg(target_os = "linux")]
fn pci_numa_node(pci_info: &nvml_wrapper::struct_wrappers::device::PciInfo) -> Option<u32> {
    let path = format!(
        "/sys/bus/pci/devices/{:04x}:{:02x}:{:02x}.0/numa_node",
        pci_info.domain, pci_info.bus, pci_info.device
    );
    std::fs::read_to_string(path).ok()?.trim().parse().ok()
}

#[cfg(not(target_os = "linux"))]
fn pci_numa_node(_pci_info: &nvml_wrapper::struct_wrappers::device::PciInfo) -> Option<u32> {
    None
}

/// NvidiaGpu collects metadata and metrics from NVIDIA GPUs using NVML.
pub struct NvidiaGpu {
    /// Leaked so that the GPM samples, which borrow it, can be stored alongside.
    nvml: &'static Nvml,
    cuda_version: String,
    device_count: u32,
    gpu_static_info: Vec<GpuStaticInfo>,
    gpu_metric_availability: Vec<GpuMetricAvailability>,
    /// The GPM sample from the previous poll and when it was taken, per device.
    gpm_samples: Vec<Option<(gpm::GpmSample<'static>, Instant)>>,
}

impl NvidiaGpu {
    pub fn new() -> Result<Self, NvmlError> {
        #[cfg(target_os = "windows")]
        let nvml = Nvml::builder()
            .lib_path(get_lib_path()?.as_os_str())
            .init()?;
        #[cfg(not(target_os = "windows"))]
        let nvml = Nvml::init()?;
        let nvml: &'static Nvml = Box::leak(Box::new(nvml));
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
            if let Ok(uuid) = device.uuid() {
                static_info.uuid = uuid;
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
            if let Ok(pci_info) = device.pci_info() {
                static_info.numa_node = pci_numa_node(&pci_info);
                static_info.pci_bus_id = pci_info.bus_id;
            }

            gpu_static_info.push(static_info);
        }

        // Initialize metric availability with default values.
        let mut gpu_metric_availability =
            vec![GpuMetricAvailability::default(); device_count as usize];

        // Probe GPM (GPU Performance Monitoring) support per device.
        // GPM requires Hopper+ (H100 and newer).
        for di in 0..device_count {
            if let Ok(device) = nvml.device_by_index(di) {
                if device.gpm_support().unwrap_or(false) {
                    gpu_metric_availability[di as usize].gpm = true;
                }
            }
        }

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
            gpm_samples: (0..device_count).map(|_| None).collect(),
        })
    }

    /// The PIDs of the processes running on a GPU.
    fn device_pids(device: &Device) -> Vec<u32> {
        device
            .running_compute_processes()
            .unwrap_or_default()
            .into_iter()
            .chain(device.running_graphics_processes().unwrap_or_default())
            .map(|p| p.pid)
            .collect()
    }

    /// Samples GPU metrics using NVML.
    ///
    /// This function collects various metrics from all available GPUs, including
    /// utilization, memory usage, temperature, and power consumption, and lists
    /// the processes running on each GPU so that a client's record can repeat the
    /// metrics of the GPUs its process uses as `gpu.process.{i}.*`.
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
    /// gpu.{i}.energyJoules: Energy consumed by the GPU at index i since its driver loaded (in Joules).
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
    /// gpu.{i}.pcieTxBytes / pcieRxBytes: PCIe throughput (bytes/sec). On GPUs without GPM this
    ///    is NVML's reading over a 20 ms window.
    /// gpu.{i}.cudaCores: The number of CUDA cores in the GPU at index i.
    /// gpu.{i}.architecture: The architecture of the GPU at index i (e.g., Ampere, Turing).
    ///
    /// GPM profiling metrics (Hopper+ only, via NVML GPU Performance Monitoring):
    /// gpu.{i}.smActive: SM utilization (%).
    /// gpu.{i}.smOccupancy: Warp occupancy vs theoretical max (%).
    /// gpu.{i}.dramActive: DRAM bandwidth utilization (%).
    /// gpu.{i}.pipeTensorActive: Any tensor ops active (%).
    /// gpu.{i}.pipeTensorHmmaActive: HMMA tensor ops active (%).
    /// gpu.{i}.pipeFp64Active / pipeFp32Active / pipeFp16Active: FP pipeline utilization (%).
    /// gpu.{i}.pcieTxBytes / pcieRxBytes: PCIe throughput (bytes/sec).
    /// gpu.{i}.nvlinkTxBytes / nvlinkRxBytes: NVLink throughput (bytes/sec).
    ///
    /// Note that {i} represents the index of each GPU in the system, starting from 0.
    ///
    /// # Errors
    ///
    /// This function should return an error only if an internal NVML call fails.
    pub fn get_metrics(&mut self) -> Result<Sample, NvmlError> {
        let mut metrics: Vec<(String, MetricValue)> = vec![];
        let mut averages: Vec<(String, f64)> = vec![];
        let mut gpu_pids = HashMap::new();

        metrics.push((
            "_cuda_version".to_string(),
            MetricValue::String(self.cuda_version.clone()),
        ));
        metrics.push((
            "_gpu.count".to_string(),
            MetricValue::Int(self.device_count as i64),
        ));

        let gpm_metric_ids: Vec<GpmMetricId> = GPM_METRICS.iter().map(|(id, _, _)| *id).collect();

        for di in 0..self.device_count {
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
                format!("_gpu.{}.uuid", di),
                MetricValue::String(self.gpu_static_info[di as usize].uuid.clone()),
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
            metrics.push((
                format!("_gpu.{}.pciBusId", di),
                MetricValue::String(self.gpu_static_info[di as usize].pci_bus_id.clone()),
            ));
            if let Some(numa_node) = self.gpu_static_info[di as usize].numa_node {
                metrics.push((
                    format!("_gpu.{}.numaNode", di),
                    MetricValue::Int(numa_node as i64),
                ));
            }

            gpu_pids.insert(di, Self::device_pids(&device));

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

            // Energy
            if availability.energy {
                match device.total_energy_consumption() {
                    Ok(millijoules) => {
                        metrics.push((
                            format!("gpu.{}.energyJoules", di),
                            MetricValue::Float(millijoules as f64 / 1000.0),
                        ));
                    }
                    Err(_) => {
                        availability.energy = false;
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

            // PCIe throughput. GPUs with GPM report it among the GPM metrics below.
            if availability.pcie_throughput && !availability.gpm {
                match (
                    device.pcie_throughput(PcieUtilCounter::Send),
                    device.pcie_throughput(PcieUtilCounter::Receive),
                ) {
                    (Ok(tx), Ok(rx)) => {
                        averages.push((format!("gpu.{}.pcieTxBytes", di), tx as f64 * 1024.0));
                        averages.push((format!("gpu.{}.pcieRxBytes", di), rx as f64 * 1024.0));
                    }
                    _ => {
                        availability.pcie_throughput = false;
                    }
                }
            }

            // GPM metrics, computed between the previous poll's sample and a fresh one.
            if availability.gpm {
                let slot = &mut self.gpm_samples[di as usize];
                let due = slot
                    .as_ref()
                    .is_none_or(|(_, taken_at)| taken_at.elapsed() >= GPM_MIN_SAMPLE_INTERVAL);
                if due {
                    match device.gpm_sample() {
                        Ok(sample) => {
                            if let Some((previous, _)) = slot.take() {
                                match gpm::gpm_metrics_get(
                                    self.nvml,
                                    &previous,
                                    &sample,
                                    &gpm_metric_ids,
                                ) {
                                    Ok(results) => {
                                        for (result, (_, name, scale)) in
                                            results.iter().zip(GPM_METRICS)
                                        {
                                            if let Ok(m) = result {
                                                averages.push((
                                                    format!("gpu.{}.{}", di, name),
                                                    m.value * scale,
                                                ));
                                            }
                                        }
                                    }
                                    Err(_) => {
                                        availability.gpm = false;
                                    }
                                }
                            }
                            *slot = Some((sample, Instant::now()));
                        }
                        Err(_) => {
                            availability.gpm = false;
                        }
                    }
                }
            }
        }

        Ok(Sample {
            metrics,
            averages,
            gpu_pids,
        })
    }

    /// Extract metadata about the GPUs in the system from the provided samples.
    pub fn get_metadata(&self, samples: &HashMap<String, &MetricValue>) -> EnvironmentRecord {
        let mut metadata = EnvironmentRecord {
            ..Default::default()
        };

        let n_gpu = match samples.get("_gpu.count") {
            Some(MetricValue::Int(n_gpu)) => *n_gpu as u32,
            _ => return metadata,
        };

        metadata.gpu_nvidia = [].to_vec();
        metadata.gpu_count = n_gpu;
        // TODO: do not assume all GPUs are the same
        if let Some(value) = samples.get("_gpu.0.name") {
            if let MetricValue::String(gpu_name) = value {
                metadata.gpu_type = gpu_name.clone();
            }
        }
        if let Some(value) = samples.get("_cuda_version") {
            if let MetricValue::String(cuda_version) = value {
                metadata.cuda_version = cuda_version.clone();
            }
        }

        for i in 0..n_gpu {
            let mut gpu_nvidia = GpuNvidiaInfo {
                ..Default::default()
            };
            if let Some(value) = samples.get(&format!("_gpu.{}.name", i)) {
                if let MetricValue::String(gpu_name) = value {
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
                if let MetricValue::String(architecture) = value {
                    gpu_nvidia.architecture = architecture.clone();
                }
            }
            // uuid
            if let Some(value) = samples.get(&format!("_gpu.{}.uuid", i)) {
                if let MetricValue::String(uuid) = value {
                    gpu_nvidia.uuid = uuid.clone();
                }
            }
            if let Some(value) = samples.get(&format!("_gpu.{}.pciBusId", i)) {
                if let MetricValue::String(pci_bus_id) = value {
                    gpu_nvidia.pci_bus_id = pci_bus_id.clone();
                }
            }
            if let Some(value) = samples.get(&format!("_gpu.{}.numaNode", i)) {
                if let MetricValue::Int(numa_node) = value {
                    gpu_nvidia.numa_node = Some(*numa_node as u32);
                }
            }
            metadata.gpu_nvidia.push(gpu_nvidia);
        }

        metadata
    }
}

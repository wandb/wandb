use crate::metrics::{Field, MetricValue, NvidiaRate, Sample};
use crate::wandb_internal::{
    AcceleratorMetrics, AcceleratorType, EnvironmentRecord, GpuNvidiaInfo, NvidiaMetrics,
    accelerator_metrics::Vendor,
};

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

/// GPM (GPU Performance Monitoring) metrics to collect and the fields they
/// fill, which DCGM profiling fills too.
///
/// GPM is supported on Hopper+ architectures (H100 and newer). Each metric is
/// computed between the sample taken on the previous poll and a fresh one, so
/// it is an average over the whole polling interval.
///
/// The third element scales NVML's value into the unit the name implies:
/// percentages become ratios, throughput comes from NVML in MiB/s.
const GPM_METRICS: &[(GpmMetricId, NvidiaRate, f64)] = &[
    (GpmMetricId::SmUtil, NvidiaRate::SmActive, 0.01),
    (GpmMetricId::SmOccupancy, NvidiaRate::SmOccupancy, 0.01),
    (
        GpmMetricId::AnyTensorUtil,
        NvidiaRate::PipeTensorActive,
        0.01,
    ),
    (GpmMetricId::DramBwUtil, NvidiaRate::DramActive, 0.01),
    (GpmMetricId::Fp64Util, NvidiaRate::PipeFp64Active, 0.01),
    (GpmMetricId::Fp32Util, NvidiaRate::PipeFp32Active, 0.01),
    (GpmMetricId::Fp16Util, NvidiaRate::PipeFp16Active, 0.01),
    (
        GpmMetricId::HmmaTensorUtil,
        NvidiaRate::PipeTensorHmmaActive,
        0.01,
    ),
    (GpmMetricId::PcieTxPerSec, NvidiaRate::PcieTx, MIB),
    (GpmMetricId::PcieRxPerSec, NvidiaRate::PcieRx, MIB),
    (GpmMetricId::NvlinkTotalTxPerSec, NvidiaRate::NvlinkTx, MIB),
    (GpmMetricId::NvlinkTotalRxPerSec, NvidiaRate::NvlinkRx, MIB),
];

const MIB: f64 = 1024.0 * 1024.0;

/// The source of the accelerators this collector reports.
const NVML: &str = "nvml";

/// Static information about a GPU.
#[derive(Default)]
struct GpuStaticInfo {
    name: String,
    brand: String,
    cuda_cores: u32,
    architecture: String,

    /// Globally unique immutable UUID associated with this Device as a 5 part hex string.
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
    corrected_memory_errors: bool,
    uncorrected_memory_errors: bool,
    fan_speed: bool,
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
            corrected_memory_errors: true,
            uncorrected_memory_errors: true,
            fan_speed: true,
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

    /// Samples every GPU through NVML: a typed accelerator per device, the
    /// GPM metrics and the PCIe throughput as averages, the processes on each
    /// device, and the static facts behind the run metadata under `_` keys.
    ///
    /// A reading that fails once is not read again.
    ///
    /// # Errors
    ///
    /// This function should return an error only if an internal NVML call fails.
    pub fn get_metrics(&mut self) -> Result<Sample, NvmlError> {
        let mut sample = Sample::default();
        let metrics = &mut sample.metrics;

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
            let info = &self.gpu_static_info[di as usize];

            // Populate static information about the GPU
            metrics.push((
                format!("_gpu.{}.name", di),
                MetricValue::String(info.name.clone()),
            ));
            metrics.push((
                format!("_gpu.{}.uuid", di),
                MetricValue::String(info.uuid.clone()),
            ));
            metrics.push((
                format!("_gpu.{}.brand", di),
                MetricValue::String(info.brand.clone()),
            ));
            metrics.push((
                format!("_gpu.{}.cudaCores", di),
                MetricValue::Int(info.cuda_cores as i64),
            ));
            metrics.push((
                format!("_gpu.{}.architecture", di),
                MetricValue::String(info.architecture.clone()),
            ));
            metrics.push((
                format!("_gpu.{}.pciBusId", di),
                MetricValue::String(info.pci_bus_id.clone()),
            ));
            if let Some(numa_node) = info.numa_node {
                metrics.push((
                    format!("_gpu.{}.numaNode", di),
                    MetricValue::Int(numa_node as i64),
                ));
            }

            sample.gpu_pids.insert(di, Self::device_pids(&device));

            let mut gpu = AcceleratorMetrics {
                r#type: AcceleratorType::NvidiaGpu as i32,
                index: di,
                uuid: info.uuid.clone(),
                source: NVML.to_string(),
                pci_bus_id: info.pci_bus_id.clone(),
                model: info.name.clone(),
                ..Default::default()
            };
            let mut nvidia = NvidiaMetrics::default();
            let availability = &mut self.gpu_metric_availability[di as usize];
            // Reads a metric while it is available, and marks it unavailable
            // after the first failure.
            fn read<T>(available: &mut bool, value: Result<T, NvmlError>) -> Option<T> {
                if !*available {
                    return None;
                }
                let value = value.ok();
                *available = value.is_some();
                value
            }

            if let Some(utilization) =
                read(&mut availability.utilization, device.utilization_rates())
            {
                gpu.utilization_ratio = Some(f64::from(utilization.gpu) / 100.0);
                gpu.memory_activity_ratio = Some(f64::from(utilization.memory) / 100.0);
            }

            if let Some(memory) = read(&mut availability.memory_info, device.memory_info()) {
                metrics.push((
                    format!("_gpu.{}.memoryTotal", di),
                    MetricValue::Int(memory.total as i64),
                ));
                gpu.memory_used_ratio = Some(memory.used as f64 / memory.total as f64);
                gpu.memory_used_bytes = Some(memory.used);
            }

            gpu.temperature_c = read(
                &mut availability.temperature,
                device.temperature(TemperatureSensor::Gpu),
            )
            .map(f64::from);

            if let Some(milliwatts) = read(&mut availability.power_usage, device.power_usage()) {
                let watts = milliwatts as f64 / 1000.0;
                gpu.power_w = Some(watts);
                if let Some(limit) = read(
                    &mut availability.enforced_power_limit,
                    device.enforced_power_limit(),
                ) {
                    let limit = limit as f64 / 1000.0;
                    gpu.power_limit_w = Some(limit);
                    gpu.power_ratio = Some(watts / limit);
                }
            }

            gpu.energy_j = read(&mut availability.energy, device.total_energy_consumption())
                .map(|millijoules| millijoules as f64 / 1000.0);
            let hz = |mhz: u32| f64::from(mhz) * 1e6;
            nvidia.sm_clock_hz =
                read(&mut availability.sm_clock, device.clock_info(Clock::SM)).map(hz);
            nvidia.memory_clock_hz = read(
                &mut availability.mem_clock,
                device.clock_info(Clock::Memory),
            )
            .map(hz);

            // NOTE: Nvidia GPUs provide two ECC counters: volatile and aggregate.
            // The volatile counter resets on driver or GPU reset, while the
            // aggregate counter persists for the GPU's lifetime. After row
            // remapping repairs ECC errors, the aggregate counter remains
            // non-zero and can falsely indicate a problem. Using the volatile
            // counter avoids this confusion.
            use nvml_wrapper::enum_wrappers::device::{EccCounter, MemoryError, MemoryLocation};
            nvidia.corrected_memory_errors = read(
                &mut availability.corrected_memory_errors,
                device.memory_error_counter(
                    MemoryError::Corrected,
                    EccCounter::Volatile,
                    MemoryLocation::Device,
                ),
            );
            nvidia.uncorrected_memory_errors = read(
                &mut availability.uncorrected_memory_errors,
                device.memory_error_counter(
                    MemoryError::Uncorrected,
                    EccCounter::Volatile,
                    MemoryLocation::Device,
                ),
            );

            gpu.fan_speed_ratio = read(&mut availability.fan_speed, device.fan_speed(0))
                .map(|percent| f64::from(percent) / 100.0);

            // PCIe throughput. GPUs with GPM report it among the GPM metrics below.
            if availability.pcie_throughput && !availability.gpm {
                match (
                    device.pcie_throughput(PcieUtilCounter::Send),
                    device.pcie_throughput(PcieUtilCounter::Receive),
                ) {
                    (Ok(tx), Ok(rx)) => {
                        let rate = |rate| Field::Nvidia(NVML, di, rate);
                        sample
                            .averages
                            .push((rate(NvidiaRate::PcieTx), tx as f64 * 1024.0));
                        sample
                            .averages
                            .push((rate(NvidiaRate::PcieRx), rx as f64 * 1024.0));
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
                        Ok(gpm_sample) => {
                            if let Some((previous, _)) = slot.take() {
                                match gpm::gpm_metrics_get(
                                    self.nvml,
                                    &previous,
                                    &gpm_sample,
                                    &gpm_metric_ids,
                                ) {
                                    Ok(results) => {
                                        for (result, (_, rate, scale)) in
                                            results.iter().zip(GPM_METRICS)
                                        {
                                            if let Ok(m) = result {
                                                sample.averages.push((
                                                    Field::Nvidia(NVML, di, *rate),
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
                            *slot = Some((gpm_sample, Instant::now()));
                        }
                        Err(_) => {
                            availability.gpm = false;
                        }
                    }
                }
            }

            gpu.vendor = Some(Vendor::Nvidia(nvidia));
            sample.record.accelerators.push(gpu);
        }

        Ok(sample)
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

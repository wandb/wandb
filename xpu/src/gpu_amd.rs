//! AMD GPU metrics and metadata through the ROCm SMI library, `librocm_smi64.so`,
//! loaded at runtime. Each value follows the call the `rocm-smi` tool makes for
//! the same field, so the reported keys keep their meaning.

use std::ffi::{CStr, c_char};

use libloading::{Library, Symbol};
use log::{debug, warn};

use crate::{
    metrics::MetricValue,
    wandb_internal::{EnvironmentRecord, GpuAmdInfo},
};

const LIBRARY_PATHS: &[&str] = &["librocm_smi64.so", "/opt/rocm/lib/librocm_smi64.so"];

type RsmiStatus = u32;
const RSMI_STATUS_SUCCESS: RsmiStatus = 0;

/// `RSMI_MEM_TYPE_VRAM` from `rsmi_memory_type_t`.
const RSMI_MEM_TYPE_VRAM: u32 = 0;
/// `RSMI_TEMP_TYPE_MEMORY` from `rsmi_temperature_type_t`.
const RSMI_TEMP_TYPE_MEMORY: u32 = 2;
/// `RSMI_TEMP_CURRENT` from `rsmi_temperature_metric_t`.
const RSMI_TEMP_CURRENT: u32 = 0;

type FnInit = unsafe extern "C" fn(u64) -> RsmiStatus;
type FnShutDown = unsafe extern "C" fn() -> RsmiStatus;
type FnNumDevices = unsafe extern "C" fn(*mut u32) -> RsmiStatus;
type FnGetU16 = unsafe extern "C" fn(u32, *mut u16) -> RsmiStatus;
type FnGetU32 = unsafe extern "C" fn(u32, *mut u32) -> RsmiStatus;
type FnGetU64 = unsafe extern "C" fn(u32, *mut u64) -> RsmiStatus;
/// Getters taking a memory type or sensor index before the output.
type FnGetU64Indexed = unsafe extern "C" fn(u32, u32, *mut u64) -> RsmiStatus;
type FnGetTemp = unsafe extern "C" fn(u32, u32, u32, *mut i64) -> RsmiStatus;
type FnGetPower = unsafe extern "C" fn(u32, *mut u64, *mut u32) -> RsmiStatus;
type FnGetName = unsafe extern "C" fn(u32, *mut c_char, usize) -> RsmiStatus;
type FnGetVbios = unsafe extern "C" fn(u32, *mut c_char, u32) -> RsmiStatus;
type FnGetOdVolt = unsafe extern "C" fn(u32, *mut RsmiOdVoltFreqData) -> RsmiStatus;

/// `rsmi_range_t`.
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct RsmiRange {
    lower_bound: u64,
    upper_bound: u64,
}

/// `rsmi_od_vddc_point_t`.
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct RsmiOdVddcPoint {
    frequency: u64,
    voltage: u64,
}

/// `rsmi_od_volt_freq_data_t`.
#[repr(C)]
#[derive(Default)]
struct RsmiOdVoltFreqData {
    curr_sclk_range: RsmiRange,
    curr_mclk_range: RsmiRange,
    sclk_freq_limits: RsmiRange,
    mclk_freq_limits: RsmiRange,
    curve: [RsmiOdVddcPoint; 3],
    num_regions: u32,
}

/// Collects AMD GPU metrics and metadata through the ROCm SMI library.
pub struct GpuAmd {
    lib: Library,
    device_count: u32,
}

impl GpuAmd {
    /// Loads the library and initializes it. Returns `None` when there is no AMD
    /// GPU driver, no library, or no device to monitor.
    pub fn new() -> Option<Self> {
        if !is_driver_installed() {
            return None;
        }

        let Some(lib) = LIBRARY_PATHS
            .iter()
            .find_map(|path| unsafe { Library::new(*path) }.ok())
        else {
            debug!("librocm_smi64.so not found; AMD GPU metrics disabled");
            return None;
        };

        let mut gpu = GpuAmd {
            lib,
            device_count: 0,
        };
        let init: Symbol<FnInit> = gpu.symbol(b"rsmi_init\0")?;
        let status = unsafe { init(0) };
        if status != RSMI_STATUS_SUCCESS {
            warn!("rsmi_init failed with status {status}; AMD GPU metrics disabled");
            return None;
        }

        let num_devices: Symbol<FnNumDevices> = gpu.symbol(b"rsmi_num_monitor_devices\0")?;
        let mut device_count = 0u32;
        if unsafe { num_devices(&mut device_count) } != RSMI_STATUS_SUCCESS || device_count == 0 {
            debug!("no AMD GPUs reported by the ROCm SMI library");
            return None;
        }

        gpu.device_count = device_count;
        Some(gpu)
    }

    /// Metrics for every device, keyed as `gpu.<index>.<name>`. Readings a device
    /// does not provide are left out.
    pub fn get_metrics(&self) -> Vec<(String, MetricValue)> {
        let mut metrics = Vec::new();
        let mut push = |device: u32, name: &str, value: f64| {
            metrics.push((format!("gpu.{device}.{name}"), MetricValue::Float(value)));
        };

        for device in 0..self.device_count {
            if let Some(v) = self.get_u32(b"rsmi_dev_busy_percent_get\0", device) {
                push(device, "gpu", v as f64);
            }
            if let (Some(used), Some(total)) = (
                self.get_u64_indexed(b"rsmi_dev_memory_usage_get\0", device, RSMI_MEM_TYPE_VRAM),
                self.get_u64_indexed(b"rsmi_dev_memory_total_get\0", device, RSMI_MEM_TYPE_VRAM),
            ) && total > 0
            {
                push(
                    device,
                    "memoryAllocated",
                    used as f64 / total as f64 * 100.0,
                );
            }
            if let Some(v) = self.get_u32(b"rsmi_dev_memory_busy_percent_get\0", device) {
                push(device, "memoryReadWriteActivity", v as f64);
            }
            if let Some(v) = self.get_u32(b"rsmi_dev_mem_overdrive_level_get\0", device) {
                push(device, "memoryOverDrive", v as f64);
            }
            if let Some(v) = self.temperature_celsius(device) {
                push(device, "temp", v);
            }
            if let Some(watts) = self.power_watts(device) {
                push(device, "powerWatts", watts);
                if let Some(cap) = self.power_cap_watts(device)
                    && cap > 0.0
                {
                    push(device, "powerPercent", watts / cap * 100.0);
                }
            }
        }

        metrics
    }

    /// Static information about every device.
    pub fn get_metadata(&self) -> EnvironmentRecord {
        let gpu_amd: Vec<GpuAmdInfo> = (0..self.device_count)
            .map(|device| {
                let vbios = self.get_vbios_version(device).unwrap_or_default();
                let (sclk_range, mclk_range) = self.clock_ranges(device);
                GpuAmdInfo {
                    id: device.to_string(),
                    unique_id: self
                        .get_u64(b"rsmi_dev_unique_id_get\0", device)
                        .map(|v| format!("0x{v:x}"))
                        .unwrap_or_default(),
                    performance_level: self
                        .get_u32(b"rsmi_dev_perf_level_get\0", device)
                        .map(|v| perf_level_name(v).to_string())
                        .unwrap_or_default(),
                    gpu_overdrive: self
                        .get_u32(b"rsmi_dev_overdrive_level_get\0", device)
                        .map(|v| v.to_string())
                        .unwrap_or_default(),
                    gpu_memory_overdrive: self
                        .get_u32(b"rsmi_dev_mem_overdrive_level_get\0", device)
                        .map(|v| v.to_string())
                        .unwrap_or_default(),
                    max_power: self
                        .power_cap_watts(device)
                        .map(|v| format!("{v:.1}"))
                        .unwrap_or_default(),
                    series: self
                        .get_name(b"rsmi_dev_name_get\0", device)
                        .unwrap_or_default(),
                    model: self
                        .get_u16(b"rsmi_dev_id_get\0", device)
                        .map(|v| format!("0x{v:x}"))
                        .unwrap_or_default(),
                    vendor: self
                        .get_name(b"rsmi_dev_vendor_name_get\0", device)
                        .unwrap_or_default(),
                    // rocm-smi derives the SKU from the middle part of the VBIOS version.
                    sku: match vbios.split('-').collect::<Vec<_>>()[..] {
                        [_, sku, _] if sku.len() > 1 => sku.to_string(),
                        _ => String::new(),
                    },
                    vbios_version: vbios,
                    sclk_range,
                    mclk_range,
                }
            })
            .collect();

        EnvironmentRecord {
            gpu_count: self.device_count,
            gpu_type: gpu_amd
                .first()
                .map(|gpu| gpu.series.clone())
                .unwrap_or_default(),
            gpu_amd,
            ..Default::default()
        }
    }

    fn symbol<T>(&self, name: &[u8]) -> Option<Symbol<'_, T>> {
        unsafe { self.lib.get(name) }.ok()
    }

    fn get_u16(&self, name: &[u8], device: u32) -> Option<u16> {
        let f: Symbol<FnGetU16> = self.symbol(name)?;
        let mut v = 0;
        (unsafe { f(device, &mut v) } == RSMI_STATUS_SUCCESS).then_some(v)
    }

    fn get_u32(&self, name: &[u8], device: u32) -> Option<u32> {
        let f: Symbol<FnGetU32> = self.symbol(name)?;
        let mut v = 0;
        (unsafe { f(device, &mut v) } == RSMI_STATUS_SUCCESS).then_some(v)
    }

    fn get_u64(&self, name: &[u8], device: u32) -> Option<u64> {
        let f: Symbol<FnGetU64> = self.symbol(name)?;
        let mut v = 0;
        (unsafe { f(device, &mut v) } == RSMI_STATUS_SUCCESS).then_some(v)
    }

    fn get_u64_indexed(&self, name: &[u8], device: u32, index: u32) -> Option<u64> {
        let f: Symbol<FnGetU64Indexed> = self.symbol(name)?;
        let mut v = 0;
        (unsafe { f(device, index, &mut v) } == RSMI_STATUS_SUCCESS).then_some(v)
    }

    fn get_name(&self, name: &[u8], device: u32) -> Option<String> {
        let f: Symbol<FnGetName> = self.symbol(name)?;
        read_string(|buf, len| unsafe { f(device, buf, len) })
    }

    fn get_vbios_version(&self, device: u32) -> Option<String> {
        let f: Symbol<FnGetVbios> = self.symbol(b"rsmi_dev_vbios_version_get\0")?;
        read_string(|buf, len| unsafe { f(device, buf, len as u32) })
    }

    /// Current temperature of the memory sensor, the sensor `rocm-smi` reports
    /// as "Temperature (Sensor memory)".
    fn temperature_celsius(&self, device: u32) -> Option<f64> {
        let f: Symbol<FnGetTemp> = self.symbol(b"rsmi_dev_temp_metric_get\0")?;
        let mut millidegrees = 0i64;
        let status = unsafe {
            f(
                device,
                RSMI_TEMP_TYPE_MEMORY,
                RSMI_TEMP_CURRENT,
                &mut millidegrees,
            )
        };
        (status == RSMI_STATUS_SUCCESS).then_some(millidegrees as f64 / 1000.0)
    }

    /// Current or average package power, whichever the library reports, in watts.
    fn power_watts(&self, device: u32) -> Option<f64> {
        let microwatts = match self.symbol::<FnGetPower>(b"rsmi_dev_power_get\0") {
            Some(f) => {
                let mut v = 0u64;
                let mut power_type = 0u32;
                (unsafe { f(device, &mut v, &mut power_type) } == RSMI_STATUS_SUCCESS).then_some(v)
            }
            None => self.get_u64_indexed(b"rsmi_dev_power_ave_get\0", device, 0),
        }?;
        Some(microwatts as f64 / 1e6)
    }

    fn power_cap_watts(&self, device: u32) -> Option<f64> {
        self.get_u64_indexed(b"rsmi_dev_power_cap_get\0", device, 0)
            .map(|microwatts| microwatts as f64 / 1e6)
    }

    /// The current sclk and mclk ranges as `rocm-smi` prints them, e.g. "500Mhz - 1700Mhz".
    fn clock_ranges(&self, device: u32) -> (String, String) {
        let Some(f) = self.symbol::<FnGetOdVolt>(b"rsmi_dev_od_volt_info_get\0") else {
            return Default::default();
        };
        let mut data = RsmiOdVoltFreqData::default();
        if unsafe { f(device, &mut data) } != RSMI_STATUS_SUCCESS {
            return Default::default();
        }
        let format = |range: RsmiRange| {
            if range.lower_bound == u64::MAX || range.upper_bound == u64::MAX {
                return String::new();
            }
            format!(
                "{}Mhz - {}Mhz",
                range.lower_bound / 1_000_000,
                range.upper_bound / 1_000_000
            )
        };
        (format(data.curr_sclk_range), format(data.curr_mclk_range))
    }
}

impl Drop for GpuAmd {
    fn drop(&mut self) {
        if let Some(shut_down) = self.symbol::<FnShutDown>(b"rsmi_shut_down\0") {
            unsafe { shut_down() };
        }
    }
}

/// Reads a string the library writes into a caller-provided buffer.
fn read_string(fill: impl FnOnce(*mut c_char, usize) -> RsmiStatus) -> Option<String> {
    let mut buf = [0 as c_char; 256];
    if fill(buf.as_mut_ptr(), buf.len() - 1) != RSMI_STATUS_SUCCESS {
        return None;
    }
    let value = unsafe { CStr::from_ptr(buf.as_ptr()) }
        .to_string_lossy()
        .into_owned();
    Some(value)
}

/// `rsmi_dev_perf_level_t` values as `rocm-smi` prints them.
fn perf_level_name(level: u32) -> &'static str {
    match level {
        0 => "auto",
        1 => "low",
        2 => "high",
        3 => "manual",
        4 => "stable_std",
        5 => "stable_peak",
        6 => "stable_min_mclk",
        7 => "stable_min_sclk",
        8 => "perf_determinism",
        _ => "unknown",
    }
}

/// Check if the AMD GPU driver is installed and loaded.
fn is_driver_installed() -> bool {
    // Inspired by rocm_smi_lib, see
    // https://github.com/ROCm/rocm_smi_lib/blob/6f51cd651e4116b04c2df6a2afe8859558bdba66/python_smi_tools/rocm_smi.py#L89
    std::fs::read_to_string("/sys/module/amdgpu/initstate")
        .map(|content| content.contains("live"))
        .unwrap_or(false)
}

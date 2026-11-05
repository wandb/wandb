/*
Based on https://github.com/vladkens/macmon.

MIT License

Copyright (c) 2024 vladkens

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
use crate::gpu_apple_sources::{
    IOHIDSensors, IOReport, SMC, SocInfo, cfio_get_residencies, cfio_watts, libc_ram, libc_swap,
};
use crate::metrics::MetricValue;
use crate::wandb_internal::{
    AcceleratorMetrics, AcceleratorType, AppleHostMetrics, AppleInfo, CpuMetrics,
    EnvironmentRecord, HostMetrics, SwapMetrics, SystemMetricsRecord,
};
use core_foundation::dictionary::CFDictionaryRef;
use log::warn;
use serde::Serialize;
use std::collections::HashMap;

type WithError<T> = Result<T, Box<dyn std::error::Error>>;

// const CPU_FREQ_DICE_SUBG: &str = "CPU Complex Performance States";
const CPU_FREQ_CORE_SUBG: &str = "CPU Core Performance States";
const GPU_FREQ_DICE_SUBG: &str = "GPU Performance States";

// MARK: Structs

#[derive(Debug, Default, Serialize)]
pub struct TempMetrics {
    pub cpu_temp_avg: f32, // Celsius
    pub gpu_temp_avg: f32, // Celsius
}

#[derive(Debug, Default, Serialize)]
pub struct MemMetrics {
    pub ram_total: u64,  // bytes
    pub ram_usage: u64,  // bytes
    pub swap_total: u64, // bytes
    pub swap_usage: u64, // bytes
}

#[derive(Debug, Default, Serialize)]
pub struct Metrics {
    pub temp: TempMetrics,
    pub memory: MemMetrics,
    pub ecpu_usage: (u32, f32), // freq, percent_from_max
    pub pcpu_usage: (u32, f32), // freq, percent_from_max
    pub gpu_usage: (u32, f32),  // freq, percent_from_max
    pub cpu_power: f32,         // Watts
    pub gpu_power: f32,         // Watts
    pub ane_power: f32,         // Watts
    pub all_power: f32,         // Watts
    pub sys_power: f32,         // Watts
    pub ram_power: f32,         // Watts
    pub gpu_ram_power: f32,     // Watts
}

// MARK: Helpers

pub fn zero_div<T: core::ops::Div<Output = T> + Default + PartialEq>(a: T, b: T) -> T {
    let zero: T = Default::default();
    if b == zero { zero } else { a / b }
}

fn is_valid_temp(val: f32) -> bool {
    val > 0.0 && val <= 150.0
}

fn calc_freq(item: CFDictionaryRef, freqs: &[u32]) -> (u32, f32) {
    let items = cfio_get_residencies(item); // (ns, freq)
    let (len1, len2) = (items.len(), freqs.len());

    // Bail out gracefully on unexpected data shapes:
    // - `freqs` may be empty for clusters whose pmgr DVFS table we couldn't read
    //   (e.g. the efficiency cores on Apple M5);
    // - `len1 > len2` is required because residencies carry extra leading
    //   IDLE/DOWN/OFF states that the indexing below skips.
    if len2 == 0 || len1 <= len2 {
        return (0, 0.0);
    }

    // IDLE / DOWN for CPU; OFF for GPU; DOWN only on M2?/M3 Max Chips
    let offset = match items
        .iter()
        .position(|x| x.0 != "IDLE" && x.0 != "DOWN" && x.0 != "OFF")
    {
        Some(offset) => offset,
        None => return (0, 0.0), // fully idle: no active residency states
    };

    let usage = items.iter().map(|x| x.1 as f64).skip(offset).sum::<f64>();
    let total = items.iter().map(|x| x.1 as f64).sum::<f64>();
    let count = freqs.len();

    let mut avg_freq = 0f64;
    for i in 0..count {
        if i + offset >= items.len() {
            break;
        }
        let percent = zero_div(items[i + offset].1 as _, usage);
        avg_freq += percent * freqs[i] as f64;
    }

    let usage_ratio = zero_div(usage, total);
    let min_freq = *freqs.first().unwrap() as f64;
    let max_freq = *freqs.last().unwrap() as f64;
    let from_max = (avg_freq.max(min_freq) * usage_ratio) / max_freq;

    (avg_freq as u32, from_max as f32)
}

fn calc_freq_final(items: &[(u32, f32)], freqs: &[u32]) -> (u32, f32) {
    let avg_freq = zero_div(items.iter().map(|x| x.0 as f32).sum(), items.len() as f32);
    let avg_perc = zero_div(items.iter().map(|x| x.1).sum(), items.len() as f32);
    // `freqs` can be empty when a cluster's DVFS table is unavailable (e.g. the
    // efficiency cores on Apple M5); fall back to 0 instead of panicking.
    let min_freq = freqs.first().copied().unwrap_or(0) as f32;

    (avg_freq.max(min_freq) as u32, avg_perc)
}

fn init_smc() -> WithError<(SMC, Vec<String>, Vec<String>)> {
    let mut smc = SMC::new()?;
    const FLOAT_TYPE: u32 = 1718383648; // FourCC: "flt "

    let mut cpu_sensors = Vec::new();
    let mut gpu_sensors = Vec::new();

    // Unfortunately, it is not known which keys are responsible for what.
    // Basically in the code that can be found publicly "Tp" is used for CPU and "Tg" for GPU.
    // "Tp" – performance cores, "Te" – efficiency cores
    for name in smc.read_all_keys().unwrap_or_default() {
        let is_cpu = name.starts_with("Tp") || name.starts_with("Te");
        let is_gpu = name.starts_with("Tg");
        if !is_cpu && !is_gpu {
            continue;
        }

        let key = match smc.read_key_info(&name) {
            Ok(key) => key,
            Err(_) => continue,
        };
        if key.data_size != 4 || key.data_type != FLOAT_TYPE || smc.read_val(&name).is_err() {
            continue;
        }

        if is_cpu {
            cpu_sensors.push(name);
        } else {
            gpu_sensors.push(name);
        }
    }

    Ok((smc, cpu_sensors, gpu_sensors))
}

// MARK: Sampler

pub struct Sampler {
    soc: SocInfo,
    ior: IOReport,
    hid: IOHIDSensors,
    smc: SMC,
    smc_cpu_keys: Vec<String>,
    smc_gpu_keys: Vec<String>,
}

impl Sampler {
    pub fn new() -> WithError<Self> {
        let channels = vec![
            ("Energy Model", None), // cpu/gpu/ane power
            // ("CPU Stats", Some(CPU_FREQ_DICE_SUBG)), // cpu freq by cluster
            ("CPU Stats", Some(CPU_FREQ_CORE_SUBG)), // cpu freq per core
            ("GPU Stats", Some(GPU_FREQ_DICE_SUBG)), // gpu freq
        ];

        let soc = SocInfo::new()?;
        let ior = IOReport::new(channels)?;
        let hid = IOHIDSensors::new()?;
        let (smc, smc_cpu_keys, smc_gpu_keys) = init_smc()?;

        Ok(Sampler {
            soc,
            ior,
            hid,
            smc,
            smc_cpu_keys,
            smc_gpu_keys,
        })
    }

    fn get_temp_smc(&mut self) -> WithError<TempMetrics> {
        let mut cpu_metrics = Vec::new();
        for sensor in &self.smc_cpu_keys {
            let val = self.smc.read_val(sensor)?;
            let val = f32::from_le_bytes(val.data[0..4].try_into().unwrap());
            if is_valid_temp(val) {
                cpu_metrics.push(val);
            }
        }

        let mut gpu_metrics = Vec::new();
        for sensor in &self.smc_gpu_keys {
            let val = self.smc.read_val(sensor)?;
            let val = f32::from_le_bytes(val.data[0..4].try_into().unwrap());
            if is_valid_temp(val) {
                gpu_metrics.push(val);
            }
        }

        let cpu_temp_avg = zero_div(cpu_metrics.iter().sum::<f32>(), cpu_metrics.len() as f32);
        let gpu_temp_avg = zero_div(gpu_metrics.iter().sum::<f32>(), gpu_metrics.len() as f32);

        Ok(TempMetrics {
            cpu_temp_avg,
            gpu_temp_avg,
        })
    }

    fn get_temp_hid(&mut self) -> WithError<TempMetrics> {
        let metrics = self.hid.get_metrics();

        let mut cpu_values = Vec::new();
        let mut gpu_values = Vec::new();

        for (name, value) in &metrics {
            if name.starts_with("pACC MTR Temp Sensor") || name.starts_with("eACC MTR Temp Sensor")
            {
                if is_valid_temp(*value) {
                    cpu_values.push(*value);
                }
                continue;
            }

            if name.starts_with("GPU MTR Temp Sensor") {
                if is_valid_temp(*value) {
                    gpu_values.push(*value);
                }
                continue;
            }
        }

        let cpu_temp_avg = zero_div(cpu_values.iter().sum(), cpu_values.len() as f32);
        let gpu_temp_avg = zero_div(gpu_values.iter().sum(), gpu_values.len() as f32);

        Ok(TempMetrics {
            cpu_temp_avg,
            gpu_temp_avg,
        })
    }

    fn get_temp(&mut self) -> WithError<TempMetrics> {
        // HID for M1, SMC for M2/M3
        // UPD: Looks like HID/SMC related to OS version, not to the chip (SMC available from macOS 14)
        match !self.smc_cpu_keys.is_empty() {
            true => self.get_temp_smc(),
            false => self.get_temp_hid(),
        }
    }

    fn get_mem(&mut self) -> WithError<MemMetrics> {
        let (ram_usage, ram_total) = libc_ram()?;
        let (swap_usage, swap_total) = libc_swap()?;
        Ok(MemMetrics {
            ram_total,
            ram_usage,
            swap_total,
            swap_usage,
        })
    }

    fn get_sys_power(&mut self) -> WithError<f32> {
        let val = self.smc.read_val("PSTR")?;
        let val = f32::from_le_bytes(val.data.clone().try_into().unwrap());
        Ok(val)
    }

    pub fn get_metrics(&mut self) -> WithError<Metrics> {
        let (sample, dt) = self.ior.sample_since_last();
        let mut ecpu_usages = Vec::new();
        let mut pcpu_usages = Vec::new();
        let mut rs = Metrics::default();

        for x in sample {
            if x.group == "CPU Stats" && x.subgroup == CPU_FREQ_CORE_SUBG {
                // M5 Pro and Max report their second core tier as MCPU channels.
                if x.channel.contains("ECPU") || x.channel.contains("MCPU") {
                    ecpu_usages.push(calc_freq(x.item, &self.soc.ecpu_freqs));
                    continue;
                }

                if x.channel.contains("PCPU") {
                    pcpu_usages.push(calc_freq(x.item, &self.soc.pcpu_freqs));
                    continue;
                }
            }

            if x.group == "GPU Stats" && x.subgroup == GPU_FREQ_DICE_SUBG {
                match x.channel.as_str() {
                    // Guard the `[1..]` slice: indexing an empty table panics.
                    "GPUPH" if !self.soc.gpu_freqs.is_empty() => {
                        rs.gpu_usage = calc_freq(x.item, &self.soc.gpu_freqs[1..])
                    }
                    _ => {}
                }
            }

            if x.group == "Energy Model" {
                match x.channel.as_str() {
                    "GPU Energy" => rs.gpu_power += cfio_watts(x.item, &x.unit, dt)?,
                    // "CPU Energy" for Basic / Max, "DIE_{}_CPU Energy" for Ultra
                    c if c.ends_with("CPU Energy") => {
                        rs.cpu_power += cfio_watts(x.item, &x.unit, dt)?
                    }
                    // same pattern next keys: "ANE" for Basic, "ANE0" for Max, "ANE0_{}" for Ultra
                    c if c.starts_with("ANE") => rs.ane_power += cfio_watts(x.item, &x.unit, dt)?,
                    c if c.starts_with("DRAM") => rs.ram_power += cfio_watts(x.item, &x.unit, dt)?,
                    c if c.starts_with("GPU SRAM") => {
                        rs.gpu_ram_power += cfio_watts(x.item, &x.unit, dt)?
                    }
                    _ => {}
                }
            }
        }

        rs.ecpu_usage = calc_freq_final(&ecpu_usages, &self.soc.ecpu_freqs);
        rs.pcpu_usage = calc_freq_final(&pcpu_usages, &self.soc.pcpu_freqs);
        rs.all_power = rs.cpu_power + rs.gpu_power + rs.ane_power;

        rs.memory = self.get_mem()?;
        rs.temp = self.get_temp()?;

        rs.sys_power = match self.get_sys_power() {
            Ok(val) => val.max(rs.all_power),
            Err(_) => 0.0,
        };

        Ok(rs)
    }

    /// Getter for the `soc` field
    pub fn get_soc_info(&self) -> &SocInfo {
        &self.soc
    }
}

use std::sync::mpsc::{Receiver, Sender, channel};
use tokio::sync::oneshot;

// Define a specific error type for our sampler
#[derive(Debug)]
pub struct SamplerError(String);

impl std::fmt::Display for SamplerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Sampler error: {}", self.0)
    }
}

impl std::error::Error for SamplerError {}

/// Commands that can be sent to the sampler thread via the command channel.
enum SamplerCommand {
    GetMetrics(oneshot::Sender<Result<Metrics, SamplerError>>),
    GetSockInfo(oneshot::Sender<SocInfo>),
    Shutdown,
}

/// A thread-safe wrapper around the Sampler struct.
///
/// This struct is intended to be used in a multi-threaded environment (such as
/// a Tokio async runtime), where the sampler is running in a separate thread and
/// the main thread needs to periodically query the sampler for metrics.
pub struct ThreadSafeSampler {
    command_sender: Sender<SamplerCommand>,
}

impl ThreadSafeSampler {
    pub fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let (command_sender, command_receiver) = channel();

        std::thread::spawn(move || {
            sampler_thread(command_receiver);
        });

        Ok(Self { command_sender })
    }

    /// Get the latest metrics from the sampler.
    ///
    /// Works by sending a command to the sampler thread and waiting for the response.
    pub async fn get_metrics(&self) -> Result<Metrics, Box<dyn std::error::Error>> {
        let (response_sender, response_receiver) = oneshot::channel();
        self.command_sender
            .send(SamplerCommand::GetMetrics(response_sender))
            .map_err(|e| Box::new(SamplerError(e.to_string())) as Box<dyn std::error::Error>)?;

        response_receiver
            .await
            .map_err(|e| Box::new(SamplerError(e.to_string())) as Box<dyn std::error::Error>)?
            .map_err(|e| Box::new(e) as Box<dyn std::error::Error>)
    }

    /// Get the soc info from the sampler.
    ///
    /// Works by sending a command to the sampler thread and waiting for the response.
    pub async fn get_soc_info(&self) -> Result<SocInfo, Box<dyn std::error::Error>> {
        let (response_sender, response_receiver) = oneshot::channel();
        self.command_sender
            .send(SamplerCommand::GetSockInfo(response_sender))
            .map_err(|e| Box::new(SamplerError(e.to_string())) as Box<dyn std::error::Error>)?;

        response_receiver
            .await
            .map_err(|e| Box::new(SamplerError(e.to_string())) as Box<dyn std::error::Error>)
    }

    /// The static facts of a sample, under `_` keys for the metadata.
    pub fn metadata_metrics(
        &self,
        metrics: Metrics,
        soc_info: SocInfo,
    ) -> Vec<(String, MetricValue)> {
        let mut result = Vec::new();

        // Static metadata.
        result.push((
            "_apple.mac_model".to_string(),
            MetricValue::String(soc_info.mac_model),
        ));
        result.push((
            "_apple.chip_name".to_string(),
            MetricValue::String(soc_info.chip_name),
        ));
        result.push((
            "_apple.ecpu_cores".to_string(),
            MetricValue::Int(soc_info.ecpu_cores as i64),
        ));
        result.push((
            "_apple.pcpu_cores".to_string(),
            MetricValue::Int(soc_info.pcpu_cores as i64),
        ));
        result.push((
            "_apple.gpu_cores".to_string(),
            MetricValue::Int(soc_info.gpu_cores as i64),
        ));
        result.push((
            "_apple.memory_gb".to_string(),
            MetricValue::Int(soc_info.memory_gb as i64),
        ));

        result.push((
            "_swap.total".to_string(),
            MetricValue::Int(metrics.memory.swap_total as i64),
        ));

        result.push((
            "_ram.total".to_string(),
            MetricValue::Int(metrics.memory.ram_total as i64),
        ));

        result
    }

    /// The readings of a sample as typed record fields. A reading that is not
    /// finite is left out, and so are memory and swap use of zero.
    pub fn record(&self, metrics: &Metrics) -> SystemMetricsRecord {
        let finite = |value: f64| value.is_finite().then_some(value);
        let nonzero = |value: u64| (value > 0).then_some(value);
        let ratio = |part: u64, total: u64| finite(part as f64 / total as f64);
        let (ecpu_freq, ecpu_ratio) = metrics.ecpu_usage;
        let (pcpu_freq, pcpu_ratio) = metrics.pcpu_usage;
        let (gpu_freq, gpu_ratio) = metrics.gpu_usage;
        let memory = &metrics.memory;

        SystemMetricsRecord {
            host: Some(HostMetrics {
                cpu: Some(CpuMetrics {
                    temperature_c: finite(metrics.temp.cpu_temp_avg as f64),
                    ..Default::default()
                }),
                swap: Some(SwapMetrics {
                    used_bytes: nonzero(memory.swap_usage),
                    used_ratio: ratio(memory.swap_usage, memory.swap_total),
                }),
                apple: Some(AppleHostMetrics {
                    memory_used_bytes: nonzero(memory.ram_usage),
                    memory_used_ratio: ratio(memory.ram_usage, memory.ram_total),
                    ecpu_utilization_ratio: finite(ecpu_ratio as f64),
                    ecpu_frequency_hz: (ecpu_freq > 0).then_some(ecpu_freq as f64 * 1e6),
                    pcpu_utilization_ratio: finite(pcpu_ratio as f64),
                    pcpu_frequency_hz: (pcpu_freq > 0).then_some(pcpu_freq as f64 * 1e6),
                    cpu_power_w: finite(metrics.cpu_power as f64),
                    system_power_w: finite(metrics.sys_power as f64),
                }),
                ..Default::default()
            }),
            accelerators: vec![
                AcceleratorMetrics {
                    r#type: AcceleratorType::AppleGpu as i32,
                    source: "ioreport".to_string(),
                    utilization_ratio: finite(gpu_ratio as f64),
                    temperature_c: finite(metrics.temp.gpu_temp_avg as f64),
                    power_w: finite(metrics.gpu_power as f64),
                    clock_hz: (gpu_freq > 0).then_some(gpu_freq as f64 * 1e6),
                    ..Default::default()
                },
                AcceleratorMetrics {
                    r#type: AcceleratorType::AppleAne as i32,
                    source: "ioreport".to_string(),
                    power_w: finite(metrics.ane_power as f64),
                    ..Default::default()
                },
            ],
            ..Default::default()
        }
    }

    pub fn get_metadata(&self, samples: &HashMap<String, &MetricValue>) -> EnvironmentRecord {
        let mut gpu_apple = AppleInfo {
            ..Default::default()
        };
        if let Some(&MetricValue::String(s)) = samples.get("_apple.chip_name") {
            gpu_apple.name = s.clone();
        }
        if let Some(&MetricValue::String(s)) = samples.get("_apple.mac_model") {
            gpu_apple.mac_model = s.clone();
        }
        if let Some(&value) = samples.get("_apple.ecpu_cores") {
            if let MetricValue::Int(ecpu_cores) = value {
                gpu_apple.ecpu_cores = *ecpu_cores as u32;
            }
        }
        if let Some(&value) = samples.get("_apple.pcpu_cores") {
            if let MetricValue::Int(pcpu_cores) = value {
                gpu_apple.pcpu_cores = *pcpu_cores as u32;
            }
        }
        if let Some(&value) = samples.get("_apple.gpu_cores") {
            if let MetricValue::Int(gpu_cores) = value {
                gpu_apple.gpu_cores = *gpu_cores as u32;
            }
        }
        if let Some(&value) = samples.get("_apple.memory_gb") {
            if let MetricValue::Int(memory_gb) = value {
                gpu_apple.memory_gb = *memory_gb as u32;
            }
        }
        if let Some(&value) = samples.get("_swap.total") {
            if let MetricValue::Int(swap_total) = value {
                gpu_apple.swap_total_bytes = *swap_total as u64;
            }
        }
        if let Some(&value) = samples.get("_ram.total") {
            if let MetricValue::Int(ram_total) = value {
                gpu_apple.ram_total_bytes = *ram_total as u64;
            }
        }
        EnvironmentRecord {
            apple: Some(gpu_apple),
            ..Default::default()
        }
    }
}

impl Drop for ThreadSafeSampler {
    fn drop(&mut self) {
        let _ = self.command_sender.send(SamplerCommand::Shutdown);
    }
}

fn sampler_thread(receiver: Receiver<SamplerCommand>) {
    // Catch panics during construction. Without this, a panic here kills the
    // thread before it ever serves a request, so every `get_metrics()` call sees
    // "channel closed" with no indication of the real cause.
    let mut sampler = match std::panic::catch_unwind(Sampler::new) {
        Ok(Ok(s)) => s,
        Ok(Err(e)) => {
            warn!("Failed to create Sampler: {}", e);
            return;
        }
        Err(_) => {
            warn!("Panic while creating Apple sampler; Apple metrics disabled");
            return;
        }
    };

    for cmd in receiver {
        match cmd {
            SamplerCommand::GetMetrics(response) => {
                // Catch panics from a single sample so one bad reading can't
                // permanently kill the sampler thread (and with it all metrics).
                let result = match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    sampler.get_metrics()
                })) {
                    Ok(result) => result.map_err(|e| SamplerError(e.to_string())),
                    Err(_) => Err(SamplerError("panic while sampling Apple metrics".into())),
                };
                let _ = response.send(result);
            }
            SamplerCommand::GetSockInfo(response) => {
                let result = sampler.get_soc_info().clone();
                let _ = response.send(result);
            }
            SamplerCommand::Shutdown => break,
        }
    }
}

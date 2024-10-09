/*
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
use core_foundation::dictionary::CFDictionaryRef;

use crate::gpu_apple_sources::{
    cfio_get_residencies, cfio_watts, libc_ram, libc_swap, IOHIDSensors, IOReport, SocInfo, SMC,
};
use crate::metrics::MetricValue;

type WithError<T> = Result<T, Box<dyn std::error::Error>>;

// const CPU_FREQ_DICE_SUBG: &str = "CPU Complex Performance States";
const CPU_FREQ_CORE_SUBG: &str = "CPU Core Performance States";
const GPU_FREQ_DICE_SUBG: &str = "GPU Performance States";

// MARK: Structs

#[derive(Debug, Default)]
pub struct TempMetrics {
    pub cpu_temp_avg: f32, // Celsius
    pub gpu_temp_avg: f32, // Celsius
}

#[derive(Debug, Default)]
pub struct MemMetrics {
    pub ram_total: u64,  // bytes
    pub ram_usage: u64,  // bytes
    pub swap_total: u64, // bytes
    pub swap_usage: u64, // bytes
}

#[derive(Debug, Default)]
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
}

// MARK: Helpers

fn zero_div<T: core::ops::Div<Output = T> + Default + PartialEq>(a: T, b: T) -> T {
    let zero: T = Default::default();
    return if b == zero { zero } else { a / b };
}

fn calc_freq(item: CFDictionaryRef, freqs: &Vec<u32>) -> (u32, f32) {
    let residencies = cfio_get_residencies(item); // (ns, freq)
    let (len1, len2) = (residencies.len(), freqs.len());
    assert!(len1 > len2, "cacl_freq invalid data: {} vs {}", len1, len2); // todo?

    // first is IDLE for CPU and OFF for GPU
    let usage = residencies.iter().map(|x| x.1 as f64).skip(1).sum::<f64>();
    let total = residencies.iter().map(|x| x.1 as f64).sum::<f64>();
    let count = freqs.len();
    // println!("{:?}", residencies);

    let mut freq = 0f64;
    for i in 0..count {
        let percent = zero_div(residencies[i + 1].1 as _, usage);
        freq += percent * freqs[i] as f64;
    }

    let percent = zero_div(usage, total);
    let min_freq = freqs.first().unwrap().clone() as f64;
    let max_freq = freqs.last().unwrap().clone() as f64;
    let from_max = (freq.max(min_freq) * percent) / max_freq;

    (freq as u32, from_max as f32)
}

fn calc_freq_final(items: &Vec<(u32, f32)>, freqs: &Vec<u32>) -> (u32, f32) {
    let avg_freq = zero_div(items.iter().map(|x| x.0 as f32).sum(), items.len() as f32);
    let avg_perc = zero_div(items.iter().map(|x| x.1 as f32).sum(), items.len() as f32);
    let min_freq = freqs.first().unwrap().clone() as f32;

    (avg_freq.max(min_freq) as u32, avg_perc)
}

fn init_smc() -> WithError<(SMC, Vec<String>, Vec<String>)> {
    let mut smc = SMC::new()?;

    let mut cpu_sensors = Vec::new();
    let mut gpu_sensors = Vec::new();

    let names = smc.read_all_keys().unwrap_or(vec![]);
    for name in &names {
        let key = match smc.read_key_info(&name) {
            Ok(key) => key,
            Err(_) => continue,
        };

        if key.data_size != 4 || key.data_type != 1718383648 {
            continue;
        }

        let _ = match smc.read_val(&name) {
            Ok(val) => val,
            Err(_) => continue,
        };

        // Unfortunately, it is not known which keys are responsible for what.
        // Basically in the code that can be found publicly "Tp" is used for CPU and "Tg" for GPU.

        match name {
            name if name.starts_with("Tp") => cpu_sensors.push(name.clone()),
            name if name.starts_with("Tg") => gpu_sensors.push(name.clone()),
            _ => (),
        }
    }

    // println!("{} {}", cpu_sensors.len(), gpu_sensors.len());
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
            cpu_metrics.push(val);
        }

        let mut gpu_metrics = Vec::new();
        for sensor in &self.smc_gpu_keys {
            let val = self.smc.read_val(sensor)?;
            let val = f32::from_le_bytes(val.data[0..4].try_into().unwrap());
            gpu_metrics.push(val);
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
                // println!("{}: {}", name, value);
                cpu_values.push(*value);
                continue;
            }

            if name.starts_with("GPU MTR Temp Sensor") {
                // println!("{}: {}", name, value);
                gpu_values.push(*value);
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
        match self.smc_cpu_keys.len() > 0 {
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

    pub fn get_metrics(&mut self, duration: u64) -> WithError<Metrics> {
        let mut rs = Metrics::default();

        let mut ecpu_usages = Vec::new();
        let mut pcpu_usages = Vec::new();

        for x in self.ior.get_sample(duration) {
            if x.group == "CPU Stats" && x.subgroup == CPU_FREQ_CORE_SUBG {
                if x.channel.contains("ECPU") {
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
                    "GPUPH" => rs.gpu_usage = calc_freq(x.item, &self.soc.gpu_freqs[1..].to_vec()),
                    _ => {}
                }
            }

            if x.group == "Energy Model" {
                match x.channel.as_str() {
                    "CPU Energy" => rs.cpu_power += cfio_watts(x.item, &x.unit, duration)?,
                    "GPU Energy" => rs.gpu_power += cfio_watts(x.item, &x.unit, duration)?,
                    c if c.starts_with("ANE") => {
                        rs.ane_power += cfio_watts(x.item, &x.unit, duration)?
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
}

use std::sync::mpsc::{channel, Receiver, Sender};
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

enum SamplerCommand {
    GetMetrics(oneshot::Sender<Result<Metrics, SamplerError>>),
    Shutdown,
}

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

    pub fn metrics_to_vec(metrics: Metrics) -> Vec<(String, MetricValue)> {
        let mut result = Vec::new();

        // Helper function to safely add metrics
        fn add_metric(vec: &mut Vec<(&'static str, f64)>, key: &'static str, value: f64) {
            // Only add non-NaN, non-infinite values
            if value.is_finite() {
                vec.push((key, value));
            }
        }

        // Helper function for optional integer metrics
        fn add_optional_int(vec: &mut Vec<(&'static str, f64)>, key: &'static str, value: u64) {
            if value > 0 {
                add_metric(vec, key, value as f64);
            }
        }

        // Temperature metrics
        if metrics.temp.cpu_temp_avg.is_finite() {
            add_metric(
                &mut result,
                "cpu.avg_temp",
                metrics.temp.cpu_temp_avg as f64,
            );
        }
        if metrics.temp.gpu_temp_avg.is_finite() {
            add_metric(&mut result, "gpu.0.temp", metrics.temp.gpu_temp_avg as f64);
        }

        // Memory metrics
        add_optional_int(&mut result, "memory.total", metrics.memory.ram_total);
        add_optional_int(&mut result, "memory.used", metrics.memory.ram_usage);
        add_optional_int(&mut result, "swap.total", metrics.memory.swap_total);
        add_optional_int(&mut result, "swap.used", metrics.memory.swap_usage);

        // CPU metrics
        let (ecpu_freq, ecpu_percent) = metrics.ecpu_usage;
        if ecpu_freq > 0 {
            add_metric(&mut result, "cpu.ecpu_freq", ecpu_freq as f64);
        }
        if ecpu_percent.is_finite() {
            add_metric(&mut result, "cpu.ecpu_percent", ecpu_percent as f64);
        }

        let (pcpu_freq, pcpu_percent) = metrics.pcpu_usage;
        if pcpu_freq > 0 {
            add_metric(&mut result, "cpu.pcpu_freq", pcpu_freq as f64);
        }
        if pcpu_percent.is_finite() {
            add_metric(&mut result, "cpu.pcpu_percent", pcpu_percent as f64);
        }

        // GPU metrics
        let (gpu_freq, gpu_percent) = metrics.gpu_usage;
        if gpu_freq > 0 {
            add_metric(&mut result, "gpu.0.freq", gpu_freq as f64);
        }
        if gpu_percent.is_finite() {
            add_metric(&mut result, "gpu.0.gpu", gpu_percent as f64);
        }

        // Power metrics
        if metrics.cpu_power.is_finite() {
            add_metric(&mut result, "cpu.powerWatts", metrics.cpu_power as f64);
        }
        if metrics.gpu_power.is_finite() {
            add_metric(&mut result, "gpu.0.powerWatts", metrics.gpu_power as f64);
        }
        if metrics.ane_power.is_finite() {
            add_metric(&mut result, "ane.power", metrics.ane_power as f64);
        }
        if metrics.sys_power.is_finite() {
            add_metric(&mut result, "system.powerWatts", metrics.sys_power as f64);
        }

        result
            .into_iter()
            .map(|(key, value)| (key.to_string(), MetricValue::Float(value)))
            .collect()
    }
}

impl Drop for ThreadSafeSampler {
    fn drop(&mut self) {
        let _ = self.command_sender.send(SamplerCommand::Shutdown);
    }
}

fn sampler_thread(receiver: Receiver<SamplerCommand>) {
    let mut sampler = match Sampler::new() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Failed to create Sampler: {}", e);
            return;
        }
    };

    for cmd in receiver {
        match cmd {
            SamplerCommand::GetMetrics(response) => {
                let result = sampler
                    .get_metrics(1)
                    .map_err(|e| SamplerError(e.to_string()));
                let _ = response.send(result);
            }
            SamplerCommand::Shutdown => break,
        }
    }
}

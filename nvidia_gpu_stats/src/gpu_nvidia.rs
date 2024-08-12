use crate::metrics::Metrics;
use nvml_wrapper::enum_wrappers::device::{Clock, TemperatureSensor};
use nvml_wrapper::error::NvmlError;
use nvml_wrapper::{Device, Nvml};
use sysinfo::{Pid, System};

pub struct NvidiaGpu {
    nvml: Nvml,
}

impl NvidiaGpu {
    pub fn new() -> Result<Self, NvmlError> {
        Ok(NvidiaGpu {
            nvml: Nvml::init()?,
        })
    }

    fn get_cuda_version(&self) -> Result<String, NvmlError> {
        let cuda_version = self.nvml.sys_cuda_driver_version()?;
        Ok(format!(
            "{}.{}",
            nvml_wrapper::cuda_driver_version_major(cuda_version),
            nvml_wrapper::cuda_driver_version_minor(cuda_version)
        ))
    }

    fn gpu_in_use_by_process(&self, device: &Device, pid: i32) -> bool {
        let our_pids: Vec<i32> = std::iter::once(pid)
            .chain(self.get_child_pids(pid))
            .collect();

        let compute_processes = device.running_compute_processes().unwrap_or_default();
        let graphics_processes = device.running_graphics_processes().unwrap_or_default();

        let device_pids: Vec<i32> = compute_processes
            .iter()
            .chain(graphics_processes.iter())
            .map(|p| p.pid as i32)
            .collect();

        our_pids.iter().any(|&p| device_pids.contains(&p))
    }

    fn get_child_pids(&self, pid: i32) -> Vec<i32> {
        let mut sys = System::new_all();
        sys.refresh_all();

        sys.processes()
            .values()
            .filter(|process| process.parent() == Some(Pid::from(pid as usize)))
            .map(|process| process.pid().as_u32() as i32)
            .collect()
    }

    pub fn sample_metrics(&self, metrics: &mut Metrics, pid: i32) -> Result<(), NvmlError> {
        let cuda_version = self.get_cuda_version()?;
        metrics.add_metric("cuda_version", cuda_version);

        let device_count = self.nvml.device_count()?;
        metrics.add_metric("_gpu.count", device_count);

        for di in 0..device_count {
            let device = self.nvml.device_by_index(di)?;
            let gpu_in_use = self.gpu_in_use_by_process(&device, pid);

            let utilization = device.utilization_rates()?;
            metrics.add_metric(&format!("gpu.{}.gpu", di), utilization.gpu);
            metrics.add_metric(&format!("gpu.{}.memory", di), utilization.memory);

            if gpu_in_use {
                metrics.add_metric(&format!("gpu.process.{}.gpu", di), utilization.gpu);
                metrics.add_metric(&format!("gpu.process.{}.memory", di), utilization.memory);
            }

            let memory_info = device.memory_info()?;
            metrics.add_metric(&format!("_gpu.{}.memoryTotal", di), memory_info.total);
            let memory_allocated = (memory_info.used as f64 / memory_info.total as f64) * 100.0;
            metrics.add_metric(&format!("gpu.{}.memoryAllocated", di), memory_allocated);
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

            let temperature = device.temperature(TemperatureSensor::Gpu)?;
            metrics.add_metric(&format!("gpu.{}.temp", di), temperature);
            if gpu_in_use {
                metrics.add_metric(&format!("gpu.process.{}.temp", di), temperature);
            }

            let power_usage = device.power_usage()? as f64 / 1000.0;
            metrics.add_metric(&format!("gpu.{}.powerWatts", di), power_usage);
            if gpu_in_use {
                metrics.add_metric(&format!("gpu.process.{}.powerWatts", di), power_usage);
            }

            if let Ok(power_limit) = device.enforced_power_limit() {
                let power_limit = power_limit as f64 / 1000.0;
                metrics.add_metric(&format!("gpu.{}.enforcedPowerLimitWatts", di), power_limit);
                let power_percent = (power_usage / power_limit) * 100.0;
                metrics.add_metric(&format!("gpu.{}.powerPercent", di), power_percent);

                if gpu_in_use {
                    metrics.add_metric(
                        &format!("gpu.process.{}.enforcedPowerLimitWatts", di),
                        power_limit,
                    );
                    metrics.add_metric(&format!("gpu.process.{}.powerPercent", di), power_percent);
                }
            }

            let name = device.name()?;
            metrics.add_metric(&format!("_gpu.{}.name", di), name);

            let brand = device.brand()?;
            metrics.add_metric(&format!("gpu.{}.brand", di), format!("{:?}", brand));

            if let Ok(fan_speed) = device.fan_speed(0) {
                metrics.add_metric(&format!("gpu.{}.fanSpeed", di), fan_speed);
            }

            if let Ok(encoder_util) = device.encoder_utilization() {
                metrics.add_metric(
                    &format!("_gpu.{}.encoderUtilization", di),
                    encoder_util.utilization,
                );
            }

            let graphics_clock = device.clock_info(Clock::Graphics)?;
            metrics.add_metric(&format!("_gpu.{}.graphicsClock", di), graphics_clock);

            let mem_clock = device.clock_info(Clock::Memory)?;
            metrics.add_metric(&format!("_gpu.{}.memoryClock", di), mem_clock);

            let link_gen = device.current_pcie_link_gen()?;
            metrics.add_metric(&format!("_gpu.{}.pcieLinkGen", di), link_gen);

            if let Ok(link_speed) = device.pcie_link_speed().map(u64::from).map(|x| x * 1000000) {
                metrics.add_metric(&format!("_gpu.{}.pcieLinkSpeed", di), link_speed);
            }

            let link_width = device.current_pcie_link_width()?;
            metrics.add_metric(&format!("_gpu.{}.pcieLinkWidth", di), link_width);

            let max_link_gen = device.max_pcie_link_gen()?;
            metrics.add_metric(&format!("_gpu.{}.maxPcieLinkGen", di), max_link_gen);

            let max_link_width = device.max_pcie_link_width()?;
            metrics.add_metric(&format!("_gpu.{}.maxPcieLinkWidth", di), max_link_width);

            let cuda_cores = device.num_cores()?;
            metrics.add_metric(&format!("_gpu.{}.cudaCores", di), cuda_cores);

            let architecture = device.architecture()?;
            metrics.add_metric(
                &format!("_gpu.{}.architecture", di),
                format!("{:?}", architecture),
            );
        }

        Ok(())
    }

    pub fn shutdown(self) -> Result<(), NvmlError> {
        self.nvml.shutdown()
    }
}

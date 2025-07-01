//! GPU monitor implementations for different platforms and vendors.

use crate::metrics;
use crate::wandb_internal::EnvironmentRecord;
use log::{debug, warn};
use std::collections::HashMap;

/// Trait for GPU monitors to provide a uniform interface
#[async_trait::async_trait]
pub trait GpuMonitor: Send + Sync {
    async fn collect_metrics(
        &self,
        pid: i32,
        gpu_device_ids: Option<Vec<i32>>,
    ) -> Result<Vec<(String, metrics::MetricValue)>, Box<dyn std::error::Error>>;

    async fn collect_metadata(
        &self,
        samples: &HashMap<String, &metrics::MetricValue>,
    ) -> EnvironmentRecord;

    fn shutdown(&self) {}
}

/// Container for all GPU monitors
pub struct GpuMonitors {
    monitors: Vec<Box<dyn GpuMonitor>>,
}

impl GpuMonitors {
    pub fn new(enable_dcgm_profiling: bool) -> Self {
        let mut monitors: Vec<Box<dyn GpuMonitor>> = Vec::new();

        // Add platform-specific monitors
        #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
        {
            if let Some(monitor) = AppleGpuMonitor::new() {
                monitors.push(Box::new(monitor));
            }
        }

        #[cfg(any(target_os = "linux", target_os = "windows"))]
        {
            if let Some(monitor) = NvidiaGpuMonitor::new() {
                monitors.push(Box::new(monitor));
            }
        }

        #[cfg(target_os = "linux")]
        {
            if enable_dcgm_profiling {
                if let Some(monitor) = DcgmGpuMonitor::new() {
                    monitors.push(Box::new(monitor));
                }
            }

            if let Some(monitor) = AmdGpuMonitor::new() {
                monitors.push(Box::new(monitor));
            }
        }

        Self { monitors }
    }

    pub async fn collect_metrics(
        &self,
        pid: i32,
        gpu_device_ids: Option<Vec<i32>>,
    ) -> Vec<(String, metrics::MetricValue)> {
        let mut all_metrics = Vec::new();

        for monitor in &self.monitors {
            match monitor.collect_metrics(pid, gpu_device_ids.clone()).await {
                Ok(metrics) => all_metrics.extend(metrics),
                Err(e) => warn!("Failed to collect metrics: {}", e),
            }
        }

        all_metrics
    }

    pub async fn collect_metadata(
        &self,
        samples: &HashMap<String, &metrics::MetricValue>,
    ) -> EnvironmentRecord {
        let mut metadata = EnvironmentRecord::default();

        for monitor in &self.monitors {
            let monitor_metadata = monitor.collect_metadata(samples).await;
            if monitor_metadata.gpu_count > 0 {
                metadata.gpu_count = monitor_metadata.gpu_count;
                metadata.gpu_type = monitor_metadata.gpu_type.clone();
            }
            if !monitor_metadata.cuda_version.is_empty() {
                metadata.cuda_version = monitor_metadata.cuda_version.clone();
            }
            metadata.gpu_nvidia.extend(monitor_metadata.gpu_nvidia);
            metadata.gpu_amd.extend(monitor_metadata.gpu_amd);
            metadata.apple = monitor_metadata.apple;
        }

        metadata
    }

    pub fn shutdown(&self) {
        for monitor in &self.monitors {
            monitor.shutdown();
        }
    }
}

// ===== Apple GPU Monitor =====
#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
use crate::gpu_apple;

#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
struct AppleGpuMonitor {
    sampler: gpu_apple::ThreadSafeSampler,
}

#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
impl AppleGpuMonitor {
    fn new() -> Option<Self> {
        match gpu_apple::ThreadSafeSampler::new() {
            Ok(sampler) => {
                debug!("Successfully initialized Apple GPU sampler");
                Some(Self { sampler })
            }
            Err(e) => {
                warn!("Failed to initialize Apple GPU sampler: {}", e);
                None
            }
        }
    }
}

#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
#[async_trait::async_trait]
impl GpuMonitor for AppleGpuMonitor {
    async fn collect_metrics(
        &self,
        _pid: i32,
        _gpu_device_ids: Option<Vec<i32>>,
    ) -> Result<Vec<(String, metrics::MetricValue)>, Box<dyn std::error::Error>> {
        let apple_stats = self.sampler.get_metrics().await?;
        Ok(self.sampler.metrics_to_vec(apple_stats))
    }

    async fn collect_metadata(
        &self,
        samples: &HashMap<String, &metrics::MetricValue>,
    ) -> EnvironmentRecord {
        self.sampler.get_metadata(samples)
    }
}

// ===== Nvidia GPU Monitor =====
#[cfg(any(target_os = "linux", target_os = "windows"))]
use crate::gpu_nvidia;

#[cfg(any(target_os = "linux", target_os = "windows"))]
struct NvidiaGpuMonitor {
    gpu: tokio::sync::Mutex<gpu_nvidia::NvidiaGpu>,
}

#[cfg(any(target_os = "linux", target_os = "windows"))]
impl NvidiaGpuMonitor {
    fn new() -> Option<Self> {
        match gpu_nvidia::NvidiaGpu::new() {
            Ok(gpu) => {
                debug!("Successfully initialized NVIDIA GPU monitoring");
                Some(Self {
                    gpu: tokio::sync::Mutex::new(gpu),
                })
            }
            Err(e) => {
                debug!("Failed to initialize NVIDIA GPU monitoring: {}", e);
                None
            }
        }
    }
}

#[cfg(any(target_os = "linux", target_os = "windows"))]
#[async_trait::async_trait]
impl GpuMonitor for NvidiaGpuMonitor {
    async fn collect_metrics(
        &self,
        pid: i32,
        gpu_device_ids: Option<Vec<i32>>,
    ) -> Result<Vec<(String, metrics::MetricValue)>, Box<dyn std::error::Error>> {
        Ok(self.gpu.lock().await.get_metrics(pid, gpu_device_ids)?)
    }

    async fn collect_metadata(
        &self,
        samples: &HashMap<String, &metrics::MetricValue>,
    ) -> EnvironmentRecord {
        let mut metadata = EnvironmentRecord::default();
        let nvidia_metadata = self.gpu.lock().await.get_metadata(samples);

        if nvidia_metadata.gpu_count > 0 {
            metadata.gpu_count = nvidia_metadata.gpu_count;
            metadata.gpu_type = nvidia_metadata.gpu_type;
            metadata.cuda_version = nvidia_metadata.cuda_version;
            metadata.gpu_nvidia = nvidia_metadata.gpu_nvidia;
        }

        metadata
    }
}

// ===== DCGM GPU Monitor =====
#[cfg(target_os = "linux")]
use crate::gpu_nvidia_dcgm;

#[cfg(target_os = "linux")]
struct DcgmGpuMonitor {
    client: gpu_nvidia_dcgm::DcgmClient,
}

#[cfg(target_os = "linux")]
impl DcgmGpuMonitor {
    fn new() -> Option<Self> {
        match gpu_nvidia_dcgm::DcgmClient::new() {
            Ok(client) => {
                debug!("Successfully initialized NVIDIA GPU DCGM monitoring client.");
                Some(Self { client })
            }
            Err(e) => {
                debug!("Failed to initialize NVIDIA GPU DCGM monitoring: {}", e);
                None
            }
        }
    }
}

#[cfg(target_os = "linux")]
#[async_trait::async_trait]
impl GpuMonitor for DcgmGpuMonitor {
    async fn collect_metrics(
        &self,
        _pid: i32,
        _gpu_device_ids: Option<Vec<i32>>,
    ) -> Result<Vec<(String, metrics::MetricValue)>, Box<dyn std::error::Error>> {
        Ok(self.client.get_metrics().await?)
    }

    async fn collect_metadata(
        &self,
        _samples: &HashMap<String, &metrics::MetricValue>,
    ) -> EnvironmentRecord {
        EnvironmentRecord::default()
    }

    fn shutdown(&self) {
        log::debug!("Signaling DCGM worker thread to shut down.");
        self.client.shutdown();
    }
}

// ===== AMD GPU Monitor =====
#[cfg(target_os = "linux")]
use crate::gpu_amd;

#[cfg(target_os = "linux")]
struct AmdGpuMonitor {
    gpu: gpu_amd::GpuAmd,
}

#[cfg(target_os = "linux")]
impl AmdGpuMonitor {
    fn new() -> Option<Self> {
        gpu_amd::GpuAmd::new().map(|gpu| {
            debug!("Successfully initialized AMD GPU monitoring");
            Self { gpu }
        })
    }
}

#[cfg(target_os = "linux")]
#[async_trait::async_trait]
impl GpuMonitor for AmdGpuMonitor {
    async fn collect_metrics(
        &self,
        _pid: i32,
        _gpu_device_ids: Option<Vec<i32>>,
    ) -> Result<Vec<(String, metrics::MetricValue)>, Box<dyn std::error::Error>> {
        Ok(self.gpu.get_metrics()?)
    }

    async fn collect_metadata(
        &self,
        _samples: &HashMap<String, &metrics::MetricValue>,
    ) -> EnvironmentRecord {
        let mut metadata = EnvironmentRecord::default();

        if let Ok(amd_metadata) = self.gpu.get_metadata() {
            if amd_metadata.gpu_count > 0 {
                metadata.gpu_count = amd_metadata.gpu_count;
                metadata.gpu_type = amd_metadata.gpu_type;
                metadata.gpu_amd = amd_metadata.gpu_amd;
            }
        }

        metadata
    }
}

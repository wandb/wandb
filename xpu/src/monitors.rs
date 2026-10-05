//! Collectors for each hardware platform and vendor.

use crate::metrics::{self, Sample};
use crate::wandb_internal::EnvironmentRecord;
use log::{debug, warn};
use std::collections::HashMap;

/// A source of metrics for one kind of hardware.
///
/// A collector reads every device it knows about; which of them a client
/// sees is decided when its record is built.
#[async_trait::async_trait]
pub trait Collector: Send + Sync {
    async fn collect_metrics(&self) -> Result<Sample, Box<dyn std::error::Error>>;

    async fn collect_metadata(
        &self,
        samples: &HashMap<String, &metrics::MetricValue>,
    ) -> EnvironmentRecord;

    fn shutdown(&self) {}
}

/// Every collector available on this machine.
pub struct Collectors {
    collectors: Vec<Box<dyn Collector>>,
}

impl Collectors {
    #[allow(unused_variables)] // used only on linux
    pub fn new(enable_dcgm_profiling: bool) -> Self {
        let mut collectors: Vec<Box<dyn Collector>> = Vec::new();

        // Add platform-specific collectors
        #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
        {
            if let Some(collector) = AppleGpuMonitor::new() {
                collectors.push(Box::new(collector));
            }
        }

        #[cfg(any(target_os = "linux", target_os = "windows"))]
        {
            if let Some(collector) = NvidiaGpuMonitor::new() {
                collectors.push(Box::new(collector));
            }
        }

        #[cfg(target_os = "linux")]
        {
            if enable_dcgm_profiling {
                if let Some(collector) = DcgmGpuMonitor::new() {
                    collectors.push(Box::new(collector));
                }
            }

            if let Some(collector) = AmdGpuMonitor::new() {
                collectors.push(Box::new(collector));
            }

            if let Some(collector) = tpu_libtpu::TpuMonitor::new() {
                collectors.push(Box::new(collector));
            }
        }

        Self { collectors }
    }

    /// One pass over every collector.
    pub async fn collect_metrics(&self) -> Sample {
        let mut sample = Sample::default();

        for collector in &self.collectors {
            match collector.collect_metrics().await {
                Ok(part) => {
                    sample.metrics.extend(part.metrics);
                    sample.gpu_pids.extend(part.gpu_pids);
                }
                Err(e) => warn!("Failed to collect metrics: {}", e),
            }
        }

        sample
    }

    pub async fn collect_metadata(
        &self,
        samples: &HashMap<String, &metrics::MetricValue>,
    ) -> EnvironmentRecord {
        let mut metadata = EnvironmentRecord::default();

        for collector in &self.collectors {
            let collector_metadata = collector.collect_metadata(samples).await;
            if collector_metadata.gpu_count > 0 {
                metadata.gpu_count = collector_metadata.gpu_count;
                metadata.gpu_type = collector_metadata.gpu_type.clone();
            }
            if !collector_metadata.cuda_version.is_empty() {
                metadata.cuda_version = collector_metadata.cuda_version.clone();
            }
            metadata.gpu_nvidia.extend(collector_metadata.gpu_nvidia);
            metadata.gpu_amd.extend(collector_metadata.gpu_amd);
            metadata.apple = collector_metadata.apple;
            if collector_metadata.tpu.is_some() {
                metadata.tpu = collector_metadata.tpu;
            }
        }

        metadata
    }

    pub fn shutdown(&self) {
        for collector in &self.collectors {
            collector.shutdown();
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
impl Collector for AppleGpuMonitor {
    async fn collect_metrics(&self) -> Result<Sample, Box<dyn std::error::Error>> {
        let stats = self.sampler.get_metrics().await?;
        let soc_info = self.sampler.get_soc_info().await?;
        Ok(Sample {
            metrics: self.sampler.metrics_to_vec(stats, soc_info),
            ..Default::default()
        })
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
use nvml_wrapper::error::NvmlError;

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
            Err(
                NvmlError::LibloadingError(_)
                | NvmlError::LibraryNotFound
                | NvmlError::DriverNotLoaded
                | NvmlError::NotFound,
            ) => {
                debug!("No NVIDIA driver found; NVIDIA GPU monitoring disabled");
                None
            }
            Err(e) => {
                warn!("Failed to initialize NVIDIA GPU monitoring: {e}");
                None
            }
        }
    }
}

#[cfg(any(target_os = "linux", target_os = "windows"))]
#[async_trait::async_trait]
impl Collector for NvidiaGpuMonitor {
    async fn collect_metrics(&self) -> Result<Sample, Box<dyn std::error::Error>> {
        Ok(self.gpu.lock().await.get_metrics()?)
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
impl Collector for DcgmGpuMonitor {
    async fn collect_metrics(&self) -> Result<Sample, Box<dyn std::error::Error>> {
        Ok(Sample {
            metrics: self.client.get_metrics().await?,
            ..Default::default()
        })
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

// ===== TPU Monitor (libtpu SDK + gRPC fallback) =====
#[cfg(target_os = "linux")]
use crate::tpu_libtpu;

// ===== AMD GPU Monitor =====
#[cfg(target_os = "linux")]
use crate::gpu_amd;

#[cfg(target_os = "linux")]
struct AmdGpuMonitor {
    gpu: tokio::sync::Mutex<gpu_amd::GpuAmd>,
}

#[cfg(target_os = "linux")]
impl AmdGpuMonitor {
    fn new() -> Option<Self> {
        gpu_amd::GpuAmd::new().map(|gpu| {
            debug!("Successfully initialized AMD GPU monitoring");
            Self {
                gpu: tokio::sync::Mutex::new(gpu),
            }
        })
    }
}

#[cfg(target_os = "linux")]
#[async_trait::async_trait]
impl Collector for AmdGpuMonitor {
    async fn collect_metrics(&self) -> Result<Sample, Box<dyn std::error::Error>> {
        Ok(Sample {
            metrics: self.gpu.lock().await.get_metrics(),
            ..Default::default()
        })
    }

    async fn collect_metadata(
        &self,
        _samples: &HashMap<String, &metrics::MetricValue>,
    ) -> EnvironmentRecord {
        self.gpu.lock().await.get_metadata()
    }
}

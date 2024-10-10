/// System metrics service for W&B

#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
mod gpu_apple;
#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
mod gpu_apple_sources;
mod gpu_nvidia;
mod metrics;
mod wandb_internal;

use clap::Parser;

use sentry::types::Dsn;
use tokio_stream;
use tonic;
use tonic::{transport::Server, Request, Response, Status};
// use tonic_reflection;

#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
use gpu_apple::ThreadSafeSampler;
#[cfg(any(target_os = "linux", target_os = "windows"))]
use gpu_nvidia::NvidiaGpu;
use wandb_internal::record::RecordType;
use wandb_internal::MetadataRequest;
use wandb_internal::{
    request::RequestType,
    stats_record::StatsType,
    system_monitor_server::{SystemMonitor, SystemMonitorServer},
    AppleInfo, GetMetadataRequest, GetStatsRequest, GpuNvidiaInfo, Record, Request as Req,
    StatsItem, StatsRecord,
};

#[derive(Parser, Debug)]
#[command(author, version, about, long_about=None)]
struct Args {
    #[arg(short, long)]
    portfile: String,

    /// Monitor this process ID and its children for GPU usage
    #[arg(short, long, default_value_t = 0)]
    pid: i32,
}

#[derive(Default)]
pub struct SystemMonitorImpl {
    shutdown_sender: tokio::sync::Mutex<Option<tokio::sync::oneshot::Sender<()>>>,
    pid: i32,
    #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
    apple_sampler: Option<ThreadSafeSampler>,
    #[cfg(any(target_os = "linux", target_os = "windows"))]
    nvidia_gpu: Option<tokio::sync::Mutex<NvidiaGpu>>,
}

impl SystemMonitorImpl {
    fn new(pid: i32) -> Self {
        #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
        let apple_sampler = match ThreadSafeSampler::new() {
            Ok(sampler) => {
                println!("Successfully initialized Apple GPU sampler");
                Some(sampler)
            }
            Err(e) => {
                println!("Failed to initialize Apple GPU sampler: {}", e);
                None
            }
        };

        #[cfg(any(target_os = "linux", target_os = "windows"))]
        let nvidia_gpu = match NvidiaGpu::new() {
            Ok(gpu) => {
                println!("Successfully initialized NVIDIA GPU monitoring");
                Some(tokio::sync::Mutex::new(gpu))
            }
            Err(e) => {
                println!("Failed to initialize NVIDIA GPU monitoring: {}", e);
                None
            }
        };

        SystemMonitorImpl {
            shutdown_sender: tokio::sync::Mutex::new(None), // Sender will be set later
            pid,
            #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
            apple_sampler,
            #[cfg(any(target_os = "linux", target_os = "windows"))]
            nvidia_gpu,
        }
    }

    async fn sample(&self) -> Vec<(String, metrics::MetricValue)> {
        let mut all_metrics = Vec::new();

        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();

        all_metrics.push((
            "_timestamp".to_string(),
            metrics::MetricValue::Float(timestamp),
        ));

        // Apple metrics (ARM Mac only)
        #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
        if let Some(apple_sampler) = &self.apple_sampler {
            match apple_sampler.get_metrics().await {
                Ok(apple_stats) => {
                    let apple_metrics = ThreadSafeSampler::metrics_to_vec(apple_stats);
                    all_metrics.extend(apple_metrics);
                }
                Err(e) => {
                    println!("Failed to get Apple metrics: {}", e);
                }
            }
        }

        // Nvidia metrics (Linux and Windows only)
        #[cfg(any(target_os = "linux", target_os = "windows"))]
        if let Some(nvidia_gpu) = &self.nvidia_gpu {
            match nvidia_gpu.lock().await.get_metrics(self.pid) {
                Ok(nvidia_metrics) => {
                    all_metrics.extend(nvidia_metrics);
                }
                Err(e) => {
                    println!("Failed to get Nvidia metrics: {}", e);
                }
            }
        }

        all_metrics
    }
}

#[tonic::async_trait]
impl SystemMonitor for SystemMonitorImpl {
    // tear_down takes an empty request and returns an empty response
    async fn tear_down(&self, request: Request<()>) -> Result<Response<()>, Status> {
        println!("Got a request to shutdown: {:?}", request);

        // Signal the server to shutdown
        let mut sender = self.shutdown_sender.lock().await;

        if let Some(sender) = sender.take() {
            sender.send(()).unwrap();
        }
        Ok(Response::new(()))
    }

    async fn get_metadata(
        &self,
        request: Request<GetMetadataRequest>,
    ) -> Result<Response<Record>, Status> {
        println!("Got a request to get metadata: {:?}", request);

        let all_metrics: Vec<(String, metrics::MetricValue)> = self.sample().await;

        // convert to hashmap
        let samples: std::collections::HashMap<String, &metrics::MetricValue> = all_metrics
            .iter()
            .map(|(name, value)| (name.to_string(), value))
            .collect();

        let mut metadata_request = MetadataRequest {
            ..Default::default()
        };

        // Apple metadata (ARM Mac only)
        #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
        {
            let mut gpu_apple = AppleInfo {
                ..Default::default()
            };
            if let Some(&value) = samples.get("_apple.chip_name") {
                gpu_apple.name = value.to_string();
            }
            if let Some(&value) = samples.get("_apple.ecpu_cores") {
                if let metrics::MetricValue::Int(ecpu_cores) = value {
                    gpu_apple.ecpu_cores = *ecpu_cores as u32;
                }
            }
            if let Some(&value) = samples.get("_apple.pcpu_cores") {
                if let metrics::MetricValue::Int(pcpu_cores) = value {
                    gpu_apple.pcpu_cores = *pcpu_cores as u32;
                }
            }
            if let Some(&value) = samples.get("_apple.gpu_cores") {
                if let metrics::MetricValue::Int(gpu_cores) = value {
                    gpu_apple.gpu_cores = *gpu_cores as u32;
                }
            }
            if let Some(&value) = samples.get("_apple.memory_gb") {
                if let metrics::MetricValue::Int(memory_gb) = value {
                    gpu_apple.memory_gb = *memory_gb as u32;
                }
            }

            metadata_request.apple = Some(gpu_apple);
        }

        // Nvidia metadata (Linux and Windows only)
        #[cfg(any(target_os = "linux", target_os = "windows"))]
        {
            let n_gpu = match samples.get("_gpu.count") {
                Some(metrics::MetricValue::Int(n_gpu)) => *n_gpu as u32,
                _ => 0,
            };

            if n_gpu > 0 {
                metadata_request.gpu_nvidia = [].to_vec();
                metadata_request.gpu_count = n_gpu;
                // TODO: assume all GPUs are the same
                if let Some(&value) = samples.get("_gpu.0.name") {
                    if let metrics::MetricValue::String(gpu_name) = value {
                        metadata_request.gpu_type = gpu_name.to_string();
                    }
                }
                if let Some(&value) = samples.get("cuda_version") {
                    if let metrics::MetricValue::String(cuda_version) = value {
                        metadata_request.cuda_version = cuda_version.to_string();
                    }
                }
            }

            for i in 0..n_gpu {
                let mut gpu_nvidia = GpuNvidiaInfo {
                    ..Default::default()
                };
                if let Some(&value) = samples.get(&format!("_gpu.{}.name", i)) {
                    gpu_nvidia.name = value.to_string();
                }
                if let Some(&value) = samples.get(&format!("_gpu.{}.memoryTotal", i)) {
                    if let metrics::MetricValue::Int(memory_total) = value {
                        gpu_nvidia.memory_total = *memory_total as u64;
                    }
                }
                // cuda cores
                if let Some(&value) = samples.get(&format!("_gpu.{}.cudaCores", i)) {
                    if let metrics::MetricValue::Int(cuda_cores) = value {
                        gpu_nvidia.cuda_cores = *cuda_cores as u32;
                    }
                }
                // architecture
                if let Some(&value) = samples.get(&format!("_gpu.{}.architecture", i)) {
                    gpu_nvidia.architecture = value.to_string();
                }
                metadata_request.gpu_nvidia.push(gpu_nvidia);
            }
        }

        let record = Record {
            record_type: Some(RecordType::Request(Req {
                request_type: Some(RequestType::Metadata(metadata_request)),
                ..Default::default()
            })),
            ..Default::default()
        };
        Ok(Response::new(record))
    }

    async fn get_stats(
        &self,
        request: Request<GetStatsRequest>,
    ) -> Result<Response<Record>, Status> {
        println!("Got a request to get stats: {:?}", request);

        let all_metrics = self.sample().await;

        // package metrics into a StatsRecord
        let stats_items: Vec<StatsItem> = all_metrics
            .iter()
            .map(|(name, value)| StatsItem {
                key: name.to_string(),
                value_json: value.to_string(),
            })
            .collect();

        let record = Record {
            record_type: Some(RecordType::Stats(StatsRecord {
                stats_type: StatsType::System as i32,
                item: stats_items,
                ..Default::default()
            })),
            ..Default::default()
        };

        Ok(Response::new(record))
    }
}

fn parse_bool(s: &str) -> bool {
    match s.to_lowercase().as_str() {
        "true" | "1" => true,
        "false" | "0" => false,
        _ => true,
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Parse command-line arguments
    let args = Args::parse();

    // Set up error reporting with Sentry
    let error_reporting_enabled = std::env::var("WANDB_ERROR_REPORTING")
        .map(|v| parse_bool(&v))
        .unwrap_or(true);

    let dsn: Option<Dsn> = if error_reporting_enabled {
        "https://9e9d0694aa7ccd41aeb5bc34aadd716a@o151352.ingest.us.sentry.io/4506068829470720"
            .parse()
            .ok()
    } else {
        None
    };

    let _guard = sentry::init(sentry::ClientOptions {
        dsn,
        release: sentry::release_name!(),
        ..Default::default()
    });

    // Bind only to the loopback interface
    let addr = (std::net::Ipv4Addr::LOCALHOST, 0);
    let listener = tokio::net::TcpListener::bind(addr).await?;

    // Create the shutdown signal channel
    let (shutdown_sender, shutdown_receiver) = tokio::sync::oneshot::channel::<()>();

    // System monitor service
    let mut system_monitor = SystemMonitorImpl::new(args.pid);
    system_monitor.shutdown_sender = tokio::sync::Mutex::new(Some(shutdown_sender));

    // TODO: Reflection service
    let descriptor = "/Users/dimaduev/dev/sdk/gpu_stats/src/descriptor.bin";
    let binding = std::fs::read(descriptor).unwrap();
    let descriptor_bytes = binding.as_slice();

    let reflection_service = tonic_reflection::server::Builder::configure()
        .register_encoded_file_descriptor_set(descriptor_bytes)
        .build_v1()
        .unwrap();

    let local_addr = listener.local_addr()?;
    // Write the port to the portfile
    std::fs::write(&args.portfile, local_addr.port().to_string())?;

    println!("System metrics service listening on {}", local_addr);

    Server::builder()
        .add_service(SystemMonitorServer::new(system_monitor))
        .add_service(reflection_service)
        .serve_with_incoming_shutdown(
            tokio_stream::wrappers::TcpListenerStream::new(listener),
            async {
                // Wait for the shutdown signal
                shutdown_receiver.await.ok();
                println!("Server is shutting down...");
            },
        )
        .await?;

    Ok(())
}

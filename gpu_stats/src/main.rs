#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
mod gpu_apple;
#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
mod gpu_apple_sources;
#[cfg(any(target_os = "linux", target_os = "windows"))]
mod gpu_nvidia;
mod metrics;
mod wandb_internal;

use clap::Parser;

use std::collections::HashMap;
use std::sync::Arc;

use sentry::types::Dsn;
use tokio::task::JoinHandle;
use tokio_stream;
use tonic;
use tonic::{transport::Server, Request, Response, Status};
// use tonic_reflection;

#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
use gpu_apple::ThreadSafeSampler;
#[cfg(any(target_os = "linux", target_os = "windows"))]
use gpu_nvidia::NvidiaGpu;
#[cfg(any(target_os = "linux", target_os = "windows"))]
use wandb_internal::GpuNvidiaInfo;
use wandb_internal::{
    record::RecordType,
    request::RequestType,
    stats_record::StatsType,
    system_monitor_server::{SystemMonitor, SystemMonitorServer},
    GetMetadataRequest, GetStatsRequest, MetadataRequest, Record, Request as Req, StatsItem,
    StatsRecord,
};

#[derive(Parser, Debug)]
#[command(author, version, about, long_about=None)]
struct Args {
    #[arg(short, long)]
    portfile: String,

    /// Parent process ID. If provided, the program will exit if the parent process is no longer alive.
    #[arg(short, long, default_value_t = 0)]
    ppid: i32,
}

#[derive(Default)]
pub struct SystemMonitorImpl {
    shutdown_sender: Arc<tokio::sync::Mutex<Option<tokio::sync::oneshot::Sender<()>>>>,
    parent_monitor_handle: Option<JoinHandle<()>>,
    #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
    apple_sampler: Option<ThreadSafeSampler>,
    #[cfg(any(target_os = "linux", target_os = "windows"))]
    nvidia_gpu: Option<tokio::sync::Mutex<NvidiaGpu>>,
}

impl SystemMonitorImpl {
    fn new(
        ppid: i32,
        shutdown_sender: Arc<tokio::sync::Mutex<Option<tokio::sync::oneshot::Sender<()>>>>,
    ) -> Self {
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

        let mut system_monitor = SystemMonitorImpl {
            shutdown_sender: shutdown_sender.clone(),
            parent_monitor_handle: None,
            #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
            apple_sampler,
            #[cfg(any(target_os = "linux", target_os = "windows"))]
            nvidia_gpu,
        };

        if ppid > 0 {
            let shutdown_sender_clone = shutdown_sender.clone();
            let handle = tokio::spawn(async move {
                loop {
                    tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                    if !is_parent_alive(ppid) {
                        // Trigger shutdown
                        let mut sender = shutdown_sender_clone.lock().await;
                        if let Some(sender) = sender.take() {
                            sender.send(()).ok();
                        }
                        break;
                    }
                }
            });
            system_monitor.parent_monitor_handle = Some(handle);
        };

        system_monitor
    }

    async fn sample(&self, pid: i32) -> Vec<(String, metrics::MetricValue)> {
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
                    let apple_metrics = apple_sampler.metrics_to_vec(apple_stats);
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
            match nvidia_gpu.lock().await.get_metrics(pid) {
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

        // Shutdown NVML
        #[cfg(any(target_os = "linux", target_os = "windows"))]
        if let Some(nvidia_gpu) = &self.nvidia_gpu {
            self.nvidia_gpu.lock().await.shutdown();
        }

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

        let all_metrics: Vec<(String, metrics::MetricValue)> = self.sample(0).await;

        // convert to hashmap
        let samples: HashMap<String, &metrics::MetricValue> = all_metrics
            .iter()
            .map(|(name, value)| (name.to_string(), value))
            .collect();

        let mut metadata_request = MetadataRequest {
            ..Default::default()
        };

        // Apple metadata (ARM Mac only)
        #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
        {
            if let Some(apple_sampler) = &self.apple_sampler {
                let apple_metadata = apple_sampler.get_metadata(&samples);
                metadata_request.apple = apple_metadata.apple;
            }
        }

        // Nvidia metadata (Linux and Windows only)
        #[cfg(any(target_os = "linux", target_os = "windows"))]
        {
            if let Some(nvidia_gpu) = &self.nvidia_gpu {
                let nvidia_metadata = nvidia_gpu.lock().await.get_metadata(&samples);
                // merge with existing metadata
                if nvidia_metadata.gpu_count > 0 {
                    metadata_request.gpu_count = nvidia_metadata.gpu_count;
                    metadata_request.gpu_type = nvidia_metadata.gpu_type;
                    metadata_request.cuda_version = nvidia_metadata.cuda_version;
                    metadata_request.gpu_nvidia = nvidia_metadata.gpu_nvidia;
                }
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

        let pid = request.into_inner().pid;
        let all_metrics = self.sample(pid).await;

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

/// Check if the parent process is still alive
#[cfg(not(target_os = "windows"))]
fn is_parent_alive(ppid: i32) -> bool {
    use nix::unistd::getppid;
    getppid() == nix::unistd::Pid::from_raw(ppid)
}

#[cfg(target_os = "windows")]
fn is_parent_alive(ppid: i32) -> bool {
    // TODO: Implement
    true
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
    let shutdown_sender = Arc::new(tokio::sync::Mutex::new(Some(shutdown_sender)));

    // System monitor service
    let system_monitor = SystemMonitorImpl::new(args.ppid, shutdown_sender.clone());

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

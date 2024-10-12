//! System metrics service for Weights & Biases.
//!
//! This service collects system metrics from various sources and exposes them via gRPC.
//!
//! Metrics are collected from the following sources:
//! - Nvidia GPUs (Linux and Windows only)
//! - Apple ARM Mac GPUs and CPUs (ARM Mac only)
mod analytics;
#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
mod gpu_apple;
#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
mod gpu_apple_sources;
#[cfg(any(target_os = "linux", target_os = "windows"))]
mod gpu_nvidia;
mod metrics;
mod wandb_internal;

use clap::Parser;

use env_logger::Builder;
use log::{debug, warn, LevelFilter};

use std::collections::HashMap;
use std::sync::Arc;

use tokio::task::JoinHandle;
use tokio_stream;
use tonic;
use tonic::{transport::Server, Request, Response, Status};

#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
use gpu_apple::ThreadSafeSampler;
#[cfg(any(target_os = "linux", target_os = "windows"))]
use gpu_nvidia::NvidiaGpu;
use wandb_internal::{
    record::RecordType,
    request::RequestType,
    stats_record::StatsType,
    system_monitor_server::{SystemMonitor, SystemMonitorServer},
    GetMetadataRequest, GetStatsRequest, MetadataRequest, Record, Request as Req, StatsItem,
    StatsRecord,
};

/// Command-line arguments for the system metrics service.
#[derive(Parser, Debug)]
#[command(author, version, about, long_about=None)]
struct Args {
    /// Portfile to write the gRPC server port to.
    ///
    /// Used to establish communication between the parent process (wandb-core) and the service.
    #[arg(short, long)]
    portfile: String,

    /// Parent process ID.
    ///
    /// If provided, the program will exit if the parent process is no longer alive.
    #[arg(short, long, default_value_t = 0)]
    ppid: i32,

    /// Verbose logging.
    ///
    /// If set, the program will log debug messages.
    #[arg(short, long, default_value_t = false)]
    verbose: bool,
}

/// System monitor implementation.
///
/// Implements the gRPC service defined in `wandb_internal::system_monitor_server`.
#[derive(Default)]
pub struct SystemMonitorImpl {
    /// Sender handle for the shutdown channel.
    ///
    /// Used to trigger service shutdown. The service will terminate if:
    /// - The parent process is no longer alive.
    /// - The teardown gRPC method is called.
    shutdown_sender: Arc<tokio::sync::Mutex<Option<tokio::sync::oneshot::Sender<()>>>>,
    /// Handle to the task that monitors the parent process.
    ///
    /// If the parent process is no longer alive, the service will shutdown.
    parent_monitor_handle: Option<JoinHandle<()>>,
    /// Apple GPU sampler (ARM Mac only).
    #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
    apple_sampler: Option<ThreadSafeSampler>,
    /// Nvidia GPU monitor (Linux and Windows only).
    #[cfg(any(target_os = "linux", target_os = "windows"))]
    nvidia_gpu: Option<tokio::sync::Mutex<NvidiaGpu>>,
}

impl SystemMonitorImpl {
    fn new(
        ppid: i32,
        shutdown_sender: Arc<tokio::sync::Mutex<Option<tokio::sync::oneshot::Sender<()>>>>,
    ) -> Self {
        // Initialize the Apple GPU sampler (ARM Mac only)
        #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
        let apple_sampler = match ThreadSafeSampler::new() {
            Ok(sampler) => {
                debug!("Successfully initialized Apple GPU sampler");
                Some(sampler)
            }
            Err(e) => {
                warn!("Failed to initialize Apple GPU sampler: {}", e);
                None
            }
        };

        // Initialize the Nvidia GPU monitor (Linux and Windows only)
        #[cfg(any(target_os = "linux", target_os = "windows"))]
        let nvidia_gpu = match NvidiaGpu::new() {
            Ok(gpu) => {
                debug!("Successfully initialized NVIDIA GPU monitoring");
                Some(tokio::sync::Mutex::new(gpu))
            }
            Err(e) => {
                warn!("Failed to initialize NVIDIA GPU monitoring: {}", e);
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

        // An async task that monitors the parent process ppid, if provided.
        // It shares the shutdown sender handle with the main service.
        if ppid > 0 {
            let shutdown_sender_clone = shutdown_sender.clone();
            let handle = tokio::spawn(async move {
                loop {
                    tokio::time::sleep(std::time::Duration::from_secs(5)).await;
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

    /// Collect system metrics.
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
                    warn!("Failed to get Apple metrics: {}", e);
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
                    warn!("Failed to get Nvidia metrics: {}", e);
                }
            }
        }

        all_metrics
    }
}

/// The gRPC service implementation for the system monitor.
#[tonic::async_trait]
impl SystemMonitor for SystemMonitorImpl {
    /// Tear down the system monitor service.
    async fn tear_down(&self, request: Request<()>) -> Result<Response<()>, Status> {
        debug!("Got a request to shutdown: {:?}", request);

        // Signal the gRPC server to shutdown
        let mut sender = self.shutdown_sender.lock().await;
        if let Some(sender) = sender.take() {
            sender.send(()).unwrap();
        }
        Ok(Response::new(()))
    }

    /// Get static metadata about the system.
    async fn get_metadata(
        &self,
        request: Request<GetMetadataRequest>,
    ) -> Result<Response<Record>, Status> {
        debug!("Got a request to get metadata: {:?}", request);

        let all_metrics: Vec<(String, metrics::MetricValue)> = self.sample(0).await;
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

    /// Get system metrics.
    async fn get_stats(
        &self,
        request: Request<GetStatsRequest>,
    ) -> Result<Response<Record>, Status> {
        debug!("Got a request to get stats: {:?}", request);

        let pid = request.into_inner().pid;
        let all_metrics = self.sample(pid).await;

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

/// Main entry point for the system metrics service.
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Parse command-line arguments
    let args = Args::parse();

    // Initialize logging
    let logging_level = if args.verbose {
        LevelFilter::Debug
    } else {
        LevelFilter::Info
    };
    Builder::new().filter_level(logging_level).init();

    // Initialize error reporting with Sentry
    analytics::setup_sentry();

    // Bind to the loopback interface.
    let addr = (std::net::Ipv4Addr::LOCALHOST, 0);
    let listener = tokio::net::TcpListener::bind(addr).await?;

    // Create the channel for service shutdown signals.
    let (shutdown_sender, shutdown_receiver) = tokio::sync::oneshot::channel::<()>();
    let shutdown_sender = Arc::new(tokio::sync::Mutex::new(Some(shutdown_sender)));

    let system_monitor = SystemMonitorImpl::new(args.ppid, shutdown_sender.clone());

    // Write the server port to the portfile
    let local_addr = listener.local_addr()?;
    std::fs::write(&args.portfile, local_addr.port().to_string())?;

    debug!("System metrics service listening on {}", local_addr);

    Server::builder()
        .add_service(SystemMonitorServer::new(system_monitor))
        .serve_with_incoming_shutdown(
            tokio_stream::wrappers::TcpListenerStream::new(listener),
            async {
                // Wait for the shutdown signal
                shutdown_receiver.await.ok();
                debug!("Server is shutting down...");
            },
        )
        .await?;

    Ok(())
}

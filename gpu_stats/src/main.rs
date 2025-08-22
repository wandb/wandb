//! System metrics service for the Weights & Biases SDK.
//!
//! This service collects system metrics from various sources and exposes them via gRPC.
//!
//! Metrics are collected from the following sources:
//! - Nvidia GPUs via NVML and DCGM (Linux and Windows only)
//! - Apple ARM Mac GPUs and CPUs (ARM Mac only)
//! - AMD GPUs (Linux only)

mod analytics;
mod metrics;
mod monitors;
mod wandb_internal;

// Platform-specific modules
#[cfg(target_os = "linux")]
mod gpu_amd;
#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
mod gpu_apple;
#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
mod gpu_apple_sources;
#[cfg(any(target_os = "linux", target_os = "windows"))]
mod gpu_nvidia;
#[cfg(target_os = "linux")]
mod gpu_nvidia_dcgm;

use clap::Parser;
use env_logger::Builder;
use log::{debug, LevelFilter};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::net::TcpListener;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::TcpListenerStream;
use tonic::{transport::Server, Request, Response, Status};

use chrono::Utc;
use prost_types::Timestamp;
use wandb_internal::{
    record::RecordType,
    stats_record::StatsType,
    system_monitor_service_server::{SystemMonitorService, SystemMonitorServiceServer},
    GetMetadataRequest, GetMetadataResponse, GetStatsRequest, GetStatsResponse, Record, StatsItem,
    StatsRecord, TearDownRequest, TearDownResponse,
};

use monitors::GpuMonitors;

// Unix-specific imports
#[cfg(not(target_os = "windows"))]
use tokio::net::UnixListener;
#[cfg(not(target_os = "windows"))]
use tokio_stream::wrappers::UnixListenerStream;

fn current_timestamp() -> Timestamp {
    let now = Utc::now();
    Timestamp {
        seconds: now.timestamp(),
        nanos: now.timestamp_subsec_nanos() as i32,
    }
}

/// Command-line arguments for the system metrics service.
#[derive(Parser, Debug)]
#[command(author, version, about, long_about=None)]
struct Args {
    /// File to write the gRPC server token to.
    ///
    /// Used to establish communication between the parent process (wandb-core) and the service.
    /// Supports Unix and TCP sockets.
    #[arg(long)]
    portfile: String,

    /// Parent process ID.
    ///
    /// If provided, the program will exit if the parent process is no longer alive.
    #[arg(long, default_value_t = 0)]
    parent_pid: i32,

    /// Verbose logging.
    ///
    /// If set, the program will log debug messages.
    #[arg(short, long, default_value_t = false)]
    verbose: bool,

    /// Enable DCGM profiling.
    ///
    /// If set, the program will attempt to use DCGM for
    /// collection Nvidia GPU performance metrics.
    #[arg(long, default_value_t = false)]
    enable_dcgm_profiling: bool,

    /// Whether to listen on a localhost socket.
    ///
    /// This is less secure than Unix sockets, but not all clients support them.
    /// On Windows, this is always true regardless of the flag.
    #[arg(long, default_value_t = false)]
    listen_on_localhost: bool,
}

/// System monitor service implementation.
pub struct SystemMonitorServiceImpl {
    /// Sender handle for the shutdown channel.
    shutdown_sender: Arc<tokio::sync::Mutex<Option<tokio::sync::oneshot::Sender<()>>>>,
    /// Handle to the task that monitors the parent process.
    parent_monitor_handle: Option<JoinHandle<()>>,
    /// GPU monitoring components
    gpu_monitors: GpuMonitors,
}

impl SystemMonitorServiceImpl {
    fn new(
        parent_pid: i32,
        enable_dcgm_profiling: bool,
        shutdown_sender: Arc<tokio::sync::Mutex<Option<tokio::sync::oneshot::Sender<()>>>>,
    ) -> Self {
        let gpu_monitors = GpuMonitors::new(enable_dcgm_profiling);

        let mut system_monitor = SystemMonitorServiceImpl {
            shutdown_sender: shutdown_sender.clone(),
            parent_monitor_handle: None,
            gpu_monitors,
        };

        // An async task that monitors the parent process id, if provided.
        if parent_pid > 0 {
            let shutdown_sender_clone = shutdown_sender.clone();
            let handle = tokio::spawn(async move {
                loop {
                    tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                    if !is_parent_alive(parent_pid) {
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
    async fn sample(
        &self,
        pid: i32,
        gpu_device_ids: Option<Vec<i32>>,
    ) -> Vec<(String, metrics::MetricValue)> {
        let mut all_metrics = Vec::new();

        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();

        all_metrics.push((
            "_timestamp".to_string(),
            metrics::MetricValue::Float(timestamp),
        ));

        // Collect metrics from all available GPU monitors
        let gpu_metrics = self.gpu_monitors.collect_metrics(pid, gpu_device_ids).await;
        all_metrics.extend(gpu_metrics);

        all_metrics
    }
}

/// The gRPC service implementation for the system monitor.
#[tonic::async_trait]
impl SystemMonitorService for SystemMonitorServiceImpl {
    /// Tear down the system monitor service.
    async fn tear_down(
        &self,
        request: Request<TearDownRequest>,
    ) -> Result<Response<TearDownResponse>, Status> {
        debug!("Received a request to ShutdownShutdown: {:?}", request);

        // Shutdown GPU monitors
        self.gpu_monitors.shutdown();

        // Signal the gRPC server to shutdown
        let mut sender = self.shutdown_sender.lock().await;
        if let Some(sender) = sender.take() {
            sender.send(()).unwrap();
        }

        Ok(Response::new(TearDownResponse {}))
    }

    /// Get static metadata about the system.
    async fn get_metadata(
        &self,
        request: Request<GetMetadataRequest>,
    ) -> Result<Response<GetMetadataResponse>, Status> {
        debug!("Received a GetMetadata request: {:?}", request);

        let all_metrics: Vec<(String, metrics::MetricValue)> = self.sample(0, None).await;
        let samples: HashMap<String, &metrics::MetricValue> = all_metrics
            .iter()
            .map(|(name, value)| (name.to_string(), value))
            .collect();

        let metadata = self.gpu_monitors.collect_metadata(&samples).await;

        let record = Record {
            record_type: Some(RecordType::Environment(metadata)),
            ..Default::default()
        };

        let response = GetMetadataResponse {
            record: Some(record),
        };

        Ok(Response::new(response))
    }

    /// Get system metrics.
    async fn get_stats(
        &self,
        request: Request<GetStatsRequest>,
    ) -> Result<Response<GetStatsResponse>, Status> {
        debug!("Received a request to get stats: {:?}", request);

        let request = request.into_inner();
        let pid = request.pid;
        let gpu_device_ids = if request.gpu_device_ids.is_empty() {
            None
        } else {
            Some(request.gpu_device_ids)
        };

        let all_metrics = self.sample(pid, gpu_device_ids).await;

        let stats_items: Vec<StatsItem> = all_metrics
            .iter()
            .filter(|(name, _)| !name.starts_with('_')) // Skip internal metrics
            .filter_map(|(name, value)| {
                serde_json::to_string(value).ok().map(|json_str| StatsItem {
                    key: name.to_string(),
                    value_json: json_str,
                })
            })
            .collect();

        let record = Record {
            record_type: Some(RecordType::Stats(StatsRecord {
                timestamp: Some(current_timestamp()),
                stats_type: StatsType::System as i32,
                item: stats_items,
                ..Default::default()
            })),
            ..Default::default()
        };

        let response = GetStatsResponse {
            record: Some(record),
        };

        Ok(Response::new(response))
    }
}

/// Check if the parent process is still alive
#[cfg(not(target_os = "windows"))]
fn is_parent_alive(parent_pid: i32) -> bool {
    use nix::unistd::getppid;
    getppid() == nix::unistd::Pid::from_raw(parent_pid)
}

#[cfg(target_os = "windows")]
fn is_parent_alive(parent_pid: i32) -> bool {
    // TODO: implement
    true
}

/// Listener types for different platforms
enum ListenerType {
    Tcp(TcpListenerStream),
    #[cfg(not(target_os = "windows"))]
    Unix(UnixListenerStream),
}

/// Create and configure the appropriate listener based on platform and settings.
async fn create_listener(args: &Args) -> Result<ListenerType, Box<dyn std::error::Error>> {
    // On Windows, always use TCP; on other platforms, respect the flag
    #[cfg(target_os = "windows")]
    let use_tcp = true;
    #[cfg(not(target_os = "windows"))]
    let use_tcp = args.listen_on_localhost;

    if use_tcp {
        // TCP listener
        let listener = TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0)).await?;
        let local_addr = listener.local_addr()?;
        let stream = TcpListenerStream::new(listener);

        // Write the server port to the portfile
        let token = format!("sock={}", local_addr.port());
        std::fs::write(&args.portfile, token)?;
        debug!("System metrics service listening on {}", local_addr);

        Ok(ListenerType::Tcp(stream))
    } else {
        // Unix Domain Socket listener (only available on non-Windows platforms)
        #[cfg(not(target_os = "windows"))]
        {
            let mut socket_path = std::env::temp_dir();
            let pid = std::process::id();
            let time_stamp = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("time should go forward")
                .as_millis();

            let socket_filename = format!(
                "wandb_gpu_stats-{}-{}-{}.sock",
                args.parent_pid, pid, time_stamp
            );
            socket_path.push(socket_filename);

            // Ensure the socket is removed if it already exists
            if socket_path.exists() {
                let _ = std::fs::remove_file(&socket_path);
            }

            let listener = UnixListener::bind(&socket_path)?;
            let stream = UnixListenerStream::new(listener);

            // Use `to_str()` for a clean string representation without quotes
            if let Some(path_str) = socket_path.to_str() {
                let token = format!("unix={}", path_str);
                std::fs::write(&args.portfile, token)?;
                debug!("System metrics service listening on {}", path_str);

                // Store path for cleanup
                let cleanup_path = socket_path.clone();
                tokio::spawn(async move {
                    tokio::signal::ctrl_c().await.ok();
                    let _ = std::fs::remove_file(&cleanup_path);
                });
            } else {
                return Err("Invalid UTF-8 sequence in socket path".into());
            }

            Ok(ListenerType::Unix(stream))
        }
        #[cfg(target_os = "windows")]
        {
            unreachable!("Unix sockets are not available on Windows")
        }
    }
}

/// Main entry point for the system metrics service.
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Parse command-line arguments.
    let args = Args::parse();

    // Initialize logging.
    let logging_level = if args.verbose {
        LevelFilter::Debug
    } else {
        LevelFilter::Info
    };
    Builder::new().filter_level(logging_level).init();
    debug!("Starting system metrics service");

    // Initialize error reporting with Sentry.
    analytics::setup_sentry();
    debug!("Sentry set up");

    // Create the channel for service shutdown signals.
    let (shutdown_sender, shutdown_receiver) = tokio::sync::oneshot::channel::<()>();
    let shutdown_sender = Arc::new(tokio::sync::Mutex::new(Some(shutdown_sender)));

    let system_monitor_service = SystemMonitorServiceImpl::new(
        args.parent_pid,
        args.enable_dcgm_profiling,
        shutdown_sender.clone(),
    );

    let server_builder =
        Server::builder().add_service(SystemMonitorServiceServer::new(system_monitor_service));

    let shutdown_signal = async {
        shutdown_receiver.await.ok();
        debug!("Server is shutting down...");
    };

    let listener = create_listener(&args).await?;

    match listener {
        ListenerType::Tcp(stream) => {
            server_builder
                .serve_with_incoming_shutdown(stream, shutdown_signal)
                .await?;
        }
        #[cfg(not(target_os = "windows"))]
        ListenerType::Unix(stream) => {
            server_builder
                .serve_with_incoming_shutdown(stream, shutdown_signal)
                .await?;
        }
    }

    Ok(())
}

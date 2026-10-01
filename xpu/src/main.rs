//! System metrics service for the Weights & Biases SDK.
//!
//! This service collects system metrics from various sources and exposes them via gRPC.
//!
//! Metrics are collected from the following sources:
//! - Nvidia GPUs via NVML and DCGM (Linux and Windows only)
//! - Apple ARM Mac GPUs and CPUs (ARM Mac only)
//! - AMD GPUs (Linux only)
//! - Google TPUs via libtpu (Linux only)
//! - Host CPU, memory, disk, network and cgroup limits via procfs and sysfs (Linux only)

mod host;
mod metrics;
mod monitors;
mod record;
mod subscriptions;
#[allow(dead_code)]
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
#[cfg(target_os = "linux")]
#[allow(dead_code)] // items used via dyn Collector dispatch; rustc can't trace through async_trait
mod tpu_libtpu;
#[cfg(target_os = "linux")]
#[allow(dead_code)]
#[path = "tpu.monitoring.runtime.rs"]
mod tpu_runtime;

use clap::Parser;
use env_logger::Builder;
use log::{LevelFilter, debug};
use std::collections::HashMap;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::net::TcpListener;
use tokio::sync::OnceCell;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::{ReceiverStream, TcpListenerStream};
use tonic::{Request, Response, Status, transport::Server};

use wandb_internal::{
    EnvironmentRecord, GetMetadataRequest, GetMetadataResponse, Record, SubscribeRequest,
    SubscribeResponse, TearDownRequest, TearDownResponse,
    record::RecordType,
    system_monitor_service_server::{SystemMonitorService, SystemMonitorServiceServer},
};

use monitors::Collectors;
use subscriptions::Subscriptions;

// Unix-specific imports
#[cfg(not(target_os = "windows"))]
use tokio::net::UnixListener;
#[cfg(not(target_os = "windows"))]
use tokio_stream::wrappers::UnixListenerStream;

/// Command-line arguments for the system metrics service.
#[derive(Parser, Debug)]
#[command(author, version, about, long_about=None)]
struct Args {
    /// File to write the gRPC server token to.
    ///
    /// Used to establish communication between the parent process (wandb-core) and the service.
    /// Supports Unix and TCP sockets. Optional with --listen.
    #[arg(long, required_unless_present = "listen")]
    portfile: Option<String>,

    /// Parent process ID.
    ///
    /// If provided, the program will exit if the parent process is no longer alive.
    /// Ignored with --listen.
    #[arg(long, default_value_t = 0)]
    parent_pid: i32,

    /// Unix socket path to listen on.
    ///
    /// If set, the program binds this path instead of a private socket and
    /// serves every client that connects to it. Unix only.
    #[arg(long, conflicts_with = "listen_on_localhost")]
    listen: Option<PathBuf>,

    /// Seconds without subscribers after which the program exits.
    ///
    /// Zero, the default, keeps the program running.
    #[arg(long, default_value_t = 0, requires = "listen")]
    idle_timeout: u64,

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
    /// The hardware metric sources available on this machine.
    collectors: Arc<Collectors>,
    /// The clients receiving metrics and the clock that serves them.
    subscriptions: Arc<Subscriptions>,
    /// Static facts about the hardware, gathered on the first request.
    metadata: OnceCell<EnvironmentRecord>,
}

impl SystemMonitorServiceImpl {
    fn new(
        parent_pid: i32,
        enable_dcgm_profiling: bool,
        shutdown_sender: Arc<tokio::sync::Mutex<Option<tokio::sync::oneshot::Sender<()>>>>,
    ) -> Self {
        let collectors = Arc::new(Collectors::new(enable_dcgm_profiling));
        let subscriptions = Arc::new(Subscriptions::new());
        tokio::spawn(subscriptions::run(
            subscriptions.clone(),
            collectors.clone(),
        ));

        let mut system_monitor = SystemMonitorServiceImpl {
            shutdown_sender: shutdown_sender.clone(),
            parent_monitor_handle: None,
            collectors,
            subscriptions,
            metadata: OnceCell::new(),
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

        self.collectors.shutdown();

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

        let metadata = self
            .metadata
            .get_or_init(|| async {
                let sample = self.collectors.collect_metrics(Vec::new()).await;
                let samples: HashMap<String, &metrics::MetricValue> = sample
                    .metrics
                    .iter()
                    .map(|(name, value)| (name.to_string(), value))
                    .collect();
                self.collectors.collect_metadata(&samples).await
            })
            .await;
        let mut metadata = metadata.clone();
        self.collectors
            .probe(&request.into_inner().disk_paths, &mut metadata);

        let record = Record {
            record_type: Some(RecordType::Environment(metadata)),
            ..Default::default()
        };

        let response = GetMetadataResponse {
            record: Some(record),
        };

        Ok(Response::new(response))
    }

    type SubscribeStream = ReceiverStream<Result<SubscribeResponse, Status>>;

    /// Stream system metrics at the subscriber's interval.
    async fn subscribe(
        &self,
        request: Request<SubscribeRequest>,
    ) -> Result<Response<Self::SubscribeStream>, Status> {
        debug!("Received a Subscribe request: {:?}", request);

        let rx = self.subscriptions.add(&request.into_inner())?;
        Ok(Response::new(ReceiverStream::new(rx)))
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
    if let Some(path) = &args.listen {
        #[cfg(not(target_os = "windows"))]
        return Ok(ListenerType::Unix(listen_at(path, args)?));
        #[cfg(target_os = "windows")]
        return Err("--listen is not supported on Windows".into());
    }

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
        write_portfile(args, &token)?;
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

            let socket_filename =
                format!("wandb_xpu-{}-{}-{}.sock", args.parent_pid, pid, time_stamp);
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
                write_portfile(args, &token)?;
                debug!("System metrics service listening on {}", path_str);

                // `UnixListener` does not unlink its socket file on drop;
                // a Drop guard parked in a tokio task cleans it up when the
                // runtime shuts down (or on SIGINT).
                struct SocketCleanup(std::path::PathBuf);
                impl Drop for SocketCleanup {
                    fn drop(&mut self) {
                        let _ = std::fs::remove_file(&self.0);
                    }
                }
                let cleanup = SocketCleanup(socket_path.clone());
                tokio::spawn(async move {
                    let _cleanup = cleanup;
                    tokio::signal::ctrl_c().await.ok();
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

/// Writes the server's address to --portfile, if given.
fn write_portfile(args: &Args, token: &str) -> std::io::Result<()> {
    match &args.portfile {
        Some(portfile) => std::fs::write(portfile, token),
        None => Ok(()),
    }
}

/// Binds the socket of a daemon shared by every wandb-core of one user on
/// the node at `path`, replacing a socket file that nothing listens on.
///
/// SIGTERM and SIGINT unlink the socket and exit.
#[cfg(not(target_os = "windows"))]
fn listen_at(
    path: &std::path::Path,
    args: &Args,
) -> Result<UnixListenerStream, Box<dyn std::error::Error>> {
    use std::os::unix::fs::PermissionsExt;
    use tokio::signal::unix::{SignalKind, signal};

    match std::os::unix::net::UnixStream::connect(path) {
        Ok(_) => return Err(format!("{} is already in use", path.display()).into()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => std::fs::remove_file(path)?,
    }
    let listener = UnixListener::bind(path)?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    write_portfile(args, &format!("unix={}", path.display()))?;
    debug!("System metrics service listening on {}", path.display());

    let mut terminate = signal(SignalKind::terminate())?;
    let path = path.to_path_buf();
    tokio::spawn(async move {
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {}
            _ = terminate.recv() => {}
        }
        let _ = std::fs::remove_file(&path);
        std::process::exit(0);
    });

    Ok(UnixListenerStream::new(listener))
}

/// Exits once there have been no subscribers for `timeout`.
///
/// The socket is unlinked under an exclusive flock on `<socket_path>.lock`,
/// the file clients lock while electing a daemon, after checking again that
/// no subscriber joined in the meantime.
#[cfg(not(target_os = "windows"))]
async fn exit_when_idle(
    subscriptions: Arc<Subscriptions>,
    socket_path: PathBuf,
    timeout: std::time::Duration,
    shutdown_sender: Arc<tokio::sync::Mutex<Option<tokio::sync::oneshot::Sender<()>>>>,
) {
    use nix::fcntl::{Flock, FlockArg};

    let mut lock_path = socket_path.clone().into_os_string();
    lock_path.push(".lock");
    let idle = || {
        subscriptions
            .idle_since()
            .is_some_and(|since| since.elapsed() >= timeout)
    };
    loop {
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
        if !idle() {
            continue;
        }
        let lock = std::fs::File::create(&lock_path).and_then(|file| {
            Flock::lock(file, FlockArg::LockExclusive).map_err(|(_, errno)| errno.into())
        });
        if let Err(e) = &lock {
            log::warn!("Failed to lock {}: {e}", lock_path.display());
        }
        if !idle() {
            continue;
        }
        debug!("No subscribers for {timeout:?}; exiting");
        let _ = std::fs::remove_file(&socket_path);
        drop(lock);
        if let Some(sender) = shutdown_sender.lock().await.take() {
            sender.send(()).ok();
        }
        return;
    }
}

/// Initialize logger that writes to a file in the wandb cache directory.
/// Returns the open file handle (must be kept alive for the logger's lifetime).
/// Falls back to stderr if the log file cannot be created.
fn init_file_logger(level: LevelFilter) -> Option<std::fs::File> {
    let cache_dir = std::env::var("WANDB_CACHE_DIR")
        .ok()
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| {
            // Match Go's os.UserCacheDir(): $HOME/.cache on Linux, $HOME/Library/Caches on macOS.
            let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
            #[cfg(target_os = "macos")]
            {
                format!("{home}/Library/Caches")
            }
            #[cfg(not(target_os = "macos"))]
            {
                format!("{home}/.cache")
            }
        });

    let log_dir = std::path::PathBuf::from(&cache_dir)
        .join("wandb")
        .join("logs");
    if let Err(e) = std::fs::create_dir_all(&log_dir) {
        eprintln!(
            "wandb-xpu: failed to create log dir {}: {e}",
            log_dir.display()
        );
        Builder::new().filter_level(level).init();
        return None;
    }

    let timestamp = chrono::Local::now().format("%Y%m%d_%H%M%S");
    let log_path = log_dir.join(format!("xpu-debug-{timestamp}.log"));

    match std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
    {
        Ok(file) => {
            let writer = file.try_clone().expect("failed to clone log file handle");
            Builder::new()
                .filter_level(level)
                .target(env_logger::Target::Pipe(Box::new(writer)))
                .format(|buf, record| {
                    writeln!(
                        buf,
                        "{} [{}] {}:{} {}",
                        chrono::Local::now().format("%Y-%m-%dT%H:%M:%S%.3f"),
                        record.level(),
                        record.file().unwrap_or("?"),
                        record.line().unwrap_or(0),
                        record.args(),
                    )
                })
                .init();
            Some(file)
        }
        Err(e) => {
            eprintln!(
                "wandb-xpu: failed to open log file {}: {e}",
                log_path.display()
            );
            Builder::new().filter_level(level).init();
            None
        }
    }
}

/// Main entry point for the system metrics service.
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Parse command-line arguments.
    let args = Args::parse();

    // Initialize logging — write to a persistent file matching wandb-core's pattern:
    //   {cache_dir}/wandb/logs/xpu-debug-{timestamp}.log
    let wandb_debug = std::env::var("WANDB_DEBUG")
        .ok()
        .is_some_and(|v| !v.is_empty() && v != "0" && v.to_lowercase() != "false");
    let logging_level = if args.verbose || wandb_debug {
        LevelFilter::Debug
    } else {
        LevelFilter::Info
    };
    let _log_guard = init_file_logger(logging_level);
    debug!("Starting system metrics service");

    // Create the channel for service shutdown signals.
    let (shutdown_sender, shutdown_receiver) = tokio::sync::oneshot::channel::<()>();
    let shutdown_sender = Arc::new(tokio::sync::Mutex::new(Some(shutdown_sender)));

    // Bind the socket and publish the portfile before initializing hardware
    // monitors, so wandb-core does not wait on driver initialization.
    let listener = create_listener(&args).await?;

    let system_monitor_service = SystemMonitorServiceImpl::new(
        if args.listen.is_some() {
            0
        } else {
            args.parent_pid
        },
        args.enable_dcgm_profiling,
        shutdown_sender.clone(),
    );

    #[cfg(not(target_os = "windows"))]
    if let Some(path) = &args.listen
        && args.idle_timeout > 0
    {
        tokio::spawn(exit_when_idle(
            system_monitor_service.subscriptions.clone(),
            path.clone(),
            std::time::Duration::from_secs(args.idle_timeout),
            shutdown_sender.clone(),
        ));
    }

    let server_builder =
        Server::builder().add_service(SystemMonitorServiceServer::new(system_monitor_service));

    let shutdown_signal = async {
        shutdown_receiver.await.ok();
        debug!("Server is shutting down...");
    };

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

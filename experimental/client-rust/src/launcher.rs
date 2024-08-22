use fork::{fork, Fork};
use sentry;
use std::fs;
use std::io;
use std::process::Command;
use std::{fmt, thread, time};
use tempfile::NamedTempFile;
use tracing;

#[derive(Debug)]
pub enum LauncherError {
    Io(io::Error),
    ForkFailed(String),
    PortParseFailed,
    Timeout,
}

impl std::error::Error for LauncherError {}

impl fmt::Display for LauncherError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            LauncherError::Io(err) => write!(f, "IO error: {}", err),
            LauncherError::ForkFailed(msg) => write!(f, "Fork failed: {}", msg),
            LauncherError::PortParseFailed => write!(f, "Failed to parse port number"),
            LauncherError::Timeout => write!(f, "Timeout waiting for port"),
        }
    }
}

impl From<io::Error> for LauncherError {
    fn from(err: io::Error) -> Self {
        LauncherError::Io(err)
    }
}

pub struct Launcher {
    pub command: String,
}

fn wait_for_port(port_filename: &str, timeout: time::Duration) -> Result<i32, LauncherError> {
    let start_time = time::Instant::now();
    let delay_time = time::Duration::from_millis(20);

    while start_time.elapsed() < timeout {
        thread::sleep(delay_time);
        let contents = fs::read_to_string(port_filename)?;
        let lines: Vec<_> = contents.lines().collect();

        if lines.last().copied() == Some("EOF") {
            for item in lines.iter() {
                if let Some((param, val)) = item.split_once('=') {
                    if param == "sock" {
                        return val.parse().map_err(|_| LauncherError::PortParseFailed);
                    }
                }
            }
        }
    }

    Err(LauncherError::Timeout)
}

impl Launcher {
    pub fn start(&self) -> Result<i32, LauncherError> {
        let port_file = NamedTempFile::new()?;
        let port_filename = port_file.path().to_str().ok_or_else(|| {
            LauncherError::Io(io::Error::new(
                io::ErrorKind::InvalidData,
                "Failed to get port filename",
            ))
        })?;

        match fork() {
            Ok(Fork::Parent(_child)) => wait_for_port(port_filename, time::Duration::from_secs(30)),
            Ok(Fork::Child) => {
                let output = Command::new(&self.command)
                    .arg("--port-filename")
                    .arg(port_filename)
                    .output()?;

                if !output.status.success() {
                    tracing::error!("Child process failed: {:?}", output);
                    std::process::exit(1);
                }
                std::process::exit(0);
            }
            Err(e) => {
                let error = LauncherError::ForkFailed(e.to_string());
                sentry::capture_error(&error);
                tracing::error!("Fork failed: {}", e);
                Err(error)
            }
        }
    }
}

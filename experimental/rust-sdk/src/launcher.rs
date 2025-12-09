use fork::{fork, Fork};
use sentry;
use std::fs;
use std::io;
use std::process::{Child, Command};
use std::{fmt, thread, time};
use tempfile::NamedTempFile;
use tracing;

#[derive(Debug)]
pub enum LauncherError {
    Io(io::Error),
    ForkFailed(String),
    SocketPathNotFound,
    Timeout,
}

impl std::error::Error for LauncherError {}

impl fmt::Display for LauncherError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            LauncherError::Io(err) => write!(f, "IO error: {}", err),
            LauncherError::ForkFailed(msg) => write!(f, "Fork failed: {}", msg),
            LauncherError::SocketPathNotFound => write!(f, "Unix socket path not found in port file"),
            LauncherError::Timeout => write!(f, "Timeout waiting for socket"),
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
    pub child_process: Option<Child>,
}

fn wait_for_socket(port_filename: &str, timeout: time::Duration) -> Result<String, LauncherError> {
    let start_time = time::Instant::now();
    let delay_time = time::Duration::from_millis(20);

    while start_time.elapsed() < timeout {
        thread::sleep(delay_time);
        let contents = fs::read_to_string(port_filename)?;
        let lines: Vec<_> = contents.lines().collect();

        if lines.last().copied() == Some("EOF") {
            for item in lines.iter() {
                if let Some((param, val)) = item.split_once('=') {
                    if param == "unix" {
                        return Ok(val.to_string());
                    }
                }
            }
            // If we found EOF but no unix socket, return error
            return Err(LauncherError::SocketPathNotFound);
        }
    }

    Err(LauncherError::Timeout)
}

impl Launcher {
    pub fn start(&mut self) -> Result<String, LauncherError> {
        let port_file = NamedTempFile::new()?;
        let port_filename = port_file.path().to_str().ok_or_else(|| {
            LauncherError::Io(io::Error::new(
                io::ErrorKind::InvalidData,
                "Failed to get port filename",
            ))
        })?;

        // WANDB_CORE_DEBUG env variable controls debug mode
        let debug = std::env::var("WANDB_CORE_DEBUG").unwrap_or_default();

        match fork() {
            Ok(Fork::Parent(_child)) => wait_for_socket(port_filename, time::Duration::from_secs(30)),
            Ok(Fork::Child) => {
                let mut command = Command::new(&self.command);
                command.arg("--port-filename").arg(port_filename);

                if debug == "1" || debug.eq_ignore_ascii_case("true") {
                    command.arg("--debug");
                }

                let child = command
                    .stdout(std::process::Stdio::inherit()) // Inherit stdout
                    .stderr(std::process::Stdio::inherit()) // Inherit stderr
                    .spawn()?; // Start the process

                // Store the child process handle
                self.child_process = Some(child);

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

impl Drop for Launcher {
    fn drop(&mut self) {
        if let Some(child) = &mut self.child_process {
            // Attempt to terminate the child process if it's still running
            match child.kill() {
                Ok(_) => tracing::info!("wandb-core process terminated."),
                Err(e) => tracing::error!("Failed to terminate wandb-core process: {}", e),
            }
        }
    }
}

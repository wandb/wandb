//! Launches the wandb-core service process and discovers its address.

use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use crate::error::{Error, Result};

/// How long to wait for wandb-core to write its port file.
const SERVICE_WAIT: Duration = Duration::from_secs(30);

/// How often to re-read the port file while waiting.
const POLL_INTERVAL: Duration = Duration::from_millis(20);

/// An address that wandb-core listens on.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum Transport {
    /// A Unix domain socket path.
    #[cfg(unix)]
    Unix(PathBuf),
    /// A TCP port on localhost.
    Tcp(u16),
}

/// A wandb-core process owned by this SDK.
#[derive(Debug)]
pub(crate) struct CoreProcess {
    child: Child,
    port_dir: PathBuf,
    pub transport: Transport,
}

impl CoreProcess {
    /// Starts wandb-core and waits for it to announce its address.
    ///
    /// The binary is taken from the `WANDB_CORE_PATH` environment variable
    /// if set, otherwise `wandb-core` is looked up on `PATH`.
    pub fn launch() -> Result<CoreProcess> {
        let program = std::env::var("WANDB_CORE_PATH")
            .ok()
            .filter(|p| !p.is_empty())
            .unwrap_or_else(|| "wandb-core".to_string());

        let pid = std::process::id();
        let port_dir =
            std::env::temp_dir().join(format!("wandb-rs-{}-{}", pid, crate::generate_id(8)));
        std::fs::create_dir_all(&port_dir)?;
        let port_file = port_dir.join(format!("port-{pid}.txt"));

        let mut command = Command::new(&program);
        command
            .arg("--port-filename")
            .arg(&port_file)
            .arg("--pid")
            .arg(pid.to_string())
            .stdin(Stdio::null());
        // The Rust std library has no Unix socket support on Windows.
        if cfg!(windows) {
            command.arg("--listen-on-localhost");
        }

        let mut child = command
            .spawn()
            .map_err(|e| Error::Service(format!("failed to start {program}: {e}")))?;
        match wait_for_port_file(&mut child, &port_file) {
            Ok(transport) => Ok(CoreProcess {
                child,
                port_dir,
                transport,
            }),
            Err(e) => {
                let _ = child.kill();
                let _ = child.wait();
                let _ = std::fs::remove_dir_all(&port_dir);
                Err(e)
            }
        }
    }

    /// Waits for the process to exit, killing it after `timeout`.
    pub fn join(&mut self, timeout: Duration) -> Result<()> {
        let deadline = Instant::now() + timeout;
        while Instant::now() < deadline {
            if self.child.try_wait()?.is_some() {
                return Ok(());
            }
            std::thread::sleep(POLL_INTERVAL);
        }
        tracing::warn!("wandb-core did not exit in {timeout:?}; killing it");
        self.child.kill()?;
        self.child.wait()?;
        Ok(())
    }
}

impl Drop for CoreProcess {
    fn drop(&mut self) {
        // Kill the process if it is still running; the normal path is a
        // teardown request followed by `join`.
        if matches!(self.child.try_wait(), Ok(None)) {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
        let _ = std::fs::remove_dir_all(&self.port_dir);
    }
}

/// Polls the port file until wandb-core finishes writing it.
fn wait_for_port_file(child: &mut Child, port_file: &Path) -> Result<Transport> {
    let deadline = Instant::now() + SERVICE_WAIT;
    while Instant::now() < deadline {
        if let Some(status) = child.try_wait()? {
            return Err(Error::Service(format!(
                "wandb-core exited before becoming ready: {status}"
            )));
        }
        if let Ok(contents) = std::fs::read_to_string(port_file) {
            if let Some(transport) = parse_port_file(&contents) {
                return Ok(transport);
            }
        }
        std::thread::sleep(POLL_INTERVAL);
    }
    Err(Error::Service(format!(
        "timed out after {SERVICE_WAIT:?} waiting for wandb-core to start"
    )))
}

/// Parses the port file written by wandb-core.
///
/// The file lists addresses as `unix=<path>` and `sock=<port>` lines and is
/// complete once the last line is `EOF`. Returns `None` if the file is
/// incomplete. Unix domain sockets are preferred where supported.
fn parse_port_file(contents: &str) -> Option<Transport> {
    let lines: Vec<&str> = contents.lines().collect();
    if lines.last() != Some(&"EOF") {
        return None;
    }
    let mut tcp = None;
    for line in lines {
        #[cfg(unix)]
        if let Some(path) = line.strip_prefix("unix=") {
            return Some(Transport::Unix(PathBuf::from(path)));
        }
        if let Some(port) = line.strip_prefix("sock=") {
            tcp = port.parse().ok().map(Transport::Tcp);
        }
    }
    tcp
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_port_file_incomplete() {
        assert_eq!(parse_port_file(""), None);
        assert_eq!(parse_port_file("unix=/tmp/sock\n"), None);
    }

    #[cfg(unix)]
    #[test]
    fn parse_port_file_prefers_unix() {
        assert_eq!(
            parse_port_file("unix=/tmp/sock\nsock=8080\nEOF"),
            Some(Transport::Unix(PathBuf::from("/tmp/sock")))
        );
    }

    #[test]
    fn parse_port_file_tcp_only() {
        assert_eq!(
            parse_port_file("sock=8080\nEOF"),
            Some(Transport::Tcp(8080))
        );
        assert_eq!(parse_port_file("sock=notaport\nEOF"), None);
    }
}

use core::panic;
use std::io;
use std::io::Result;
use std::net::TcpStream;

use sentry;
use std::env;
use std::path::Path;
use std::sync::Arc;
use tracing;

use crate::connection::{Connection, Interface};
use crate::launcher::Launcher;
use crate::run::Run;
use crate::settings::Settings;
use crate::wandb_internal;

pub struct Session {
    inner: Arc<SessionInner>,
}

#[derive(Debug)]
pub struct SessionInner {
    settings: Settings,
    addr: String,
}

pub fn get_core_address() -> String {
    let current_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("bin");
    let core_cmd = Path::new(&current_dir)
        .join("wandb-core")
        .into_os_string()
        .into_string()
        .expect("Failed to convert path to string");

    let mut launcher = Launcher {
        command: core_cmd,
        child_process: None,
    };
    let port = launcher.start();

    if let Ok(port) = port {
        format!("127.0.0.1:{}", port)
    } else {
        sentry::capture_error(&io::Error::new(
            io::ErrorKind::Other,
            "Couldn't get port from launcher...",
        ));
        tracing::error!("Couldn't get port from launcher...");
        panic!();
    }
}

impl SessionInner {
    pub fn connect(&self) -> TcpStream {
        tracing::debug!("Connecting to {}", self.addr);

        if let Ok(stream) = TcpStream::connect(&self.addr) {
            tracing::debug!("Stream peer address: {}", stream.peer_addr().unwrap());
            tracing::debug!("Stream local address: {}", stream.local_addr().unwrap());

            return stream;
        } else {
            sentry::capture_error(&io::Error::new(
                io::ErrorKind::Other,
                "Couldn't connect to server...",
            ));
            tracing::error!("Couldn't connect to server...");
            panic!();
        }
    }
}

impl Drop for SessionInner {
    fn drop(&mut self) {
        println!("Dropping session");
        // Send a teardown request to the wandb-core
        let conn = Connection::new(self.connect());
        let interface = Interface::new(conn);

        let inform_teardown_request = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::InformTeardown(
                    wandb_internal::ServerInformTeardownRequest {
                        exit_code: 0,
                        info: None,
                    },
                ),
            ),
        };
        tracing::debug!(
            "Sending inform teardown request {:?}",
            inform_teardown_request
        );
        interface
            .conn
            .send_message(&inform_teardown_request)
            .unwrap();
    }
}

impl Session {
    pub fn new(settings: Settings) -> Result<Session> {
        let addr = get_core_address();
        let inner = Arc::new(SessionInner { settings, addr });
        Ok(Session { inner })
    }

    pub fn init_run(&self, run_id: Option<String>) -> Result<Run> {
        let conn = Connection::new(self.inner.connect());
        let interface = Interface::new(conn);

        let mut run = Run {
            settings: self.inner.settings.clone(),
            interface,
            _session: Arc::clone(&self.inner),
        };

        run.init(run_id);

        Ok(run)
    }
}

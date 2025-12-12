use core::panic;
use std::io;
use std::io::Result;
use std::os::unix::net::UnixStream;

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
    socket_path: String,
}

pub fn get_core_socket_path() -> String {
    // TODO: get and set WANDB_CORE env variable to handle multiprocessing
    let current_dir =
        env::var("_WANDB_CORE_PATH").expect("Environment variable _WANDB_CORE_PATH is not set");
    let core_cmd = Path::new(&current_dir)
        .join("wandb-core")
        .into_os_string()
        .into_string()
        .expect("Failed to convert path to string");

    let mut launcher = Launcher {
        command: core_cmd,
        child_process: None,
    };
    let socket_path = launcher.start();

    if let Ok(socket_path) = socket_path {
        socket_path
    } else {
        sentry::capture_error(&io::Error::new(
            io::ErrorKind::Other,
            "Couldn't get Unix socket path from launcher...",
        ));
        tracing::error!("Couldn't get Unix socket path from launcher...");
        panic!();
    }
}

impl SessionInner {
    pub fn connect(&self) -> UnixStream {
        tracing::debug!("Connecting to Unix socket at {}", self.socket_path);

        if let Ok(stream) = UnixStream::connect(&self.socket_path) {
            tracing::debug!("Connected to wandb-core via Unix socket");

            return stream;
        } else {
            sentry::capture_error(&io::Error::new(
                io::ErrorKind::Other,
                "Couldn't connect to wandb-core Unix socket...",
            ));
            tracing::error!("Couldn't connect to wandb-core Unix socket at {}", self.socket_path);
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
            request_id: String::new(),
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
        let socket_path = get_core_socket_path();
        let inner = Arc::new(SessionInner { settings, socket_path });
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

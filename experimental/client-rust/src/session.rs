use pyo3::prelude::*;

use core::panic;
use std::io;
use std::net::TcpStream;

use sentry;
use std::env;
use std::path::Path;
use tracing;

use crate::connection::{Connection, Interface};
use crate::launcher::Launcher;
use crate::run::Run;
use crate::settings::Settings;

#[pyclass]
pub struct Session {
    settings: Settings,
    addr: String,
}

pub fn get_core_address() -> String {
    // TODO: get and set WANDB_CORE env variable to handle multiprocessing
    let current_dir =
        env::var("_WANDB_CORE_PATH").expect("Environment variable _WANDB_CORE_PATH is not set");
    // Create a Path from the current_dir
    let core_cmd = Path::new(&current_dir)
        .join("wandb-core")
        .into_os_string()
        .into_string()
        .expect("Failed to convert path to string");
    println!("Core command: {}", core_cmd);
    let launcher = Launcher { command: core_cmd };
    let port = launcher.start();
    // let port = "1";
    // format!("127.0.0.1:{:?}", port)
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

#[pymethods]
impl Session {
    #[new]
    pub fn new(settings: Settings) -> Session {
        let addr = get_core_address();
        let session = Session { settings, addr };
        tracing::debug!("Session created");

        session
    }

    pub fn init_run(&self, run_id: Option<String>) -> Run {
        let conn = Connection::new(self.connect());
        let interface = Interface::new(conn);

        let mut run = Run {
            settings: self.settings.clone(),
            interface,
        };

        run.init(run_id);

        return run;
    }
}

impl Session {
    fn connect(&self) -> TcpStream {
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

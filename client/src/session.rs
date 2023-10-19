use pyo3::prelude::*;

use core::panic;
use std::io;
use std::net::TcpStream;

use sentry;
use std::env;
use tracing;

use crate::wandb_internal::Settings as SettingsProto;

use crate::connection::{Connection, Interface};
use crate::launcher::Launcher;
use crate::run::Run;

// constants
const ENV_NEXUS_PATH: &str = "_WANDB_NEXUS_PATH";

#[pyclass]
#[derive(Clone)]
pub struct Settings {
    pub proto: SettingsProto,
}

#[pymethods]
impl Settings {
    #[new]
    pub fn new(
        base_url: Option<String>,
        stats_sample_rate_seconds: Option<f64>,
        stats_samples_to_average: Option<i32>,
        // log_internal: Option<String>,
        // sync_file: Option<String>,
    ) -> Settings {
        let proto = SettingsProto {
            base_url: Some(base_url.unwrap_or("https://api.wandb.ai".to_string())),
            stats_sample_rate_seconds: Some(stats_sample_rate_seconds.unwrap_or(5.0)),
            stats_samples_to_average: Some(stats_samples_to_average.unwrap_or(1)),
            log_internal: Some("wandb-internal.log".to_string()),
            sync_file: Some("lol.wandb".to_string()),
            ..Default::default()
        };
        Settings { proto }
    }

    // TODO: auto-generate all getters and setters
    #[getter]
    pub fn base_url(&self) -> String {
        self.proto.base_url.clone().unwrap()
    }

    #[getter]
    pub fn run_name(&self) -> String {
        self.proto.run_name.clone().unwrap()
    }

    #[getter]
    pub fn run_url(&self) -> String {
        self.proto.run_url.clone().unwrap()
    }

    #[getter]
    pub fn sync_dir(&self) -> String {
        self.proto.sync_dir.clone().unwrap()
    }
}

impl Settings {
    pub fn clone(&self) -> Settings {
        let proto = self.proto.clone();
        Settings { proto }
    }
}

#[pyclass]
pub struct Session {
    settings: Settings,
    addr: String,
}

pub fn get_nexus_address() -> String {
    // TODO: get and set WANDB_NEXUS env variable to handle multiprocessing
    let mut nexus_cmd = "wandb-nexus".to_string();
    let nexus_path = env::var(ENV_NEXUS_PATH);
    if nexus_path.is_ok() {
        nexus_cmd = nexus_path.unwrap();
    }

    let launcher = Launcher {
        command: nexus_cmd.to_string(),
    };
    let port = launcher.start();
    format!("127.0.0.1:{}", port)
}

#[pymethods]
impl Session {
    #[new]
    pub fn new(settings: Settings) -> Session {
        let addr = get_nexus_address();
        let session = Session { settings, addr };
        tracing::debug!("Session created");

        session
    }

    pub fn init_run(&mut self, run_id: Option<String>) -> Run {
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

use pyo3::prelude::*;

use std::net::TcpStream;

use rand::distributions::Alphanumeric;
use rand::Rng;
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
        // stats_sample_rate_seconds: Option<f64>,
        // stats_samples_to_average: Option<i32>,
        // log_internal: Option<String>,
        // sync_file: Option<String>,
    ) -> Settings {
        let proto = SettingsProto {
            base_url: Some(base_url.unwrap_or("https://api.wandb.ai".to_string())),
            // stats_sample_rate_seconds: Some(1.0),
            // stats_samples_to_average: Some(1),
            log_internal: Some("wandb-internal.log".to_string()),
            sync_file: Some("lol.wandb".to_string()),
            ..Default::default()
        };
        Settings { proto }
    }

    #[getter]
    fn base_url(&self) -> String {
        self.proto.base_url.clone().unwrap()
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

#[pyfunction]
pub fn generate_run_id(run_id: Option<String>) -> String {
    match run_id {
        Some(id) => id,
        None => {
            let rand_string: String = rand::thread_rng()
                .sample_iter(&Alphanumeric)
                .take(6)
                .map(char::from)
                .collect();
            rand_string
        }
    }
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

    pub fn init_run(&self, run_id: Option<String>) -> Run {
        // generate a random alphnumeric string of length 6 if run_id is None:
        let run_id = generate_run_id(run_id);
        tracing::debug!("Creating new run {}", run_id);

        let conn = Connection::new(self.connect());
        let interface = Interface::new(conn);

        let mut run = Run {
            id: run_id,
            settings: self.settings.clone(),
            interface,
        };

        run.init();
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
            tracing::error!("Couldn't connect to server...");
            panic!();
        }
    }
}

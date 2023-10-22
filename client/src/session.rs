use pyo3::prelude::*;

use core::panic;
use std::io;
use std::net::TcpStream;

use sentry;
use std::env;
use tracing;

use crate::connection::{Connection, Interface};
use crate::launcher::Launcher;
use crate::run::Run;
use crate::settings::Settings;

// constants
const ENV_NEXUS_PATH: &str = "_WANDB_NEXUS_PATH";

#[cfg_attr(feature = "py", pyclass)]
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

#[cfg_eval]
#[cfg_attr(feature = "py", pymethods)]
impl Session {
    #[cfg_attr(feature = "py", new)]
    pub fn new(settings: Settings) -> Session {
        let addr = get_nexus_address();
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

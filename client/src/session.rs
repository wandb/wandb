use std::net::TcpStream;

use rand::distributions::Alphanumeric;
use rand::Rng;
use std::env;

use crate::wandb_internal::Settings;
// use pyo3::prelude::*;

use crate::connection::{Connection, Interface};
use crate::run::Run;
use crate::launcher::Launcher;

// constants
const ENV_NEXUS_PATH: &str = "_WANDB_NEXUS_PATH";

// #[pyclass]
pub struct Session {
    settings: Settings,
    addr: String,
}

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

    let launcher = Launcher{
        command: nexus_cmd.to_string(),
    };
    let port = launcher.start();
    format!("127.0.0.1:{}", port)
}

// #[pymethods]
impl Session {
    pub fn new(settings: Settings) -> Session {
        let addr = get_nexus_address();
        let session = Session {
            settings: settings,
            addr: addr,
        };
        // println!("Session created {:?}", session.settings);
        session
    }

    fn connect(&self) -> TcpStream {
        println!("Connecting to {}", self.addr);

        if let Ok(stream) = TcpStream::connect(&self.addr) {
            println!("{}", stream.peer_addr().unwrap());
            println!("{}", stream.local_addr().unwrap());

            return stream;
        } else {
            println!("Couldn't connect to server...");
            panic!();
        }
    }

    pub fn new_run(&self, run_id: Option<String>) -> Run {
        // generate a random alphnumeric string of length 6 if run_id is None:
        let run_id = generate_run_id(run_id);
        println!("Creating new run {}", run_id);

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

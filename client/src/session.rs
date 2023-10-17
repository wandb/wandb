use std::net::TcpStream;

use rand::distributions::Alphanumeric;
use rand::Rng;

use crate::wandb_internal::Settings;
// use pyo3::prelude::*;

use crate::connection::Connection;
use crate::run::Run;

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

// #[pymethods]
impl Session {
    pub fn new(settings: Settings, addr: String) -> Session {
        let session = Session { settings, addr };
        // println!("Session created {:?} {}", session.settings, session.addr);

        // todo: start Nexus

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

        let run = Run {
            id: run_id,
            settings: self.settings.clone(),
            conn: conn,
        };

        run.init();
        return run;
    }
}

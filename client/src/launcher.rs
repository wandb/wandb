use fork::{fork, Fork};
use sentry;
use std::fs;
use std::process::Command;
use std::{thread, time};
use tempfile::NamedTempFile;
use tracing;

pub struct Launcher {
    pub command: String,
}

fn wait_for_port(port_filename: &str) -> i32 {
    let delay_time = time::Duration::from_millis(20);
    loop {
        thread::sleep(delay_time);
        let contents =
            fs::read_to_string(port_filename).expect("Should have been able to read the file");
        let lines = contents.lines().collect::<Vec<_>>();
        if lines.last().copied() == Some("EOF") {
            for item in lines.iter() {
                match item.split_once("=") {
                    None => continue,
                    Some((param, val)) => {
                        if param == "sock" {
                            let my_int = val.to_string().parse::<i32>().unwrap();
                            return my_int;
                        }
                    }
                }
            }
        }
    }
}

impl Launcher {
    pub fn start(&self) -> i32 {
        let port_file = NamedTempFile::new().expect("tempfile should be created");
        let port_filename = port_file.path().as_os_str().to_str().unwrap();
        match fork() {
            Ok(Fork::Parent(_child)) => {
                let port = wait_for_port(port_filename);
                return port;
            }
            Ok(Fork::Child) => {
                let _command = Command::new(self.command.clone())
                    .arg("--port-filename")
                    .arg(port_filename)
                    .output();
            }
            Err(e) => {
                sentry::capture_error(&std::io::Error::new(
                    std::io::ErrorKind::Other,
                    format!("Fork failed: {}", e),
                ));
                tracing::error!("Fork failed");
            }
        }
        0
    }
}

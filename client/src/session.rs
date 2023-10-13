use byteorder::{LittleEndian, WriteBytesExt};
use std::{
    io::{BufWriter, Write},
    net::TcpStream,
};

use prost::Message;
use rand::distributions::Alphanumeric;
use rand::Rng;

use crate::wandb_internal::{self, Settings};

pub struct Session {
    settings: Settings,
    addr: String,
}

pub struct Run {
    pub id: String,
    pub settings: Settings,
    stream: TcpStream,
}

#[repr(C)]
struct Header {
    magic: u8,
    data_length: u32,
}

fn generate_run_id(run_id: Option<String>) -> String {
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

impl Session {
    pub fn new(settings: Settings, addr: String) -> Session {
        let session = Session { settings, addr };
        println!("Session created {:?} {}", session.settings, session.addr);

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

        let run = Run {
            id: run_id,
            settings: self.settings.clone(),
            stream: self.connect(),
        };

        run.init();
        return run;
    }
}

impl Run {
    fn send_message(&self, message: &wandb_internal::ServerRequest) {
        // marshal the protobuf message
        let mut buf = Vec::new();
        message.encode(&mut buf).unwrap();

        // let c = vec![];  // Placeholder for some kind of Write implementation, e.g., a TCP stream
        let mut writer = BufWriter::with_capacity(16384, &self.stream);

        let header = Header {
            magic: b'W',
            data_length: buf.len() as u32,
        };

        // Write the header to the writer
        writer.write_u8(header.magic).unwrap();
        writer
            .write_u32::<LittleEndian>(header.data_length)
            .unwrap();

        // Write the protobuf to the writer
        writer.write_all(&buf).unwrap();
    }

    fn init(&self) {
        println!("Initializing run {}", self.id);

        let server_inform_init_request = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::InformInit(
                    wandb_internal::ServerInformInitRequest {
                        settings: Some(self.settings.clone()),
                        info: Some(wandb_internal::RecordInfo {
                            stream_id: self.id.clone(),
                            ..Default::default()
                        }),
                    },
                ),
            ),
        };

        self.send_message(&server_inform_init_request);

        let server_publish_run = wandb_internal::Record {
            record_type: Some(wandb_internal::record::RecordType::Run(
                wandb_internal::RunRecord {
                    run_id: self.id.clone(),
                    // display_name: "gooba-gaba".to_string(),
                    info: Some(wandb_internal::RecordInfo {
                        stream_id: self.id.clone(),
                        ..Default::default()
                    }),
                    ..Default::default()
                },
            )),
            info: Some(wandb_internal::RecordInfo {
                stream_id: self.id.clone(),
                ..Default::default()
            }),
            ..Default::default()
        };
        let server_publish_run_request = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::RecordPublish(
                    server_publish_run,
                ),
            ),
        };

        self.send_message(&server_publish_run_request);
    }

    pub fn log(&self) {
        println!("Logging to run {}", self.id);
    }

    pub fn finish(&self) {
        println!("Finishing run {}", self.id);
    }
}

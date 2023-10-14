use byteorder::{LittleEndian, WriteBytesExt};
use std::{
    collections::HashMap,
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
        println!(
            "Sending message to run {}",
            self.stream.peer_addr().unwrap()
        );
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

        let server_publish_run_request = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::RecordCommunicate(
                    wandb_internal::Record {
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
                    },
                ),
            ),
        };

        self.send_message(&server_publish_run_request);

        let server_publish_run_start = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::RecordCommunicate(
                    wandb_internal::Record {
                        record_type: Some(wandb_internal::record::RecordType::Request(
                            wandb_internal::Request {
                                request_type: Some(wandb_internal::request::RequestType::RunStart(
                                    wandb_internal::RunStartRequest {
                                        run: Some(wandb_internal::RunRecord {
                                            ..Default::default()
                                        }),
                                        info: Some(wandb_internal::RequestInfo {
                                            stream_id: self.id.clone(),
                                            ..Default::default()
                                        }),
                                    },
                                )),
                            },
                        )),
                        info: Some(wandb_internal::RecordInfo {
                            stream_id: self.id.clone(),
                            ..Default::default()
                        }),
                        ..Default::default()
                    },
                ),
            ),
        };
        self.send_message(&server_publish_run_start);
    }

    pub fn log(&self, data: HashMap<String, f64>) {
        println!("Logging to run {}", self.id);

        let history_record = wandb_internal::HistoryRecord {
            item: data
                .iter()
                .map(|(k, v)| wandb_internal::HistoryItem {
                    key: k.clone(),
                    value_json: v.to_string(),
                    ..Default::default()
                })
                .collect(),
            ..Default::default()
        };

        let record = wandb_internal::Record {
            record_type: Some(wandb_internal::record::RecordType::History(history_record)),
            info: Some(wandb_internal::RecordInfo {
                stream_id: self.id.clone(),
                ..Default::default()
            }),
            ..Default::default()
        };

        let message = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::RecordPublish(record),
            ),
        };

        self.send_message(&message);

    }

    pub fn finish(&self) {
        println!("Finishing run {}", self.id);

        let finish_record = wandb_internal::RunExitRecord {
            exit_code: 0,
            info: Some(wandb_internal::RecordInfo {
                stream_id: self.id.clone(),
                ..Default::default()
            }),
            ..Default::default()
        };

        let record = wandb_internal::Record {
            record_type: Some(wandb_internal::record::RecordType::Exit(finish_record)),
            info: Some(wandb_internal::RecordInfo {
                stream_id: self.id.clone(),
                ..Default::default()
            }),
            ..Default::default()
        };

        let message = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::RecordCommunicate(record),
            ),
        };
        self.send_message(&message);

        let shutdown_request = wandb_internal::Request {
            request_type: Some(wandb_internal::request::RequestType::Shutdown(
                wandb_internal::ShutdownRequest {
                    info: Some(wandb_internal::RequestInfo {
                        stream_id: self.id.clone(),
                        ..Default::default()
                    }),
                },
            )),
        };
        let shutdown_record = wandb_internal::Record {
            record_type: Some(wandb_internal::record::RecordType::Request(shutdown_request)),
            info: Some(wandb_internal::RecordInfo {
                stream_id: self.id.clone(),
                ..Default::default()
            }),
            ..Default::default()
        };
        let message = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::RecordCommunicate(
                    shutdown_record,
                ),
            ),
        };
        self.send_message(&message);

        let inform_finish_request = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::InformFinish(
                    wandb_internal::ServerInformFinishRequest {
                        info: Some(wandb_internal::RecordInfo {
                            stream_id: self.id.clone(),
                            ..Default::default()
                        })
                    },
                ),
            ),
        };
        self.send_message(&inform_finish_request);

        loop {}
    }
}

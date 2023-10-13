use byteorder::{LittleEndian, WriteBytesExt};
use std::{
    io::{BufWriter, Write},
    net::TcpStream,
};

use prost::Message;

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

impl Session {
    pub fn new(settings: Settings, addr: String) -> Session {
        let session = Session { settings, addr };
        println!("Session created {:?} {}", session.settings, session.addr);

        // todo: start Nexus

        session
    }

    fn connect(&self) -> TcpStream {
        println!("Connecting to {}", self.addr);

        // let stream = TcpStream::connect(&self.addr).unwrap();

        if let Ok(stream) = TcpStream::connect(&self.addr) {
            println!("{}", stream.peer_addr().unwrap());
            println!("{}", stream.local_addr().unwrap());

            return stream;
        } else {
            println!("Couldn't connect to server...");
            panic!();
        }

        // let mut buffer = [0u8; 1024];
        // match stream.read(&mut buffer) {
        //     Ok(size) => {
        //         let response = String::from_utf8_lossy(&buffer[..size]);
        //         println!("Received from server: {}", response);
        //     }
        //     Err(e) => {
        //         eprintln!("Error reading from socket: {}", e);
        //     }
        // }
    }

    pub fn new_run(&self, run_id: Option<String>) -> Run {
        println!("Creating new run");

        let run = Run {
            id: run_id.unwrap_or("a1b2c3".to_string()),
            settings: self.settings.clone(),
            stream: self.connect(),
        };

        run.init();
        return run;
    }
}

impl Run {
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

        // marshal the protobuf
        let mut buf = Vec::new();
        server_inform_init_request.encode(&mut buf).unwrap();

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

    pub fn log(&self) {
        println!("Logging to run {}", self.id);
    }

    pub fn finish(&self) {
        println!("Finishing run {}", self.id);
    }
}

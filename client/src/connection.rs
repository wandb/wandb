use crate::session::generate_run_id;
use crate::wandb_internal;
use byteorder::{LittleEndian, WriteBytesExt};
use prost::Message;
use std::{
    collections::HashMap,
    io::{BufWriter, Write},
    net::TcpStream,
    sync::mpsc::{channel, Sender},
    sync::{Arc, Mutex},
};

#[repr(C)]
struct Header {
    magic: u8,
    data_length: u32,
}

pub struct Interface {
    pub conn: Connection,
    // hashmap string -> channel
    pub handles: Arc<Mutex<HashMap<String, Sender<wandb_internal::Result>>>>,
}

impl Interface {
    pub fn new(conn: Connection) -> Self {
        let handles = Arc::new(Mutex::new(HashMap::new()));
        let interface = Interface {
            handles: handles.clone(),
            conn: conn.clone(),
        };

        std::thread::spawn(move || conn.recv(&handles));

        interface
    }
}

pub struct Connection {
    pub stream: TcpStream,
}

impl Connection {
    pub fn new(stream: TcpStream) -> Self {
        let conn = Connection { stream };

        conn
    }

    pub fn clone(&self) -> Self {
        let stream = self.stream.try_clone().unwrap();
        Connection { stream }
    }

    pub fn send_and_recv_message(
        &mut self,
        message: &mut wandb_internal::Record,
        handles: &mut Arc<Mutex<HashMap<String, Sender<wandb_internal::Result>>>>,
    ) -> wandb_internal::Result {
        // todo: generate unique id for this message
        let uuid = generate_run_id(None);
        // message.server_request_type.RecordCommunicate.control.mailbox_slot = uuid.clone();
        // update the message with the uuid
        // let
        if let Some(ref mut control) = message.control {
            control.mailbox_slot = uuid.clone();
            control.req_resp = true;
        } else {
            message.control = Some(wandb_internal::Control {
                mailbox_slot: uuid.clone(),
                req_resp: true,
                ..Default::default()
            });
        }

        let message = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::RecordCommunicate(
                    message.clone(),
                ),
            ),
        };

        let (sender, receiver) = channel();
        println!(">>> Inserting sender {:?} for uuid {}", sender, uuid);
        handles.lock().unwrap().insert(uuid, sender);
        println!(">>> Handles: {:?}", handles);
        self.send_message(&message).unwrap();

        println!(">>> Waiting for result...");
        return receiver.recv().unwrap();
    }

    pub fn send_message(&self, message: &wandb_internal::ServerRequest) -> Result<(), ()> {
        // marshal the protobuf message
        let mut buf = Vec::new();
        message.encode(&mut buf).unwrap();

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
        writer.flush().unwrap();
        Ok(())
    }

    pub fn recv_message(&self) -> Vec<u8> {
        // Read the magic byte
        let mut magic_byte = [0; 1];
        let bytes_read = std::io::Read::read(&mut &self.stream, &mut magic_byte).unwrap();
        println!("Read {} bytes", bytes_read);
        println!("Magic byte: {:?}", magic_byte);

        if magic_byte != [b'W'] {
            println!("Magic number is not 'W'");
            return vec![];
        }

        let mut body_length_bytes = [0; 4];
        std::io::Read::read(&mut &self.stream, &mut body_length_bytes).unwrap();
        let body_length = u32::from_le_bytes(body_length_bytes);
        println!("Body length: {}", body_length);

        // Read the body
        let mut body = vec![0; body_length as usize];
        std::io::Read::read(&mut &self.stream, &mut body).unwrap();
        println!("Body: {:?}", body);

        body
    }

    pub fn recv(&self, handles: &Arc<Mutex<HashMap<String, Sender<wandb_internal::Result>>>>) {
        println!(
            "Receiving messages from run {}",
            self.stream.peer_addr().unwrap()
        );
        loop {
            println!("Waiting for message...");
            let msg = self.recv_message();
            if msg.len() == 0 {
                println!("Connection closed");
                break;
            }
            let proto_message = wandb_internal::ServerResponse::decode(msg.as_slice()).unwrap();
            println!("Received message: {:?}", proto_message);
            println!("Handles: {:?}", handles);

            match proto_message.server_response_type {
                Some(wandb_internal::server_response::ServerResponseType::ResultCommunicate(
                    result,
                )) => {
                    // Handle ResultCommunicate variant here
                    // You can access fields of Result if needed
                    println!(">>>> Received ResultCommunicate: {:?}", result);

                    if let Some(control) = &result.control {
                        let mailbox_slot = &control.mailbox_slot;
                        println!("Mailbox slot: {}", mailbox_slot);
                        println!("Handles: {:?}", handles);
                        if let Some(sender) = handles.lock().unwrap().get(mailbox_slot) {
                            println!("Sending result to sender {:?}", sender);
                            // todo: use the result type of the result_communicate
                            // let cloned_result = result.clone();
                            sender.send(result).expect("Failed to send result")
                        } else {
                            println!("Failed to send result to sender");
                        }
                    } else {
                        println!("Received ResultCommunicate without control")
                    }
                }
                Some(_) => {
                    println!("Received message with unknown type");
                }
                None => {
                    println!("Received message without type")
                }
            }
            // let handle_id
        }
    }
}

use crate::run::generate_id;
use crate::wandb_internal;
use byteorder::{LittleEndian, WriteBytesExt};
use prost::Message;
use std::{
    collections::HashMap,
    io::{BufWriter, Write},
    os::unix::net::UnixStream,
    // sync::mpsc::{channel, Receiver, RecvError, Sender},
    sync::mpsc::{channel, Sender},
    sync::{Arc, Mutex},
};
use tracing;

#[repr(C)]
struct Header {
    magic: u8,
    data_length: u32,
}

#[derive(Debug)]
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

#[derive(Debug)]
pub struct Connection {
    pub stream: UnixStream,
}

impl Connection {
    pub fn new(stream: UnixStream) -> Self {
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
        // TODO: generate unique id for this message
        let uuid = generate_id(16);
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
            request_id: String::new(),
        };

        let (sender, receiver) = channel();
        tracing::debug!(">>> Inserting sender {:?} for uuid {}", sender, uuid);
        handles.lock().unwrap().insert(uuid, sender);
        tracing::debug!(">>> Handles: {:?}", handles);
        self.send_message(&message).unwrap();
        tracing::debug!(">>> Waiting for result...");
        // TODO: this should be recv_timeout(timeout)
        return receiver.recv().unwrap();
        // return receiver
        //     .recv_timeout(std::time::Duration::from_secs(10))
        //     .unwrap();
    }

    pub fn send_message(&self, message: &wandb_internal::ServerRequest) -> Result<(), ()> {
        // marshal the protobuf message
        let mut buf = Vec::new();
        message.encode(&mut buf).unwrap();

        tracing::debug!(
            "Sending message {:?} to wandb-core via Unix socket",
            message
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
        tracing::debug!("Read {} bytes", bytes_read);
        tracing::debug!("Magic byte: {:?}", magic_byte);

        if magic_byte != [b'W'] {
            // this errot means that the connection was closed
            tracing::debug!("Magic number is not 'W': {}", magic_byte[0]);
            tracing::debug!("Connection closed");
            return vec![];
        }

        let mut body_length_bytes = [0; 4];
        std::io::Read::read(&mut &self.stream, &mut body_length_bytes).unwrap();
        let body_length = u32::from_le_bytes(body_length_bytes);
        tracing::debug!("Body length: {}", body_length);

        // Read the body
        let mut body = vec![0; body_length as usize];
        std::io::Read::read(&mut &self.stream, &mut body).unwrap();
        tracing::debug!("Body: {:?}", body);

        body
    }

    pub fn recv(&self, handles: &Arc<Mutex<HashMap<String, Sender<wandb_internal::Result>>>>) {
        tracing::debug!("Receiving messages from wandb-core via Unix socket");
        loop {
            tracing::debug!("Waiting for message...");
            let msg = self.recv_message();
            if msg.len() == 0 {
                tracing::debug!("Connection closed");
                break;
            }
            let proto_message = wandb_internal::ServerResponse::decode(msg.as_slice()).unwrap();
            tracing::debug!("Received message: {:?}", proto_message);
            tracing::debug!("Handles: {:?}", handles);

            match proto_message.server_response_type {
                Some(wandb_internal::server_response::ServerResponseType::ResultCommunicate(
                    result,
                )) => {
                    // Handle ResultCommunicate variant here
                    // You can access fields of Result if needed
                    tracing::debug!(">>>> Received ResultCommunicate: {:?}", result);

                    if let Some(control) = &result.control {
                        let mailbox_slot = &control.mailbox_slot;
                        tracing::debug!("Mailbox slot: {}", mailbox_slot);
                        tracing::debug!("Handles: {:?}", handles);
                        if let Some(sender) = handles.lock().unwrap().get(mailbox_slot) {
                            tracing::debug!("Sending result to sender {:?}", sender);
                            // TODO: use the result type of the result_communicate
                            // let cloned_result = result.clone();
                            sender.send(result).expect("Failed to send result")
                        } else {
                            tracing::warn!("Failed to send result to sender");
                        }
                    } else {
                        tracing::warn!("Received ResultCommunicate without control");
                    }
                }
                Some(_) => {
                    tracing::warn!("Received message with unknown type");
                }
                _ => {
                    tracing::warn!("Received message without type")
                }
            }
            // let handle_id
        }
    }
}

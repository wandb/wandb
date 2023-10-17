use crate::wandb_internal;
use byteorder::{LittleEndian, WriteBytesExt};
use prost::Message;
use std::{
    collections::HashMap,
    io::{BufWriter, Write},
    net::TcpStream,
    sync::mpsc::Sender,
};
use crate::session::generate_run_id;

#[repr(C)]
struct Header {
    magic: u8,
    data_length: u32,
}

pub struct Connection {
    pub stream: TcpStream,
    // hashmap string -> channel
    pub handles: HashMap<String, Sender<wandb_internal::Result>>,
}

impl Connection {
    pub fn clone(&self) -> Self {
        Connection {
            stream: self.stream.try_clone().unwrap(),
            handles: self.handles.clone(),
        }
    }

    pub fn send_and_recv_message(
        &self,
        message: &wandb_internal::ServerRequest,
    ) -> Sender<wandb_internal::Result> {
        // todo: generate unique id for this message
        let uuid = generate_run_id(None);
        // message.server_request_type.RecordCommunicate.control.mailbox_slot = uuid.clone();
        // update the message with the uuid
        // let


        self.send_message(message).unwrap();
        self.recv();
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

    pub fn new(stream: TcpStream) -> Self {
        let conn = Connection {
            stream,
            handles: HashMap::new(),
        };

        // spin up a thread to listen for messages from the server on the connection
        let mut conn_clone = conn.clone();
        std::thread::spawn(move || conn_clone.recv());

        conn
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

    pub fn recv(&mut self) {
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

            // let handle_id
        }
    }
}

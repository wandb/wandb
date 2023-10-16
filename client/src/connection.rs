use crate::wandb_internal;
use byteorder::{LittleEndian, WriteBytesExt};
use bytes;
use prost::Message;
use std::{
    io::{BufWriter, Write},
    net::TcpStream,
};

#[repr(C)]
struct Header {
    magic: u8,
    data_length: u32,
}

pub struct Connection {
    pub stream: TcpStream,
}

impl Connection {
    pub fn clone(&self) -> Self {
        Connection {
            stream: self.stream.try_clone().unwrap(),
        }
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
        let conn = Connection { stream };

        // spin up a thread to listen for messages from the server on the connection
        let mut conn_clone = conn.clone();
        std::thread::spawn(move || conn_clone.recv());

        conn
    }

    pub fn recv(&mut self) {
        println!(
            "Receiving messages from run {}",
            self.stream.peer_addr().unwrap()
        );
        // let mut tokenizer = Tokenizer::new();
        // let buffer = bytes::BytesMut::new();
        loop {
            println!("Waiting for message...");
            let mut data = vec![0; 16384];
            let bytes_read = std::io::Read::read(&mut self.stream, &mut data).unwrap();
            println!("Read {} bytes", bytes_read);
            println!("Data: {:?}", data);
            // exit once connection is closed
            if bytes_read == 0 {
                println!("Connection closed");
                break;
            }
        }
    }
}

// pub struct Tokenizer {}

// impl Tokenizer {
//     pub fn new() -> Self {
//         Tokenizer {}
//     }

//     pub fn split<'a>(&'a mut self, data: &'a [u8]) -> Option<&[u8]> {
//         if data.len() < 5 {
//             return None;
//         }
//         let magic = data[0];
//         let data_length = bytes::Buf::get_u32_le(&mut &data[1..5]) as usize;
//         if magic != b'W' || data.len() < 5 + data_length {
//             // log::error!("Invalid header or not enough data");
//             return None;
//         }
//         Some(&data[5..5 + data_length])
//     }
// }

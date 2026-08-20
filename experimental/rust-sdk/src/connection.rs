//! Connection to wandb-core: message framing and request-response matching.
//!
//! Every message in both directions is framed as a 5-byte header — the magic
//! byte `'W'` and a little-endian u32 payload length — followed by a
//! protobuf-encoded [`pb::ServerRequest`] or [`pb::ServerResponse`].
//!
//! Requests that expect a response carry a unique `request_id`; a background
//! reader thread matches incoming responses to waiting callers by that ID.

use std::collections::HashMap;
use std::io::{self, BufReader, Read, Write};
use std::net::TcpStream;
#[cfg(unix)]
use std::os::unix::net::UnixStream;
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

use prost::Message;

use crate::error::{Error, Result};
use crate::launcher::Transport;
use crate::wandb_internal as pb;

const FRAME_MAGIC: u8 = b'W';
const FRAME_HEADER_LEN: usize = 5;

/// Requests waiting for a response, keyed by request ID.
///
/// `None` after the connection has closed, so that no request can start
/// waiting for a response that will never arrive.
type Pending = Arc<Mutex<Option<HashMap<String, mpsc::Sender<pb::ServerResponse>>>>>;

/// A connection to a wandb-core service.
///
/// Cheap operations happen on the caller's thread; a single background
/// thread reads responses and delivers them to waiting requests.
#[derive(Debug)]
pub(crate) struct Connection {
    writer: Mutex<Socket>,
    control: Socket,
    pending: Pending,
    reader: Option<JoinHandle<()>>,
}

impl Connection {
    /// Connects to wandb-core at the given address.
    pub fn connect(transport: &Transport) -> Result<Connection> {
        let socket = Socket::connect(transport)?;
        let pending: Pending = Arc::new(Mutex::new(Some(HashMap::new())));

        let reader_socket = socket.try_clone()?;
        let writer_socket = socket.try_clone()?;
        let reader_pending = Arc::clone(&pending);
        let reader = std::thread::Builder::new()
            .name("wandb-reader".to_string())
            .spawn(move || read_responses(reader_socket, reader_pending))?;

        Ok(Connection {
            writer: Mutex::new(writer_socket),
            control: socket,
            pending,
            reader: Some(reader),
        })
    }

    /// Sends a request without waiting for a response.
    pub fn notify(&self, request: pb::ServerRequest) -> Result<()> {
        let frame = encode_frame(&request);
        let mut writer = self.writer.lock().expect("wandb writer lock poisoned");
        writer.write_all(&frame)?;
        Ok(())
    }

    /// Sends a request and waits for the matching response.
    ///
    /// `key` is the ID the response will carry: `request_id` for most
    /// requests, or the echoed `_info.stream_id` for authenticate requests,
    /// which are the one kind that wandb-core answers without a
    /// `request_id`.
    pub fn request(
        &self,
        key: &str,
        request: pb::ServerRequest,
        timeout: Duration,
    ) -> Result<pb::ServerResponse> {
        let (sender, receiver) = mpsc::channel();
        match self
            .pending
            .lock()
            .expect("wandb pending lock poisoned")
            .as_mut()
        {
            Some(pending) => pending.insert(key.to_string(), sender),
            None => return Err(Error::ConnectionClosed),
        };

        if let Err(e) = self.notify(request) {
            self.forget(key);
            return Err(e);
        }

        match receiver.recv_timeout(timeout) {
            Ok(response) => match response.server_response_type {
                Some(pb::server_response::ServerResponseType::ErrorResponse(e)) => {
                    Err(Error::Server(e.message))
                }
                _ => Ok(response),
            },
            Err(mpsc::RecvTimeoutError::Timeout) => {
                self.forget(key);
                // Tell wandb-core the response is no longer needed.
                let _ = self.notify(pb::ServerRequest {
                    server_request_type: Some(pb::server_request::ServerRequestType::Cancel(
                        pb::ServerCancelRequest {
                            request_id: key.to_string(),
                        },
                    )),
                    ..Default::default()
                });
                Err(Error::Timeout(timeout))
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => Err(Error::ConnectionClosed),
        }
    }

    /// Closes the connection and waits for the reader thread to exit.
    pub fn close(&mut self) {
        let _ = self.control.shutdown();
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
    }

    fn forget(&self, key: &str) {
        if let Some(pending) = self
            .pending
            .lock()
            .expect("wandb pending lock poisoned")
            .as_mut()
        {
            pending.remove(key);
        }
    }
}

impl Drop for Connection {
    fn drop(&mut self) {
        self.close();
    }
}

/// Reads responses until the connection closes, delivering each to the
/// request waiting for it.
fn read_responses(socket: Socket, pending: Pending) {
    let mut reader = BufReader::new(socket);
    loop {
        let body = match read_frame(&mut reader) {
            Ok(Some(body)) => body,
            Ok(None) => break,
            Err(e) => {
                tracing::debug!("wandb-core connection error: {e}");
                break;
            }
        };
        let response = match pb::ServerResponse::decode(body.as_slice()) {
            Ok(response) => response,
            Err(e) => {
                tracing::warn!("failed to decode wandb-core response: {e}");
                break;
            }
        };
        let key = response_key(&response);
        let sender = pending
            .lock()
            .expect("wandb pending lock poisoned")
            .as_mut()
            .and_then(|pending| pending.remove(&key));
        match sender {
            // The receiver may have already timed out; that's fine.
            Some(sender) => drop(sender.send(response)),
            None => tracing::debug!("dropping unsolicited response with id {key:?}"),
        }
    }
    // Mark the connection closed and wake up all waiting requests by
    // dropping their senders. Requests arriving later fail immediately.
    *pending.lock().expect("wandb pending lock poisoned") = None;
}

/// Returns the ID identifying the request a response answers.
fn response_key(response: &pb::ServerResponse) -> String {
    if !response.request_id.is_empty() {
        return response.request_id.clone();
    }
    // Authenticate responses carry no request_id; wandb-core echoes the
    // request's `_info`, in which we send the request ID as the stream ID.
    if let Some(pb::server_response::ServerResponseType::AuthenticateResponse(auth)) =
        &response.server_response_type
    {
        return auth.info.clone().unwrap_or_default().stream_id;
    }
    String::new()
}

/// Encodes a request as a length-prefixed frame.
fn encode_frame(request: &pb::ServerRequest) -> Vec<u8> {
    let body_len = request.encoded_len();
    let mut frame = Vec::with_capacity(FRAME_HEADER_LEN + body_len);
    frame.push(FRAME_MAGIC);
    frame.extend_from_slice(&(body_len as u32).to_le_bytes());
    request
        .encode(&mut frame)
        .expect("Vec<u8> writes cannot fail");
    frame
}

/// Reads one frame, returning `None` on a clean end of stream.
fn read_frame(reader: &mut impl Read) -> io::Result<Option<Vec<u8>>> {
    let mut header = [0u8; FRAME_HEADER_LEN];
    match reader.read_exact(&mut header) {
        Ok(()) => {}
        Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => return Ok(None),
        Err(e) => return Err(e),
    }
    if header[0] != FRAME_MAGIC {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!("invalid magic byte in frame header: {:#x}", header[0]),
        ));
    }
    let body_len = u32::from_le_bytes(header[1..].try_into().unwrap());
    let mut body = vec![0u8; body_len as usize];
    reader.read_exact(&mut body)?;
    Ok(Some(body))
}

/// A stream socket connected to wandb-core.
#[derive(Debug)]
enum Socket {
    #[cfg(unix)]
    Unix(UnixStream),
    Tcp(TcpStream),
}

impl Socket {
    fn connect(transport: &Transport) -> io::Result<Socket> {
        match transport {
            #[cfg(unix)]
            Transport::Unix(path) => UnixStream::connect(path).map(Socket::Unix),
            Transport::Tcp(port) => TcpStream::connect(("127.0.0.1", *port)).map(Socket::Tcp),
        }
    }

    fn try_clone(&self) -> io::Result<Socket> {
        match self {
            #[cfg(unix)]
            Socket::Unix(s) => s.try_clone().map(Socket::Unix),
            Socket::Tcp(s) => s.try_clone().map(Socket::Tcp),
        }
    }

    fn shutdown(&self) -> io::Result<()> {
        match self {
            #[cfg(unix)]
            Socket::Unix(s) => s.shutdown(std::net::Shutdown::Both),
            Socket::Tcp(s) => s.shutdown(std::net::Shutdown::Both),
        }
    }
}

impl Read for Socket {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        match self {
            #[cfg(unix)]
            Socket::Unix(s) => s.read(buf),
            Socket::Tcp(s) => s.read(buf),
        }
    }
}

impl Write for Socket {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        match self {
            #[cfg(unix)]
            Socket::Unix(s) => s.write(buf),
            Socket::Tcp(s) => s.write(buf),
        }
    }

    fn flush(&mut self) -> io::Result<()> {
        match self {
            #[cfg(unix)]
            Socket::Unix(s) => s.flush(),
            Socket::Tcp(s) => s.flush(),
        }
    }
}

#[cfg(all(test, unix))]
mod tests {
    use std::os::unix::net::UnixListener;

    use super::*;

    /// A minimal fake wandb-core: replies to inform_init and authenticate,
    /// stays silent on everything else.
    fn fake_core() -> (tempfile_path::TempSocket, Transport) {
        let socket = tempfile_path::TempSocket::new();
        let listener = UnixListener::bind(&socket.path).unwrap();
        let transport = Transport::Unix(socket.path.clone());
        std::thread::spawn(move || {
            let (stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            let mut writer = stream;
            while let Ok(Some(body)) = read_frame(&mut reader) {
                let request = pb::ServerRequest::decode(body.as_slice()).unwrap();
                use pb::server_request::ServerRequestType;
                use pb::server_response::ServerResponseType;
                let response_type = match request.server_request_type {
                    Some(ServerRequestType::InformInit(_)) => Some(
                        ServerResponseType::InformInitResponse(pb::ServerInformInitResponse {}),
                    ),
                    Some(ServerRequestType::Authenticate(auth)) => {
                        // wandb-core echoes _info but not request_id here.
                        let mut response = pb::ServerResponse {
                            server_response_type: Some(ServerResponseType::AuthenticateResponse(
                                pb::ServerAuthenticateResponse {
                                    default_entity: "fake-entity".to_string(),
                                    error_status: String::new(),
                                    info: auth.info,
                                },
                            )),
                            ..Default::default()
                        };
                        let frame = encode_response(&mut response, "");
                        writer.write_all(&frame).unwrap();
                        continue;
                    }
                    _ => None, // never respond
                };
                if let Some(response_type) = response_type {
                    let mut response = pb::ServerResponse {
                        server_response_type: Some(response_type),
                        ..Default::default()
                    };
                    let frame = encode_response(&mut response, &request.request_id);
                    writer.write_all(&frame).unwrap();
                }
            }
        });
        (socket, transport)
    }

    fn encode_response(response: &mut pb::ServerResponse, request_id: &str) -> Vec<u8> {
        response.request_id = request_id.to_string();
        let mut frame = vec![FRAME_MAGIC];
        frame.extend_from_slice(&(response.encoded_len() as u32).to_le_bytes());
        response.encode(&mut frame).unwrap();
        frame
    }

    fn inform_init_request(request_id: &str) -> pb::ServerRequest {
        pb::ServerRequest {
            request_id: request_id.to_string(),
            server_request_type: Some(pb::server_request::ServerRequestType::InformInit(
                pb::ServerInformInitRequest::default(),
            )),
        }
    }

    #[test]
    fn request_matches_response_by_id() {
        let (_socket, transport) = fake_core();
        let conn = Connection::connect(&transport).unwrap();
        let response = conn
            .request(
                "req-1",
                inform_init_request("req-1"),
                Duration::from_secs(5),
            )
            .unwrap();
        assert_eq!(response.request_id, "req-1");
    }

    #[test]
    fn authenticate_matches_response_by_stream_id() {
        let (_socket, transport) = fake_core();
        let conn = Connection::connect(&transport).unwrap();
        let request = pb::ServerRequest {
            server_request_type: Some(pb::server_request::ServerRequestType::Authenticate(
                pb::ServerAuthenticateRequest {
                    api_key: "key".to_string(),
                    base_url: "http://localhost".to_string(),
                    info: Some(pb::RecordInfo {
                        stream_id: "auth-1".to_string(),
                        ..Default::default()
                    }),
                },
            )),
            ..Default::default()
        };
        let response = conn
            .request("auth-1", request, Duration::from_secs(5))
            .unwrap();
        match response.server_response_type {
            Some(pb::server_response::ServerResponseType::AuthenticateResponse(auth)) => {
                assert_eq!(auth.default_entity, "fake-entity");
            }
            other => panic!("unexpected response: {other:?}"),
        }
    }

    #[test]
    fn request_times_out_when_unanswered() {
        let (_socket, transport) = fake_core();
        let conn = Connection::connect(&transport).unwrap();
        let request = pb::ServerRequest {
            request_id: "req-1".to_string(),
            server_request_type: Some(pb::server_request::ServerRequestType::InformFinish(
                pb::ServerInformFinishRequest::default(),
            )),
        };
        let result = conn.request("req-1", request, Duration::from_millis(50));
        assert!(matches!(result, Err(Error::Timeout(_))));
    }

    #[test]
    fn pending_requests_fail_when_connection_closes() {
        let (_socket, transport) = fake_core();
        let mut conn = Connection::connect(&transport).unwrap();
        let closer = std::thread::spawn({
            let control = conn.control.try_clone().unwrap();
            move || {
                std::thread::sleep(Duration::from_millis(50));
                control.shutdown().unwrap();
            }
        });
        let request = pb::ServerRequest {
            request_id: "req-1".to_string(),
            server_request_type: Some(pb::server_request::ServerRequestType::InformFinish(
                pb::ServerInformFinishRequest::default(),
            )),
        };
        let result = conn.request("req-1", request, Duration::from_secs(30));
        assert!(matches!(result, Err(Error::ConnectionClosed)));
        closer.join().unwrap();
        conn.close();

        // Requests after the connection closed fail fast, not by timeout.
        let request = pb::ServerRequest {
            request_id: "req-2".to_string(),
            server_request_type: Some(pb::server_request::ServerRequestType::InformFinish(
                pb::ServerInformFinishRequest::default(),
            )),
        };
        let result = conn.request("req-2", request, Duration::from_secs(30));
        assert!(matches!(result, Err(Error::ConnectionClosed)));
    }

    /// A socket path in the temp dir, removed on drop.
    mod tempfile_path {
        use std::path::PathBuf;

        pub struct TempSocket {
            pub path: PathBuf,
        }

        impl TempSocket {
            pub fn new() -> TempSocket {
                TempSocket {
                    path: std::env::temp_dir()
                        .join(format!("wandb-test-{}.sock", crate::generate_id(8))),
                }
            }
        }

        impl Drop for TempSocket {
            fn drop(&mut self) {
                let _ = std::fs::remove_file(&self.path);
            }
        }
    }
}

use std::io::{Read, Write};
use std::net::TcpListener;
use std::sync::{Arc, Mutex};
use std::thread;

/// Starts an HTTP server serving a file
/// Returns (server_url, request_counter)
///
/// The server handles:
/// - HEAD requests
/// - Range requests
/// - Full file requests
///
/// The request counter tracks the number of HTTP requests received.
/// Callers can choose to ignore the counter if they don't need it.
pub fn start_http_server(file_path: &str) -> (String, Arc<Mutex<usize>>) {
    // Read the file contents
    let file_contents = std::fs::read(file_path).unwrap();
    let file_size = file_contents.len();

    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let url = format!("http://127.0.0.1:{}/test.parquet", addr.port());

    // Share file contents across all request handlers
    let contents_arc = Arc::new(file_contents);
    let counter = Arc::new(Mutex::new(0usize));
    let counter_clone = counter.clone();

    thread::spawn(move || {
        for stream in listener.incoming() {
            let contents = Arc::clone(&contents_arc);
            let size = file_size;
            let counter = counter_clone.clone();

            thread::spawn(move || {
                let mut stream = match stream {
                    Ok(s) => s,
                    Err(_) => return,
                };

                // Increment request counter
                *counter.lock().unwrap() += 1;

                // Set read/write timeouts
                stream.set_read_timeout(Some(std::time::Duration::from_secs(5))).ok();
                stream.set_write_timeout(Some(std::time::Duration::from_secs(5))).ok();

                // Read request with size limit
                let mut buffer = Vec::new();
                let mut temp = [0u8; 1024];
                loop {
                    match stream.read(&mut temp) {
                        Ok(0) => break,
                        Ok(n) => {
                            buffer.extend_from_slice(&temp[..n]);
                            // Check if we've received the full headers
                            if buffer.windows(4).any(|w| w == b"\r\n\r\n") {
                                break;
                            }
                            // Prevent reading too much
                            if buffer.len() > 8192 {
                                break;
                            }
                        }
                        Err(_) => break,
                    }
                }

                let request = String::from_utf8_lossy(&buffer);

                // Handle HEAD request
                if request.starts_with("HEAD") {
                    let response = format!(
                        "HTTP/1.1 200 OK\r\n\
                         Content-Length: {}\r\n\
                         Content-Type: application/octet-stream\r\n\
                         Accept-Ranges: bytes\r\n\
                         Connection: keep-alive\r\n\
                         \r\n",
                        size
                    );
                    let _ = stream.write_all(response.as_bytes());
                    let _ = stream.flush();
                    return;
                }

                // Handle Range request (case-insensitive)
                if let Some(range_line) = request.lines().find(|l| l.to_lowercase().starts_with("range:")) {
                    if let Some(range_str) = range_line.split(':').nth(1) {
                        let range_str = range_str.trim();
                        if let Some(bytes_part) = range_str.strip_prefix("bytes=") {
                            let parts: Vec<&str> = bytes_part.split('-').collect();
                            if parts.len() == 2 {
                                let start: usize = parts[0].trim().parse().unwrap_or(0);
                                let end_str = parts[1].trim();
                                let end: usize = if end_str.is_empty() {
                                    size - 1
                                } else {
                                    end_str.parse().unwrap_or(size - 1)
                                };
                                let end = std::cmp::min(end, size - 1);

                                if start <= end && start < size {
                                    let data = &contents[start..=end];
                                    let response = format!(
                                        "HTTP/1.1 206 Partial Content\r\n\
                                         Content-Length: {}\r\n\
                                         Content-Range: bytes {}-{}/{}\r\n\
                                         Content-Type: application/octet-stream\r\n\
                                         Accept-Ranges: bytes\r\n\
                                         Connection: keep-alive\r\n\
                                         \r\n",
                                        data.len(),
                                        start,
                                        end,
                                        size
                                    );
                                    let _ = stream.write_all(response.as_bytes());
                                    let _ = stream.write_all(data);
                                    let _ = stream.flush();
                                    return;
                                }
                            }
                        }
                    }
                }

                // Default: return full file
                let response = format!(
                    "HTTP/1.1 200 OK\r\n\
                     Content-Length: {}\r\n\
                     Content-Type: application/octet-stream\r\n\
                     Accept-Ranges: bytes\r\n\
                     Connection: keep-alive\r\n\
                     \r\n",
                    size
                );
                let _ = stream.write_all(response.as_bytes());
                let _ = stream.write_all(&contents);
                let _ = stream.flush();
            });
        }
    });

    // Give server time to start and bind
    thread::sleep(std::time::Duration::from_millis(200));

    (url, counter)
}

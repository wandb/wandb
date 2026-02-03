use bytes::Bytes;
use parquet::errors::Result as ParquetResult;
use parquet::file::reader::{ChunkReader, Length};
use std::io::{Error as IoError, ErrorKind, Read, Result as IoResult, Seek, SeekFrom};
use std::sync::{Arc, RwLock};

pub struct HttpFileReader {
    client: Arc<reqwest::blocking::Client>,
    url: Arc<String>,
    file_size: i64,
    position: i64,
    // Shared buffer across all readers for the same file
    read_buffer: Arc<RwLock<Option<ReadBuffer>>>,
}

// Buffer for small sequential reads via Read trait
struct ReadBuffer {
    data: Vec<u8>,
    start_offset: i64,
}

impl HttpFileReader {
    /// Create a new HTTP file reader
    /// Makes a HEAD request to get the file size
    pub fn new(url: String) -> IoResult<Self> {
        // Configure client for better performance
        let client = Arc::new(
            reqwest::blocking::Client::builder()
                .pool_max_idle_per_host(100)
                .pool_idle_timeout(std::time::Duration::from_secs(90))
                .timeout(std::time::Duration::from_secs(30))
                .tcp_keepalive(std::time::Duration::from_secs(60))
                .tcp_nodelay(true)
                .build()
                .map_err(|e| IoError::new(ErrorKind::Other, e))?,
        );

        // Get file size with HEAD request
        let response = client
            .head(&url)
            .send()
            .map_err(|e| IoError::new(ErrorKind::Other, e))?;

        if !response.status().is_success() {
            return Err(IoError::new(
                ErrorKind::Other,
                format!("Failed to get file size: status {}", response.status()),
            ));
        }

        let file_size = response
            .headers()
            .get(reqwest::header::CONTENT_LENGTH)
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse::<i64>().ok())
            .ok_or_else(|| IoError::new(ErrorKind::Other, "Missing Content-Length header"))?;

        Ok(HttpFileReader {
            client,
            url: Arc::new(url),
            file_size,
            position: 0,
            read_buffer: Arc::new(RwLock::new(None)),
        })
    }

    /// Create a new reader with shared client and buffer
    fn new_with_shared(&self) -> Self {
        HttpFileReader {
            client: Arc::clone(&self.client),
            url: Arc::clone(&self.url),
            file_size: self.file_size,
            position: 0,
            read_buffer: Arc::clone(&self.read_buffer), // Share the buffer!
        }
    }

    /// Read at specific offset - similar to Go's ReadAt
    pub fn read_at(&self, buf: &mut [u8], offset: i64) -> IoResult<usize> {
        if offset < 0 {
            return Err(IoError::new(ErrorKind::InvalidInput, "negative offset"));
        }

        if buf.is_empty() {
            return Ok(0);
        }

        // Calculate range - matches Go implementation
        let start = offset;
        let end = std::cmp::min(offset + buf.len() as i64, self.file_size);

        if start >= self.file_size {
            return Ok(0); // EOF
        }

        // Make HTTP range request - note: HTTP range is inclusive on both ends
        // So bytes=0-99 means 100 bytes (0 through 99)
        let range_header = format!("bytes={}-{}", start, end - 1);

        let response = self
            .client
            .get(self.url.as_ref())
            .header(reqwest::header::RANGE, range_header)
            .send()
            .map_err(|e| IoError::new(ErrorKind::Other, e))?;

        let status = response.status();
        if !status.is_success() && status != reqwest::StatusCode::PARTIAL_CONTENT {
            return Err(IoError::new(
                ErrorKind::Other,
                format!("HTTP error: {}", status),
            ));
        }

        // Read response body directly
        let bytes = response
            .bytes()
            .map_err(|e| IoError::new(ErrorKind::Other, e))?;

        let bytes_read = std::cmp::min(bytes.len(), buf.len());
        buf[..bytes_read].copy_from_slice(&bytes[..bytes_read]);

        Ok(bytes_read)
    }
}

impl Read for HttpFileReader {
    fn read(&mut self, buf: &mut [u8]) -> IoResult<usize> {
        if buf.is_empty() || self.position >= self.file_size {
            return Ok(0);
        }

        // Try to serve from the shared buffer first
        {
            let buffer_lock = self.read_buffer.read().unwrap();
            if let Some(ref buffer) = *buffer_lock {
                let buffer_end = buffer.start_offset + buffer.data.len() as i64;
                if self.position >= buffer.start_offset && self.position < buffer_end {
                    let offset = (self.position - buffer.start_offset) as usize;
                    let available = buffer.data.len() - offset;
                    let to_copy = std::cmp::min(buf.len(), available);

                    buf[..to_copy].copy_from_slice(&buffer.data[offset..offset + to_copy]);
                    self.position += to_copy as i64;

                    return Ok(to_copy);
                }
            }
        } // Release read lock

        // ALWAYS fetch at least BUFFER_SIZE to reduce HTTP requests
        const BUFFER_SIZE: usize = 1024 * 1024; // Increase to 1MB - fetch more per request

        // Fetch BUFFER_SIZE or remaining file, whichever is smaller
        let remaining = (self.file_size - self.position) as usize;
        let fetch_size = std::cmp::min(BUFFER_SIZE, remaining);

        if fetch_size == 0 {
            return Ok(0); // EOF
        }

        let mut fetch_buf = vec![0u8; fetch_size];
        let n = self.read_at(&mut fetch_buf, self.position)?;
        fetch_buf.truncate(n);

        if n == 0 {
            return Ok(0); // EOF
        }

        // ALWAYS store in shared buffer (even for small fetches)
        // This ensures subsequent reads from ANY reader can use it
        {
            let mut buffer_lock = self.read_buffer.write().unwrap();
            *buffer_lock = Some(ReadBuffer {
                data: fetch_buf.clone(),
                start_offset: self.position,
            });
        }

        // Copy what the caller requested
        let to_copy = std::cmp::min(buf.len(), n);
        buf[..to_copy].copy_from_slice(&fetch_buf[..to_copy]);
        self.position += to_copy as i64;

        Ok(to_copy)
    }
}

impl Seek for HttpFileReader {
    fn seek(&mut self, pos: SeekFrom) -> IoResult<u64> {
        let new_position = match pos {
            SeekFrom::Start(offset) => offset as i64,
            SeekFrom::Current(offset) => self.position + offset,
            SeekFrom::End(offset) => self.file_size + offset,
        };

        if new_position < 0 {
            return Err(IoError::new(
                ErrorKind::InvalidInput,
                format!("seek before start: {} < 0", new_position),
            ));
        }

        if new_position > self.file_size {
            return Err(IoError::new(
                ErrorKind::InvalidInput,
                format!("seek beyond end: {} > {}", new_position, self.file_size),
            ));
        }

        self.position = new_position;

        // Note: We don't invalidate the shared buffer on seek
        // Multiple readers may be seeking around, and the buffer can serve them all

        Ok(self.position as u64)
    }
}

impl Length for HttpFileReader {
    fn len(&self) -> u64 {
        self.file_size as u64
    }
}

impl ChunkReader for HttpFileReader {
    type T = HttpFileReader;

    fn get_read(&self, start: u64) -> ParquetResult<Self::T> {
        let mut reader = self.new_with_shared();
        reader
            .seek(SeekFrom::Start(start))
            .map_err(|e| parquet::errors::ParquetError::External(Box::new(e)))?;
        Ok(reader)
    }

    fn get_bytes(&self, start: u64, length: usize) -> ParquetResult<Bytes> {
        // Direct read at offset - no caching, no prefetching
        // This matches Go's simple approach
        let mut buf = vec![0u8; length];
        let n = self
            .read_at(&mut buf, start as i64)
            .map_err(|e| parquet::errors::ParquetError::External(Box::new(e)))?;

        buf.truncate(n);
        Ok(Bytes::from(buf))
    }
}

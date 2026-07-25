//! Ack channel: the oracle (and later the Rust app) reports every processed
//! Update and completed View over a FIFO, letting the harness step scenarios
//! on facts instead of timers. Protocol (see `core/internal/leet/testmode.go`):
//!
//! ```text
//! u <seq> <msgType>   after each Update, e.g. "u 12 tea.KeyPressMsg"
//! v <seq>             after each View; seq = latest Update seq rendered
//! ```

use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::sync::mpsc;
use std::time::{Duration, Instant};

use anyhow::{Context, Result};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Ack {
    Update { seq: u64, msg_type: String },
    View { seq: u64 },
}

pub struct AckListener {
    rx: mpsc::Receiver<Ack>,
    /// Everything seen so far, for error reports and await bookkeeping.
    pub history: Vec<Ack>,
}

impl AckListener {
    /// Create the FIFO at `path` and start the reader thread. Must be called
    /// before the oracle process is spawned (the oracle opens the write end
    /// lazily on its first ack).
    pub fn new(path: &Path) -> Result<Self> {
        nix::unistd::mkfifo(path, nix::sys::stat::Mode::S_IRWXU)
            .with_context(|| format!("mkfifo {}", path.display()))?;

        // Non-blocking read end: opening succeeds with no writer, and reads
        // return 0 until one connects.
        let fd = nix::fcntl::open(
            path,
            nix::fcntl::OFlag::O_RDONLY | nix::fcntl::OFlag::O_NONBLOCK,
            nix::sys::stat::Mode::empty(),
        )
        .with_context(|| format!("open fifo {}", path.display()))?;
        let mut file = File::from(fd);

        let (tx, rx) = mpsc::channel();
        std::thread::Builder::new()
            .name("ack-listener".into())
            .spawn(move || {
                let mut pending = Vec::new();
                let mut buf = [0u8; 4096];
                loop {
                    match file.read(&mut buf) {
                        // 0 = no writer yet, or writer went away.
                        Ok(0) => std::thread::sleep(Duration::from_millis(2)),
                        Ok(n) => {
                            pending.extend_from_slice(&buf[..n]);
                            while let Some(pos) = pending.iter().position(|&b| b == b'\n') {
                                let line: Vec<u8> = pending.drain(..=pos).collect();
                                if let Some(ack) = parse_ack(&line[..line.len() - 1])
                                    && tx.send(ack).is_err()
                                {
                                    return; // harness dropped the receiver
                                }
                            }
                        }
                        Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                            std::thread::sleep(Duration::from_millis(2));
                        }
                        Err(_) => return,
                    }
                }
            })
            .context("spawn ack-listener thread")?;

        Ok(AckListener {
            rx,
            history: Vec::new(),
        })
    }

    /// Drain without blocking.
    pub fn drain(&mut self) {
        while let Ok(ack) = self.rx.try_recv() {
            self.history.push(ack);
        }
    }

    /// Wait until an Update ack whose type contains `type_fragment` has been
    /// seen `count` times since `since_idx` (an index into `history`).
    /// Returns the seq of the last matching update.
    pub fn await_update(
        &mut self,
        type_fragment: &str,
        count: usize,
        since_idx: usize,
        timeout: Duration,
    ) -> Result<u64> {
        let deadline = Instant::now() + timeout;
        loop {
            self.drain();
            let mut seen = 0;
            let mut last_seq = 0;
            for ack in &self.history[since_idx..] {
                if let Ack::Update { seq, msg_type } = ack
                    && msg_type.contains(type_fragment)
                {
                    seen += 1;
                    last_seq = *seq;
                    if seen >= count {
                        return Ok(last_seq);
                    }
                }
            }
            let _ = last_seq;
            if Instant::now() >= deadline {
                anyhow::bail!(
                    "timeout awaiting {count}x update ack containing {type_fragment:?} \
                     (saw {seen}); ack tail: {:?}",
                    self.tail(12)
                );
            }
            match self.rx.recv_timeout(Duration::from_millis(10)) {
                Ok(ack) => self.history.push(ack),
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    anyhow::bail!("ack listener thread died")
                }
            }
        }
    }

    /// Wait for a View ack with seq >= `min_seq` (a frame reflecting that
    /// update has been rendered).
    pub fn await_view(&mut self, min_seq: u64, timeout: Duration) -> Result<()> {
        let deadline = Instant::now() + timeout;
        loop {
            self.drain();
            if self
                .history
                .iter()
                .any(|a| matches!(a, Ack::View { seq } if *seq >= min_seq))
            {
                return Ok(());
            }
            if Instant::now() >= deadline {
                anyhow::bail!(
                    "timeout awaiting view ack with seq >= {min_seq}; ack tail: {:?}",
                    self.tail(12)
                );
            }
            match self.rx.recv_timeout(Duration::from_millis(10)) {
                Ok(ack) => self.history.push(ack),
                Err(mpsc::RecvTimeoutError::Timeout) => {}
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    anyhow::bail!("ack listener thread died")
                }
            }
        }
    }

    /// Wait until no ack of any kind arrives for `quiet`, capped by `timeout`.
    pub fn await_quiet(&mut self, quiet: Duration, timeout: Duration) -> Result<()> {
        let deadline = Instant::now() + timeout;
        let mut last_len = {
            self.drain();
            self.history.len()
        };
        let mut quiet_since = Instant::now();
        loop {
            std::thread::sleep(Duration::from_millis(5));
            self.drain();
            if self.history.len() != last_len {
                last_len = self.history.len();
                quiet_since = Instant::now();
            } else if quiet_since.elapsed() >= quiet {
                return Ok(());
            }
            if Instant::now() >= deadline {
                // Quiet never settled — report rather than silently snapshot.
                anyhow::bail!("ack stream never went quiet for {quiet:?} within {timeout:?}");
            }
        }
    }

    pub fn tail(&self, n: usize) -> Vec<String> {
        self.history
            .iter()
            .rev()
            .take(n)
            .rev()
            .map(|a| match a {
                Ack::Update { seq, msg_type } => format!("u {seq} {msg_type}"),
                Ack::View { seq } => format!("v {seq}"),
            })
            .collect()
    }
}

fn parse_ack(line: &[u8]) -> Option<Ack> {
    let s = std::str::from_utf8(line).ok()?.trim();
    let mut parts = s.splitn(3, ' ');
    match (parts.next()?, parts.next()) {
        ("u", Some(seq)) => Some(Ack::Update {
            seq: seq.parse().ok()?,
            msg_type: parts.next().unwrap_or("").to_string(),
        }),
        ("v", Some(seq)) => Some(Ack::View {
            seq: seq.parse().ok()?,
        }),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_protocol_lines() {
        assert_eq!(
            parse_ack(b"u 12 tea.KeyPressMsg"),
            Some(Ack::Update {
                seq: 12,
                msg_type: "tea.KeyPressMsg".into()
            })
        );
        assert_eq!(parse_ack(b"v 12"), Some(Ack::View { seq: 12 }));
        assert_eq!(parse_ack(b"garbage"), None);
    }
}

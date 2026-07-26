//! PTY process driver: spawns the oracle in a pseudo-terminal, runs the
//! reader loop that feeds both the responder persona and the `avt` screen
//! parser, and exposes input/resize/snapshot/shutdown to the scenario
//! runner.

use std::io::{Read, Write};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use portable_pty::{CommandBuilder, PtySize, native_pty_system};

use crate::grid::{Grid, grid_from_avt};
use crate::persona::{Persona, PersonaBackground, QueryLogEntry};

pub struct PtyProcess {
    master: Box<dyn portable_pty::MasterPty + Send>,
    child: Box<dyn portable_pty::Child + Send + Sync>,
    writer: Arc<Mutex<Box<dyn Write + Send>>>,
    state: Arc<SharedState>,
}

struct SharedState {
    vt: Mutex<avt::Vt>,
    persona: Mutex<Persona>,
    /// Raw output byte count — used to detect output quiescence.
    raw_len: Mutex<usize>,
    /// Rolling tail of raw output for error reports.
    raw_tail: Mutex<Vec<u8>>,
}

pub struct SpawnSpec {
    pub program: String,
    pub args: Vec<String>,
    pub cwd: std::path::PathBuf,
    pub env: Vec<(String, String)>,
    pub cols: u16,
    pub rows: u16,
    pub background: PersonaBackground,
}

const RAW_TAIL_CAP: usize = 4096;

impl PtyProcess {
    pub fn spawn(spec: &SpawnSpec) -> Result<Self> {
        let pty_system = native_pty_system();
        let pair = pty_system
            .openpty(PtySize {
                rows: spec.rows,
                cols: spec.cols,
                pixel_width: 0,
                pixel_height: 0,
            })
            .context("openpty")?;

        let mut cmd = CommandBuilder::new(&spec.program);
        cmd.args(&spec.args);
        cmd.cwd(&spec.cwd);
        // A minimal, frozen environment: nothing from the host leaks in.
        cmd.env_clear();
        cmd.env("TERM", "xterm-256color");
        cmd.env("COLORTERM", "truecolor");
        cmd.env("CLICOLOR_FORCE", "1");
        // Signed-off DIVERGENCE (PARITY.md, console timestamps): the Rust
        // port renders timestamps in UTC (std has no tz API); pinning TZ
        // makes the Go oracle render UTC too.
        cmd.env("TZ", "UTC");
        for (k, v) in &spec.env {
            cmd.env(k, v);
        }

        let child = pair
            .slave
            .spawn_command(cmd)
            .context("spawn oracle in pty")?;
        drop(pair.slave);

        let mut reader = pair.master.try_clone_reader().context("clone pty reader")?;
        let writer: Arc<Mutex<Box<dyn Write + Send>>> = Arc::new(Mutex::new(
            pair.master.take_writer().context("take pty writer")?,
        ));

        let state = Arc::new(SharedState {
            vt: Mutex::new(
                avt::Vt::builder()
                    .size(spec.cols as usize, spec.rows as usize)
                    .build(),
            ),
            persona: Mutex::new(Persona::new(spec.background)),
            raw_len: Mutex::new(0),
            raw_tail: Mutex::new(Vec::new()),
        });

        {
            let state = Arc::clone(&state);
            let writer = Arc::clone(&writer);
            std::thread::Builder::new()
                .name("pty-reader".into())
                .spawn(move || {
                    let mut buf = [0u8; 8192];
                    // Carry incomplete UTF-8 between reads for avt.
                    let mut utf8_pending: Vec<u8> = Vec::new();
                    loop {
                        let n = match reader.read(&mut buf) {
                            Ok(0) | Err(_) => return,
                            Ok(n) => n,
                        };
                        let chunk = &buf[..n];

                        // Persona first: replies are time-sensitive.
                        let replies = state.persona.lock().unwrap().scan(chunk);
                        if !replies.is_empty() {
                            let mut w = writer.lock().unwrap();
                            let _ = w.write_all(&replies);
                            let _ = w.flush();
                        }

                        // Screen parser (needs valid UTF-8 boundaries).
                        utf8_pending.extend_from_slice(chunk);
                        let valid_up_to = match std::str::from_utf8(&utf8_pending) {
                            Ok(_) => utf8_pending.len(),
                            Err(e) => e.valid_up_to(),
                        };
                        if valid_up_to > 0 {
                            let s = std::str::from_utf8(&utf8_pending[..valid_up_to]).unwrap();
                            state.vt.lock().unwrap().feed_str(s);
                            utf8_pending.drain(..valid_up_to);
                        }
                        // Genuinely invalid bytes would stall the pending
                        // buffer; drop them if it grows past a UTF-8 max
                        // sequence length.
                        if utf8_pending.len() > 4 {
                            utf8_pending.clear();
                        }

                        *state.raw_len.lock().unwrap() += n;
                        let mut tail = state.raw_tail.lock().unwrap();
                        tail.extend_from_slice(chunk);
                        if tail.len() > RAW_TAIL_CAP {
                            let excess = tail.len() - RAW_TAIL_CAP;
                            tail.drain(..excess);
                        }
                    }
                })
                .context("spawn pty-reader thread")?;
        }

        Ok(PtyProcess {
            master: pair.master,
            child,
            writer,
            state,
        })
    }

    pub fn write_input(&self, bytes: &[u8]) -> Result<()> {
        let mut w = self.writer.lock().unwrap();
        w.write_all(bytes).context("write pty input")?;
        w.flush().context("flush pty input")
    }

    /// TIOCSWINSZ + SIGWINCH to the child.
    pub fn resize(&self, cols: u16, rows: u16) -> Result<()> {
        self.master
            .resize(PtySize {
                rows,
                cols,
                pixel_width: 0,
                pixel_height: 0,
            })
            .context("pty resize")?;
        self.state
            .vt
            .lock()
            .unwrap()
            .resize(cols as usize, rows as usize);
        Ok(())
    }

    /// Wait until raw output has been stable for `quiet` (capped by
    /// `timeout`, which is NOT an error — rendering may legitimately be
    /// finished already).
    pub fn await_output_quiet(&self, quiet: Duration, timeout: Duration) {
        let deadline = Instant::now() + timeout;
        let mut last = *self.state.raw_len.lock().unwrap();
        let mut stable_since = Instant::now();
        while Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(5));
            let now_len = *self.state.raw_len.lock().unwrap();
            if now_len != last {
                last = now_len;
                stable_since = Instant::now();
            } else if stable_since.elapsed() >= quiet {
                return;
            }
        }
    }

    pub fn snapshot(&self) -> Grid {
        grid_from_avt(&self.state.vt.lock().unwrap())
    }

    pub fn persona_log(&self) -> Vec<QueryLogEntry> {
        self.state.persona.lock().unwrap().log.clone()
    }

    pub fn raw_tail(&self) -> String {
        String::from_utf8_lossy(&self.state.raw_tail.lock().unwrap())
            .escape_debug()
            .to_string()
    }

    /// Quit politely (`q`), then escalate to kill.
    pub fn shutdown(&mut self) -> Result<()> {
        let _ = self.write_input(b"q");
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            match self.child.try_wait() {
                Ok(Some(_)) => return Ok(()),
                Ok(None) => {
                    if Instant::now() >= deadline {
                        self.child.kill().ok();
                        let _ = self.child.wait();
                        return Ok(());
                    }
                    std::thread::sleep(Duration::from_millis(20));
                }
                Err(e) => return Err(e).context("try_wait oracle"),
            }
        }
    }

    pub fn is_alive(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }
}

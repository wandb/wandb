//! The responder persona: a frozen table of answers to the terminal
//! capability queries that Bubble Tea v2 (and the app itself) emit at
//! startup.
//!
//! The persona is deliberately minimal — a plain VT220-ish terminal with
//! truecolor SGR support and nothing fancy. Advertising more (kitty
//! keyboard, mode 2027 grapheme clustering, in-band resize) would change
//! the oracle's input encoding and width measurement, breaking scripted
//! input and frame parity. The Rust app under test runs with the same
//! forced-off hooks so neither side depends on terminal replies.
//!
//! Every recognized query is logged; the null test surfaces queries that
//! are unanswered-and-unknown, which is how new bubbletea versions
//! announce themselves.

/// Background color the persona reports via OSC 10/11, mirroring the Go
/// side's `WANDB_LEET_TEST` frozen values (`styles.go initTerminalBg`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PersonaBackground {
    Dark,
    Light,
}

impl PersonaBackground {
    fn osc11_reply(self) -> &'static [u8] {
        match self {
            // #1e1e1e / #fafafa, doubled to 16-bit per OSC 11 convention.
            PersonaBackground::Dark => b"\x1b]11;rgb:1e1e/1e1e/1e1e\x1b\\",
            PersonaBackground::Light => b"\x1b]11;rgb:fafa/fafa/fafa\x1b\\",
        }
    }

    fn osc10_reply(self) -> &'static [u8] {
        match self {
            PersonaBackground::Dark => b"\x1b]10;rgb:e5e5/e5e5/e5e5\x1b\\",
            PersonaBackground::Light => b"\x1b]10;rgb:1e1e/1e1e/1e1e\x1b\\",
        }
    }
}

/// One recognized query and the reply we sent (None = declined by silence).
#[derive(Debug, Clone)]
pub struct QueryLogEntry {
    pub query: String,
    pub reply: Option<String>,
}

/// Streaming scanner over the oracle's output. Queries can be split across
/// read chunks, so a tail of unprocessed bytes is carried between calls.
pub struct Persona {
    background: PersonaBackground,
    tail: Vec<u8>,
    pub log: Vec<QueryLogEntry>,
}

/// Upper bound on carried tail; must cover the longest recognizable query
/// (XTGETTCAP scans up to 64 bytes for its terminator).
const MAX_TAIL_LEN: usize = 128;

enum Classified {
    /// A recognized query of `len` bytes starting at the scan position.
    Query { len: usize, name: String },
    /// Might be a query, but more bytes are needed to decide.
    Partial,
    /// Not a query we recognize.
    No,
}

impl Persona {
    pub fn new(background: PersonaBackground) -> Self {
        Persona {
            background,
            tail: Vec::new(),
            log: Vec::new(),
        }
    }

    /// Scan a chunk of oracle output; returns reply bytes to write to the
    /// PTY (empty if none). The chunk is scanned independently of the
    /// display stream — the caller feeds the same bytes to the screen
    /// parser.
    pub fn scan(&mut self, chunk: &[u8]) -> Vec<u8> {
        self.tail.extend_from_slice(chunk);
        let mut replies = Vec::new();

        let mut i = 0;
        while i < self.tail.len() {
            if self.tail[i] != 0x1b {
                i += 1;
                continue;
            }
            match classify(&self.tail[i..]) {
                Classified::Query { len, name } => {
                    let reply = self.reply_for(&self.tail[i..i + len]);
                    self.log.push(QueryLogEntry {
                        query: name,
                        reply: reply
                            .as_ref()
                            .map(|r| String::from_utf8_lossy(r).escape_debug().to_string()),
                    });
                    if let Some(r) = reply {
                        replies.extend_from_slice(&r);
                    }
                    i += len;
                }
                Classified::Partial => break, // wait for more bytes
                Classified::No => i += 1,
            }
        }

        // Keep only the unprocessed tail, bounded. (A false Partial — e.g.
        // content genuinely ending in ESC — resolves as more bytes arrive.)
        self.tail.drain(..i);
        if self.tail.len() > MAX_TAIL_LEN {
            let excess = self.tail.len() - MAX_TAIL_LEN;
            self.tail.drain(..excess);
        }
        replies
    }

    /// The reply table. `None` means "recognized, deliberately unanswered"
    /// (declining a capability).
    fn reply_for(&self, query: &[u8]) -> Option<Vec<u8>> {
        if query == b"\x1b[c" || query == b"\x1b[0c" {
            // Primary DA: VT220 with ANSI color.
            return Some(b"\x1b[?62;22c".to_vec());
        }
        if query == b"\x1b[6n" {
            return Some(b"\x1b[1;1R".to_vec());
        }
        if query == b"\x1b[5n" {
            return Some(b"\x1b[0n".to_vec());
        }
        if query.starts_with(b"\x1b[?") && query.ends_with(b"$p") {
            // DECRQM: every mode reported "not recognized" (0). Notably
            // 2026 (sync output), 2027 (graphemes), 2031 (color scheme),
            // 2048 (in-band resize): declining keeps the oracle on legacy
            // input/width paths matching the Rust side's forced config.
            let mut reply = b"\x1b[?".to_vec();
            reply.extend_from_slice(&query[3..query.len() - 2]);
            reply.extend_from_slice(b";0$y");
            return Some(reply);
        }
        if query.starts_with(b"\x1b]11;?") {
            return Some(self.background.osc11_reply().to_vec());
        }
        if query.starts_with(b"\x1b]10;?") {
            return Some(self.background.osc10_reply().to_vec());
        }
        // XTVERSION, kitty keyboard, XTWINOPS, XTGETTCAP: decline by silence.
        None
    }
}

/// Recognize a query at the start of `buf` (which begins with ESC).
fn classify(buf: &[u8]) -> Classified {
    debug_assert_eq!(buf[0], 0x1b);
    if buf.len() < 2 {
        return Classified::Partial;
    }
    match buf[1] {
        b'[' => classify_csi(buf),
        b']' => classify_osc(buf),
        b'P' => classify_dcs(buf),
        _ => Classified::No,
    }
}

fn classify_csi(buf: &[u8]) -> Classified {
    // Fixed short queries first.
    for (pat, name) in [
        (b"\x1b[c" as &[u8], "DA1"),
        (b"\x1b[0c", "DA1"),
        (b"\x1b[>q", "XTVERSION"),
        (b"\x1b[>0q", "XTVERSION"),
        (b"\x1b[?u", "kitty-keyboard-query"),
        (b"\x1b[6n", "DSR-CPR"),
        (b"\x1b[5n", "DSR-status"),
        (b"\x1b[16t", "XTWINOPS-cell-size"),
        (b"\x1b[14t", "XTWINOPS-text-area-px"),
        (b"\x1b[18t", "XTWINOPS-text-area-cells"),
    ] {
        if buf.len() < pat.len() {
            if pat.starts_with(buf) {
                return Classified::Partial;
            }
            continue;
        }
        if buf.starts_with(pat) {
            return Classified::Query {
                len: pat.len(),
                name: name.to_string(),
            };
        }
    }

    // DECRQM: ESC [ ? <digits> $ p
    if buf.starts_with(b"\x1b[?") {
        let mut j = 3;
        while j < buf.len() && buf[j].is_ascii_digit() {
            j += 1;
        }
        if j > 3 {
            if j >= buf.len() {
                return Classified::Partial;
            }
            if buf[j] == b'$' {
                if j + 1 >= buf.len() {
                    return Classified::Partial;
                }
                if buf[j + 1] == b'p' {
                    let mode = String::from_utf8_lossy(&buf[3..j]);
                    return Classified::Query {
                        len: j + 2,
                        name: format!("DECRQM-{mode}"),
                    };
                }
            }
        }
    }
    Classified::No
}

fn classify_osc(buf: &[u8]) -> Classified {
    // OSC 10/11 color queries: ESC ] 1 0/1 ; ? (BEL | ESC \)
    for (prefix, name) in [(b"\x1b]10;?" as &[u8], "OSC10"), (b"\x1b]11;?", "OSC11")] {
        if buf.len() < prefix.len() {
            if prefix.starts_with(buf) {
                return Classified::Partial;
            }
            continue;
        }
        if buf.starts_with(prefix) {
            let rest = &buf[prefix.len()..];
            if rest.is_empty() {
                return Classified::Partial;
            }
            if rest[0] == 0x07 {
                return Classified::Query {
                    len: prefix.len() + 1,
                    name: name.to_string(),
                };
            }
            if rest[0] == 0x1b {
                if rest.len() < 2 {
                    return Classified::Partial;
                }
                if rest[1] == b'\\' {
                    return Classified::Query {
                        len: prefix.len() + 2,
                        name: name.to_string(),
                    };
                }
            }
        }
    }
    Classified::No
}

fn classify_dcs(buf: &[u8]) -> Classified {
    // XTGETTCAP: ESC P + q <hex...> ESC \ — recognized, never answered.
    if buf.len() < 4 {
        return if b"\x1bP+q".starts_with(buf) {
            Classified::Partial
        } else {
            Classified::No
        };
    }
    if !buf.starts_with(b"\x1bP+q") {
        return Classified::No;
    }
    for j in 4..buf.len().min(64) {
        if buf[j] == 0x1b {
            if j + 1 >= buf.len() {
                return Classified::Partial;
            }
            if buf[j + 1] == b'\\' {
                return Classified::Query {
                    len: j + 2,
                    name: "XTGETTCAP".to_string(),
                };
            }
        }
    }
    if buf.len() < 64 {
        Classified::Partial
    } else {
        Classified::No
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn da1_gets_reply_split_across_chunks() {
        let mut p = Persona::new(PersonaBackground::Dark);
        assert!(p.scan(b"hello\x1b").is_empty());
        let r = p.scan(b"[c world");
        assert_eq!(r, b"\x1b[?62;22c");
        assert_eq!(p.log.len(), 1);
        assert_eq!(p.log[0].query, "DA1");
        assert!(p.log[0].reply.is_some());
    }

    #[test]
    fn decrqm_declined_with_mode_zero() {
        let mut p = Persona::new(PersonaBackground::Dark);
        let r = p.scan(b"\x1b[?2027$p");
        assert_eq!(r, b"\x1b[?2027;0$y");
        assert_eq!(p.log[0].query, "DECRQM-2027");
    }

    #[test]
    fn osc11_reports_frozen_dark_background() {
        let mut p = Persona::new(PersonaBackground::Dark);
        let r = p.scan(b"\x1b]11;?\x07");
        assert_eq!(r, b"\x1b]11;rgb:1e1e/1e1e/1e1e\x1b\\");
    }

    #[test]
    fn kitty_keyboard_declined_by_silence_but_logged() {
        let mut p = Persona::new(PersonaBackground::Dark);
        let r = p.scan(b"\x1b[?u");
        assert!(r.is_empty());
        assert_eq!(p.log[0].query, "kitty-keyboard-query");
        assert!(p.log[0].reply.is_none());
    }

    #[test]
    fn sgr_content_is_not_matched() {
        let mut p = Persona::new(PersonaBackground::Dark);
        let r = p.scan(b"\x1b[38;2;255;0;0mred\x1b[0m \x1b[2J\x1b[H");
        assert!(r.is_empty());
        assert!(p.log.is_empty());
    }
}

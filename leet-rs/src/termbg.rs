//! Terminal background color detection via OSC 11.
//!
//! Mirrors the Go implementation's termenv query: ask the terminal for its
//! background color once at startup so adaptive colors and the run-list
//! zebra tint can match the real background. Must run while raw mode is
//! enabled and before the event loop starts consuming stdin.

/// Queries the terminal background color, waiting up to `timeout_ms`.
///
/// Returns `None` when the terminal does not answer (the caller keeps the
/// dark-background default, as Go leet does).
#[cfg(unix)]
pub fn query_background(timeout_ms: i32) -> Option<(u8, u8, u8)> {
    use std::io::{Read, Write};
    use std::os::fd::AsRawFd;

    let mut stdout = std::io::stdout();
    // Query background color; ST-terminated per xterm ctlseqs.
    stdout.write_all(b"\x1b]11;?\x1b\\").ok()?;
    stdout.flush().ok()?;

    let stdin = std::io::stdin();
    let fd = stdin.as_raw_fd();
    let mut response = Vec::with_capacity(64);
    let deadline = std::time::Instant::now() + std::time::Duration::from_millis(timeout_ms as u64);

    loop {
        let remaining = deadline.saturating_duration_since(std::time::Instant::now());
        if remaining.is_zero() {
            return None;
        }
        let mut pfd = libc_pollfd(fd);
        let n = unsafe { libc::poll(&mut pfd, 1, remaining.as_millis() as i32) };
        if n <= 0 {
            return None;
        }

        let mut buf = [0u8; 64];
        let read = stdin.lock().read(&mut buf).ok()?;
        if read == 0 {
            return None;
        }
        response.extend_from_slice(&buf[..read]);

        // Terminators: BEL or ST (ESC \).
        if response.contains(&0x07) || response.windows(2).any(|w| w == b"\x1b\\") {
            return parse_osc11(&response);
        }
        if response.len() > 4096 {
            return None;
        }
    }
}

#[cfg(not(unix))]
pub fn query_background(_timeout_ms: i32) -> Option<(u8, u8, u8)> {
    None
}

#[cfg(unix)]
fn libc_pollfd(fd: i32) -> libc::pollfd {
    libc::pollfd {
        fd,
        events: libc::POLLIN,
        revents: 0,
    }
}

/// Parses an OSC 11 reply: `ESC ] 11 ; rgb:RRRR/GGGG/BBBB (BEL | ESC \)`.
///
/// Channel width varies by terminal (1-4 hex digits); the high-order byte is
/// used, matching X11 color-spec scaling.
fn parse_osc11(response: &[u8]) -> Option<(u8, u8, u8)> {
    let text = String::from_utf8_lossy(response);
    let spec = text.split("rgb:").nth(1)?;
    let spec = spec.trim_end_matches(['\x07', '\x1b', '\\']);
    let mut channels = spec.split('/');

    let parse = |s: &str| -> Option<u8> {
        let digits: String = s.chars().take_while(|c| c.is_ascii_hexdigit()).collect();
        if digits.is_empty() {
            return None;
        }
        let v = u32::from_str_radix(&digits, 16).ok()?;
        // Scale to 8 bits from however many digits were given.
        let max = (1u32 << (4 * digits.len() as u32)) - 1;
        Some(((v * 255 + max / 2) / max) as u8)
    };

    let r = parse(channels.next()?)?;
    let g = parse(channels.next()?)?;
    let b = parse(channels.next()?)?;
    Some((r, g, b))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_four_digit_reply() {
        let reply = b"\x1b]11;rgb:1e1e/2222/2828\x07";
        assert_eq!(parse_osc11(reply), Some((0x1e, 0x22, 0x28)));
    }

    #[test]
    fn parses_two_digit_reply_with_st() {
        let reply = b"\x1b]11;rgb:ff/ff/ff\x1b\\";
        assert_eq!(parse_osc11(reply), Some((0xff, 0xff, 0xff)));
    }

    #[test]
    fn rejects_garbage() {
        assert_eq!(parse_osc11(b"\x1b[0n"), None);
    }
}

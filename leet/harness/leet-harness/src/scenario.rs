//! Scenario DSL: a JSON script of events + assertions shared by the oracle
//! recorder and (later) the Rust-side parity tests. Scenario IDs are
//! referenced from `docs/PARITY.md`.
//!
//! ```json
//! {
//!   "name": "workspace-boot-01",
//!   "fixture": "workspace-multi",
//!   "size": { "cols": 120, "rows": 40 },
//!   "steps": [
//!     { "await_update": { "type": "FileCompleteMsg", "count": 1, "timeout_ms": 15000 } },
//!     { "quiesce": {} },
//!     { "snap": "boot" },
//!     { "key": "j" },
//!     { "snap": "after-j" }
//!   ]
//! }
//! ```

use std::path::Path;

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Scenario {
    pub name: String,
    /// Fixture directory name under `fixtures/wandb/` (the oracle is pointed
    /// at `<fixture>/wandb`). Symon/config scenarios may omit it.
    #[serde(default)]
    pub fixture: Option<String>,
    #[serde(default = "default_size")]
    pub size: Size,
    /// Extra oracle CLI flags (e.g. ["--symon"]).
    #[serde(default)]
    pub args: Vec<String>,
    /// Forced background: "dark" (default) or "light".
    #[serde(default)]
    pub background: Background,
    /// Regions blanked on both sides before diffing (for cells that are
    /// legitimately non-deterministic; use sparingly, each needs a comment).
    #[serde(default)]
    pub masks: Vec<Mask>,
    /// Diff tier this scenario is gated at (see docs: 0=structural 1=chars
    /// 2=color). Unicode-hostile scenarios set 0.
    #[serde(default = "default_tier")]
    pub tier: u8,
    pub steps: Vec<Step>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct Size {
    pub cols: u16,
    pub rows: u16,
}

fn default_size() -> Size {
    Size {
        cols: 120,
        rows: 40,
    }
}

fn default_tier() -> u8 {
    1
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Background {
    #[default]
    Dark,
    Light,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mask {
    pub x: usize,
    pub y: usize,
    pub w: usize,
    pub h: usize,
    /// Why this region is masked — required, shows up in reports.
    #[serde(default)]
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Step {
    /// Send a key (name or literal char) and await its Update+View acks,
    /// then ack-quiet.
    Key(String),
    /// Send a key without awaiting anything (for keys that quit/restart).
    KeyNoAwait(String),
    /// Mouse event at 0-based cell coordinates.
    Mouse(MouseStep),
    /// Resize the PTY and await the WindowSizeMsg ack.
    Resize { cols: u16, rows: u16 },
    /// Await `count` Update acks whose Go/Rust type name contains `type`.
    AwaitUpdate {
        #[serde(rename = "type")]
        type_fragment: String,
        #[serde(default = "default_count")]
        count: usize,
        #[serde(default = "default_await_timeout_ms")]
        timeout_ms: u64,
    },
    /// Ack-quiet: no Update/View acks for `quiet_ms` (default 150).
    Quiesce {
        #[serde(default = "default_quiet_ms")]
        quiet_ms: u64,
        #[serde(default = "default_await_timeout_ms")]
        timeout_ms: u64,
    },
    /// Capture a named frame.
    Snap(String),
    /// Wall-clock sleep — escape hatch, avoid.
    WaitMs(u64),
}

fn default_count() -> usize {
    1
}
fn default_await_timeout_ms() -> u64 {
    15_000
}
fn default_quiet_ms() -> u64 {
    150
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct MouseStep {
    /// 0-based cell column/row (the SGR encoder converts to 1-based).
    pub col: u16,
    pub row: u16,
    pub kind: MouseKind,
    #[serde(default)]
    pub alt: bool,
    #[serde(default)]
    pub shift: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MouseKind {
    LeftPress,
    LeftRelease,
    RightPress,
    RightRelease,
    RightDrag,
    WheelUp,
    WheelDown,
}

impl Scenario {
    pub fn load(path: &Path) -> Result<Self> {
        let data = std::fs::read_to_string(path)
            .with_context(|| format!("read scenario {}", path.display()))?;
        let sc: Scenario = serde_json::from_str(&data)
            .with_context(|| format!("parse scenario {}", path.display()))?;
        if sc.steps.is_empty() {
            bail!("scenario {} has no steps", sc.name);
        }
        Ok(sc)
    }
}

/// Encode a key name to the byte sequence a terminal would send. Names mirror
/// leet's keybindings.go vocabulary. Most keys use the legacy encoding;
/// `ctrl+/` is the one binding that has no legacy representation (see below)
/// and uses the kitty CSI-u encoding both decoders accept unconditionally.
pub fn encode_key(name: &str) -> Result<Vec<u8>> {
    let bytes: Vec<u8> = match name {
        "enter" => b"\r".to_vec(),
        "esc" => b"\x1b".to_vec(),
        "tab" => b"\t".to_vec(),
        "shift+tab" => b"\x1b[Z".to_vec(),
        "space" => b" ".to_vec(),
        "backspace" => b"\x7f".to_vec(),
        "up" => b"\x1b[A".to_vec(),
        "down" => b"\x1b[B".to_vec(),
        "right" => b"\x1b[C".to_vec(),
        "left" => b"\x1b[D".to_vec(),
        "home" => b"\x1b[H".to_vec(),
        "end" => b"\x1b[F".to_vec(),
        "pgup" => b"\x1b[5~".to_vec(),
        "pgdown" => b"\x1b[6~".to_vec(),
        "ctrl+c" => b"\x03".to_vec(),
        "ctrl+f" => b"\x06".to_vec(),
        "ctrl+l" => b"\x0c".to_vec(),
        "ctrl+o" => b"\x0f".to_vec(),
        // PARITY: there is no legacy byte for ctrl+/ — terminals send US
        // (0x1f), which BOTH ultraviolet (key_table.go / decoder.go
        // parseControl) and the Rust port decode as "ctrl+_", so the
        // "ctrl+/" binding can never fire from legacy bytes (that's why
        // keybindings keep the ctrl+l fallback). Go leet works in real
        // terminals because Bubble Tea v2 always negotiates kitty key
        // disambiguation (cursed_renderer.go keyboardEnhancementsFlags:
        // "always enable basic key disambiguation"), making the terminal
        // send CSI 47;5u instead. Emulate that terminal class here; both
        // ultraviolet and crossterm parse CSI-u without negotiation.
        "ctrl+/" => b"\x1b[47;5u".to_vec(),
        // The legacy byte a NON-negotiating (dumb) terminal sends for
        // ctrl+/ (and for ctrl+_ and ctrl+shift+-): US, 0x1f. Decodes as
        // "ctrl+_" in both implementations and must NOT clear the filter
        // in either (verified against the Go oracle in a scripted PTY that
        // answers no negotiation).
        "ctrl+_" => b"\x1f".to_vec(),
        // ctrl+\ has a faithful legacy byte: FS (0x1c) decodes as "ctrl+\\"
        // in both implementations (this also exercises the Rust C0 remap).
        "ctrl+\\" => b"\x1c".to_vec(),
        _ => {
            if let Some(rest) = name.strip_prefix("alt+") {
                // ESC-prefixed
                let mut inner = encode_key(rest)?;
                let mut v = vec![0x1b];
                v.append(&mut inner);
                v
            } else if name.chars().count() == 1 {
                name.as_bytes().to_vec()
            } else {
                bail!("unknown key name: {name:?}");
            }
        }
    };
    Ok(bytes)
}

/// SGR mouse encoding (mode 1006): `CSI < b ; x ; y M/m`, 1-based coords.
pub fn encode_mouse(m: &MouseStep) -> Vec<u8> {
    let (mut b, press) = match m.kind {
        MouseKind::LeftPress => (0, true),
        MouseKind::LeftRelease => (0, false),
        MouseKind::RightPress => (2, true),
        MouseKind::RightRelease => (2, false),
        // Motion with right button held: button + 32.
        MouseKind::RightDrag => (2 + 32, true),
        MouseKind::WheelUp => (64, true),
        MouseKind::WheelDown => (65, true),
    };
    if m.shift {
        b += 4;
    }
    if m.alt {
        b += 8;
    }
    let suffix = if press { 'M' } else { 'm' };
    format!("\x1b[<{};{};{}{}", b, m.col + 1, m.row + 1, suffix).into_bytes()
}

/// The Update-ack type fragment expected after a key press.
pub const KEY_ACK_TYPE: &str = "KeyPressMsg";
/// … after a mouse event (bubbletea delivers concrete types like
/// tea.MouseClickMsg/MouseWheelMsg/MouseMotionMsg — "Mouse" matches all).
pub const MOUSE_ACK_TYPE: &str = "Mouse";
/// … after a resize.
pub const RESIZE_ACK_TYPE: &str = "WindowSizeMsg";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn key_encoding_covers_leet_bindings() {
        assert_eq!(encode_key("j").unwrap(), b"j");
        assert_eq!(encode_key("enter").unwrap(), b"\r");
        assert_eq!(encode_key("shift+tab").unwrap(), b"\x1b[Z");
        assert_eq!(encode_key("alt+r").unwrap(), b"\x1br");
        // ctrl+/ is the negotiated (kitty CSI-u) encoding; ctrl+_ is the
        // legacy 0x1f byte a dumb terminal sends for the same chord.
        assert_eq!(encode_key("ctrl+/").unwrap(), b"\x1b[47;5u");
        assert_eq!(encode_key("ctrl+_").unwrap(), b"\x1f");
        assert!(encode_key("hyper+x").is_err());
    }

    #[test]
    fn sgr_mouse_is_one_based() {
        let e = encode_mouse(&MouseStep {
            col: 0,
            row: 0,
            kind: MouseKind::LeftPress,
            alt: false,
            shift: false,
        });
        assert_eq!(e, b"\x1b[<0;1;1M");
        let e = encode_mouse(&MouseStep {
            col: 10,
            row: 5,
            kind: MouseKind::WheelDown,
            alt: false,
            shift: false,
        });
        assert_eq!(e, b"\x1b[<65;11;6M");
    }
}

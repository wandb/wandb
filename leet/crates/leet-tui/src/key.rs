//! Input events: the `tea.KeyPressMsg` / `tea.Mouse*Msg` surface that leet's
//! call sites consume (keybindings.go, nav.go, filter.go, runhandlers.go,
//! workspacehandlers.go, mediapane.go), normalized from crossterm events.
//!
//! Only the subset leet reads is modeled — `Key.Code`, `Key.Text`, `Key.Mod`
//! and `Key.String()` for the binding tables (keybindings.go `buildKeyMap`
//! keys handlers by `normalizeKey(msg.String())`), plus `tea.Mouse{X, Y,
//! Button, Mod}` and the click/release/motion/wheel message kinds.
//!
//! The crossterm mappings reproduce what Bubble Tea v2's legacy decoder
//! (ultraviolet `key_table.go` / `decoder.go`) reports for the same input
//! bytes, so binding strings match the Go oracle byte-for-byte.

use crossterm::event::{
    KeyCode as CtKeyCode, KeyEvent as CtKeyEvent, KeyEventKind, KeyModifiers,
    MouseButton as CtMouseButton, MouseEvent as CtMouseEvent, MouseEventKind,
};

/// Modifier flags carried by key and mouse events (Go `tea.KeyMod`).
///
/// Only the modifiers leet reads are modeled: ctrl/alt in key bindings
/// ("ctrl+c", "alt+r", …) and alt/shift on mouse events (runhandlers.go
/// `mouse.Mod == tea.ModAlt`; help's "shift+drag" is terminal-side).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct KeyMods {
    pub ctrl: bool,
    pub alt: bool,
    pub shift: bool,
}

impl KeyMods {
    pub const NONE: KeyMods = KeyMods {
        ctrl: false,
        alt: false,
        shift: false,
    };
    pub const CTRL: KeyMods = KeyMods {
        ctrl: true,
        alt: false,
        shift: false,
    };
    /// Go `tea.ModAlt`; compared with `==` at mouse call sites
    /// (runhandlers.go:175, :228), which this type's `PartialEq` mirrors.
    pub const ALT: KeyMods = KeyMods {
        ctrl: false,
        alt: true,
        shift: false,
    };
    pub const SHIFT: KeyMods = KeyMods {
        ctrl: false,
        alt: false,
        shift: true,
    };
}

/// The key that was pressed (Go `tea.Key.Code`), restricted to the codes
/// leet's call sites match on (filter.go, model.go, runoverviewsidebar.go,
/// mediapane.go) plus everything reachable from the binding tables.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeyCode {
    /// A printable character. ASCII uppercase is folded to lowercase with the
    /// shift modifier set, mirroring ultraviolet's decoder (`parseUtf8`); the
    /// shifted text is preserved in [`KeyEvent::text`].
    Char(char),
    /// Go `tea.KeySpace` — space decodes as a named key with text `" "`.
    Space,
    /// Go `tea.KeyEnter`.
    Enter,
    /// Go `tea.KeyEsc`.
    Esc,
    /// Go `tea.KeyTab`; shift+tab is `Tab` with [`KeyMods::shift`] set,
    /// as in Bubble Tea (`\x1b[Z` → `{Code: KeyTab, Mod: ModShift}`).
    Tab,
    /// Go `tea.KeyBackspace` (the DEL 0x7f byte).
    Backspace,
    /// Go `tea.KeyUp`.
    Up,
    /// Go `tea.KeyDown`.
    Down,
    /// Go `tea.KeyLeft`.
    Left,
    /// Go `tea.KeyRight`.
    Right,
    /// Go `tea.KeyHome`.
    Home,
    /// Go `tea.KeyEnd`.
    End,
    /// Go `tea.KeyPgUp`.
    PgUp,
    /// Go `tea.KeyPgDown`.
    PgDown,
}

/// A key press (Go `tea.KeyPressMsg`, i.e. `tea.Key`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KeyEvent {
    pub code: KeyCode,
    /// The text the key produces (Go `tea.Key.Text`; `None` ⇔ Go `""`).
    /// Filter input appends this verbatim (filter.go `UpdateDraft`); the
    /// config editor iterates its chars (configeditor.go:570-571).
    pub text: Option<String>,
    pub mods: KeyMods,
}

impl KeyEvent {
    /// Port of `tea.Key.String()`: the textual representation of the key if
    /// there is one, otherwise the keystroke — you always get "?" and never
    /// "shift+/". Binding lookups pass this through [`normalize_key`]
    /// (keybindings.go `buildKeyMap` / runhandlers.go:322).
    pub fn key_string(&self) -> String {
        if let Some(text) = &self.text
            && !text.is_empty()
            && text != " "
        {
            return text.clone();
        }
        self.keystroke()
    }

    /// Port of `tea.Key.Keystroke()`: "ctrl+" / "alt+" / "shift+" prefixes
    /// (in that order) followed by the key name from ultraviolet's
    /// `keyTypeString` table ("esc", "pgup", …) or the character itself.
    pub fn keystroke(&self) -> String {
        let mut s = String::new();
        if self.mods.ctrl {
            s.push_str("ctrl+");
        }
        if self.mods.alt {
            s.push_str("alt+");
        }
        if self.mods.shift {
            s.push_str("shift+");
        }
        match self.code {
            KeyCode::Char(c) => s.push(c),
            KeyCode::Space => s.push_str("space"),
            KeyCode::Enter => s.push_str("enter"),
            KeyCode::Esc => s.push_str("esc"),
            KeyCode::Tab => s.push_str("tab"),
            KeyCode::Backspace => s.push_str("backspace"),
            KeyCode::Up => s.push_str("up"),
            KeyCode::Down => s.push_str("down"),
            KeyCode::Left => s.push_str("left"),
            KeyCode::Right => s.push_str("right"),
            KeyCode::Home => s.push_str("home"),
            KeyCode::End => s.push_str("end"),
            KeyCode::PgUp => s.push_str("pgup"),
            KeyCode::PgDown => s.push_str("pgdown"),
        }
        s
    }

    /// Maps a crossterm key event to leet's key event. Returns `None` for
    /// events leet never consumes: key releases, and keys outside the modeled
    /// set (F-keys, insert/delete, media keys, …) which in Go would reach the
    /// binding map and match nothing.
    ///
    /// Divergences between crossterm's parser and ultraviolet's are
    /// normalized here so both implementations report identical keys for
    /// identical input bytes:
    ///
    ///   - ASCII uppercase → lowercase `Code` + shift + `Text` (ultraviolet
    ///     decoder.go `parseUtf8`); text is cleared under ctrl/alt, mirroring
    ///     the ESC-prefix alt path (decoder.go:263-266) and the C0 table.
    ///   - The C0 bytes 0x1C..0x1F arrive from crossterm as ctrl+'4'..'7' but
    ///     ultraviolet reports ctrl+'\\', ']', '^', '_' (key_table.go FS/GS/
    ///     RS/US rows; decoder.go `parseControl` agrees) — the "ctrl+\\"
    ///     binding depends on this remap on legacy terminals.
    ///     PARITY: note 0x1F is ctrl+'_', NOT ctrl+'/'. No legacy byte maps
    ///     to "ctrl+/" in either implementation, so that binding can only
    ///     fire via an enhanced encoding. Go gets one automatically: Bubble
    ///     Tea v2 always negotiates kitty key disambiguation (bubbletea
    ///     cursed_renderer.go `keyboardEnhancementsFlags` starts at flags=1,
    ///     plus xterm modifyOtherKeys mode 2), so kitty-capable terminals
    ///     send ctrl+/ as CSI 47;5u, which crossterm also parses without
    ///     negotiation into Char('/')+CONTROL and stringifies as "ctrl+/"
    ///     here. The runtime mirrors Go's negotiation with
    ///     `PushKeyboardEnhancementFlags` (runtime.rs `setup_terminal`,
    ///     `KEYBOARD_ENHANCEMENTS`) so kitty-capable terminals actually
    ///     send that encoding; this module is byte-for-byte faithful on
    ///     both encodings. Go's additional modifyOtherKeys mode 2 is NOT
    ///     mirrored — crossterm cannot parse `CSI 27;<mod>;<code>~` (its
    ///     reader drops, and worse, wedges on the sequence), so on
    ///     mok-only terminals (bare xterm) "ctrl+/" stays inert in Rust
    ///     where Go clears; ctrl+l covers those terminals.
    ///     PARITY: under the kitty protocol a genuine ctrl+4 (CSI 52;5u) is
    ///     indistinguishable from legacy 0x1C at this layer and gets
    ///     remapped to ctrl+'\\' where Go reports "ctrl+4"; accepted — kitty
    ///     terminals never send the raw C0 bytes for these combos, and
    ///     ctrl+4..7 are unbound.
    pub fn from_crossterm(ev: CtKeyEvent) -> Option<KeyEvent> {
        if ev.kind == KeyEventKind::Release {
            return None;
        }

        let mut mods = KeyMods {
            ctrl: ev.modifiers.contains(KeyModifiers::CONTROL),
            alt: ev.modifiers.contains(KeyModifiers::ALT),
            shift: ev.modifiers.contains(KeyModifiers::SHIFT),
        };

        let mut text = None;
        let code = match ev.code {
            CtKeyCode::Char(mut c) => {
                if mods.ctrl {
                    // C0 0x1C..0x1F: crossterm's ctrl+'4'..'7' → ultraviolet's
                    // ctrl+'\', ']', '^', '_' (key_table.go FS/GS/RS/US rows).
                    c = match c {
                        '4' => '\\',
                        '5' => ']',
                        '6' => '^',
                        '7' => '_',
                        other => other,
                    };
                }
                if !mods.ctrl && !mods.alt {
                    text = Some(c.to_string());
                }
                if c == ' ' {
                    KeyCode::Space
                } else if c.is_ascii_uppercase() {
                    // Convert upper case letters to lower case + shift
                    // modifier (ultraviolet decoder.go parseUtf8).
                    mods.shift = true;
                    KeyCode::Char(c.to_ascii_lowercase())
                } else {
                    KeyCode::Char(c)
                }
            }
            CtKeyCode::Enter => KeyCode::Enter,
            CtKeyCode::Esc => KeyCode::Esc,
            CtKeyCode::Tab => KeyCode::Tab,
            CtKeyCode::BackTab => {
                // `\x1b[Z` → {Code: KeyTab, Mod: ModShift} (key_table.go).
                mods.shift = true;
                KeyCode::Tab
            }
            CtKeyCode::Backspace => KeyCode::Backspace,
            CtKeyCode::Up => KeyCode::Up,
            CtKeyCode::Down => KeyCode::Down,
            CtKeyCode::Left => KeyCode::Left,
            CtKeyCode::Right => KeyCode::Right,
            CtKeyCode::Home => KeyCode::Home,
            CtKeyCode::End => KeyCode::End,
            CtKeyCode::PageUp => KeyCode::PgUp,
            CtKeyCode::PageDown => KeyCode::PgDown,
            _ => return None,
        };

        Some(KeyEvent { code, text, mods })
    }
}

/// Port of keybindings.go `normalizeKey`: normalizes a key string into the
/// stable form used by the binding maps.
///
/// Bubble Tea has historically reported space as " " in some situations; we
/// want a help-friendly, explicit key name.
pub fn normalize_key(key: &str) -> &str {
    if key == " " { "space" } else { key }
}

/// Mouse buttons (Go `tea.MouseButton`), restricted to what crossterm can
/// report. leet reads `Left`, `Right`, `WheelUp` and `WheelDown`
/// (runhandlers.go, workspacehandlers.go); the rest exist so every crossterm
/// event maps totally.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MouseButton {
    /// Go `tea.MouseNone` (motion without a held button).
    None,
    Left,
    Middle,
    Right,
    /// Wheel directions are buttons, as in Bubble Tea
    /// (`m.Button == tea.MouseWheelUp`).
    WheelUp,
    WheelDown,
    WheelLeft,
    WheelRight,
}

/// Which Go mouse message the event corresponds to: `tea.MouseClickMsg`,
/// `tea.MouseReleaseMsg`, `tea.MouseMotionMsg` or `tea.MouseWheelMsg`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MouseKind {
    Click,
    Release,
    Motion,
    Wheel,
}

/// A mouse event: Go `tea.Mouse{X, Y, Button, Mod}` plus the message kind.
///
/// `x`/`y` are zero-based cell coordinates (SGR-decoded); Go stores them as
/// `int` and layout math subtracts into negatives before bounds checks
/// (runhandlers.go:232-238), hence `isize`. `mods` carries the modifiers held
/// at event time — alt gates synchronized inspection
/// (`mouse.Mod == tea.ModAlt`, runhandlers.go:175, :228).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MouseEvent {
    pub kind: MouseKind,
    pub button: MouseButton,
    pub x: isize,
    pub y: isize,
    pub mods: KeyMods,
}

impl MouseEvent {
    /// Total mapping from crossterm's SGR-decoded mouse event: press/release,
    /// drag (motion with the held button — right-drag drives chart
    /// inspection), pure motion (button `None`), and wheel (direction encoded
    /// as a button, as in Bubble Tea).
    pub fn from_crossterm(ev: CtMouseEvent) -> MouseEvent {
        let (kind, button) = match ev.kind {
            MouseEventKind::Down(b) => (MouseKind::Click, MouseButton::from_crossterm(b)),
            MouseEventKind::Up(b) => (MouseKind::Release, MouseButton::from_crossterm(b)),
            MouseEventKind::Drag(b) => (MouseKind::Motion, MouseButton::from_crossterm(b)),
            MouseEventKind::Moved => (MouseKind::Motion, MouseButton::None),
            MouseEventKind::ScrollUp => (MouseKind::Wheel, MouseButton::WheelUp),
            MouseEventKind::ScrollDown => (MouseKind::Wheel, MouseButton::WheelDown),
            MouseEventKind::ScrollLeft => (MouseKind::Wheel, MouseButton::WheelLeft),
            MouseEventKind::ScrollRight => (MouseKind::Wheel, MouseButton::WheelRight),
        };
        MouseEvent {
            kind,
            button,
            x: ev.column as isize,
            y: ev.row as isize,
            mods: KeyMods {
                ctrl: ev.modifiers.contains(KeyModifiers::CONTROL),
                alt: ev.modifiers.contains(KeyModifiers::ALT),
                shift: ev.modifiers.contains(KeyModifiers::SHIFT),
            },
        }
    }
}

impl MouseButton {
    fn from_crossterm(b: CtMouseButton) -> MouseButton {
        match b {
            CtMouseButton::Left => MouseButton::Left,
            CtMouseButton::Right => MouseButton::Right,
            CtMouseButton::Middle => MouseButton::Middle,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(code: CtKeyCode, mods: KeyModifiers) -> KeyEvent {
        KeyEvent::from_crossterm(CtKeyEvent::new(code, mods))
            .unwrap_or_else(|| panic!("expected {code:?} + {mods:?} to map"))
    }

    /// Every key leet binds (keybindings.go, nav.go, mediapane.go HandleKey,
    /// metricsgrid.go digit capture) must map to the exact string Bubble Tea
    /// v2 reports for the same input, since buildKeyMap keys handlers by
    /// `normalizeKey(msg.String())`.
    #[test]
    fn binding_key_strings_match_bubbletea() {
        use CtKeyCode::*;
        use KeyModifiers as M;
        let cases: &[(&str, CtKeyCode, KeyModifiers, &str)] = &[
            // nav.go navKeys
            ("w", Char('w'), M::NONE, "w"),
            ("s", Char('s'), M::NONE, "s"),
            ("a", Char('a'), M::NONE, "a"),
            ("d", Char('d'), M::NONE, "d"),
            ("up", Up, M::NONE, "up"),
            ("down", Down, M::NONE, "down"),
            ("left", Left, M::NONE, "left"),
            ("right", Right, M::NONE, "right"),
            ("N (shifted)", Char('N'), M::SHIFT, "N"),
            ("N (bare uppercase)", Char('N'), M::NONE, "N"),
            ("n", Char('n'), M::NONE, "n"),
            ("pgup", PageUp, M::NONE, "pgup"),
            ("pgdown", PageDown, M::NONE, "pgdown"),
            ("home", Home, M::NONE, "home"),
            ("end", End, M::NONE, "end"),
            // General
            ("h", Char('h'), M::NONE, "h"),
            ("?", Char('?'), M::NONE, "?"),
            ("q", Char('q'), M::NONE, "q"),
            ("ctrl+c", Char('c'), M::CONTROL, "ctrl+c"),
            ("alt+r", Char('r'), M::ALT, "alt+r"),
            ("esc", Esc, M::NONE, "esc"),
            ("enter", Enter, M::NONE, "enter"),
            // Panels + grid config digits (metricsgrid.go strconv.Atoi)
            ("0", Char('0'), M::NONE, "0"),
            ("1", Char('1'), M::NONE, "1"),
            ("2", Char('2'), M::NONE, "2"),
            ("3", Char('3'), M::NONE, "3"),
            ("4", Char('4'), M::NONE, "4"),
            ("5", Char('5'), M::NONE, "5"),
            ("6", Char('6'), M::NONE, "6"),
            ("7", Char('7'), M::NONE, "7"),
            ("8", Char('8'), M::NONE, "8"),
            ("9", Char('9'), M::NONE, "9"),
            ("[", Char('['), M::NONE, "["),
            ("]", Char(']'), M::NONE, "]"),
            // Charts
            ("y", Char('y'), M::NONE, "y"),
            ("/", Char('/'), M::NONE, "/"),
            ("\\", Char('\\'), M::NONE, "\\"),
            // The "ctrl+/" binding only ever fires via an enhanced encoding
            // (kitty CSI 47;5u / modifyOtherKeys), which Go always
            // negotiates; crossterm parses CSI-u into Char('/')+CONTROL.
            ("ctrl+/ (kitty CSI-u)", Char('/'), M::CONTROL, "ctrl+/"),
            ("ctrl+\\ (kitty CSI-u)", Char('\\'), M::CONTROL, "ctrl+\\"),
            // Legacy C0 bytes: what crossterm reports for 0x1C..0x1F must
            // stringify like ultraviolet's key_table.go FS/GS/RS/US entries.
            // In particular legacy 0x1F is "ctrl+_", NOT "ctrl+/", matching
            // Go (verified against the oracle: 0x1F does not clear the
            // metrics filter there either — single-tiny-filter-clear-01).
            ("ctrl+\\ (legacy 0x1C)", Char('4'), M::CONTROL, "ctrl+\\"),
            ("ctrl+] (legacy 0x1D)", Char('5'), M::CONTROL, "ctrl+]"),
            ("ctrl+^ (legacy 0x1E)", Char('6'), M::CONTROL, "ctrl+^"),
            ("ctrl+_ (legacy 0x1F)", Char('7'), M::CONTROL, "ctrl+_"),
            ("ctrl+l", Char('l'), M::CONTROL, "ctrl+l"),
            // Run overview / runs filter
            ("o", Char('o'), M::NONE, "o"),
            ("ctrl+o", Char('o'), M::CONTROL, "ctrl+o"),
            ("f", Char('f'), M::NONE, "f"),
            ("ctrl+f", Char('f'), M::CONTROL, "ctrl+f"),
            // Configuration (symon also binds the shifted forms)
            ("c", Char('c'), M::NONE, "c"),
            ("r", Char('r'), M::NONE, "r"),
            ("C", Char('C'), M::SHIFT, "C"),
            ("R", Char('R'), M::SHIFT, "R"),
            // Focusable panes
            ("tab", Tab, M::NONE, "tab"),
            ("shift+tab", BackTab, M::SHIFT, "shift+tab"),
            ("shift+tab (bare BackTab)", BackTab, M::NONE, "shift+tab"),
            ("space", Char(' '), M::NONE, "space"),
            ("p", Char('p'), M::NONE, "p"),
            ("l", Char('l'), M::NONE, "l"),
            ("k", Char('k'), M::NONE, "k"),
            // Filter input
            ("backspace", Backspace, M::NONE, "backspace"),
            // Modifier stringification sanity
            ("ctrl+space (NUL)", Char(' '), M::CONTROL, "ctrl+space"),
            ("alt+N", Char('N'), M::ALT.union(M::SHIFT), "alt+shift+n"),
            ("shift+up", Up, M::SHIFT, "shift+up"),
        ];
        for (name, code, mods, want) in cases {
            let got = key(*code, *mods).key_string();
            assert_eq!(&got, want, "case {name:?}");
        }
    }

    #[test]
    fn key_releases_are_dropped() {
        let ev = CtKeyEvent::new_with_kind(
            CtKeyCode::Char('q'),
            KeyModifiers::NONE,
            KeyEventKind::Release,
        );
        assert_eq!(KeyEvent::from_crossterm(ev), None);
    }

    #[test]
    fn unmodeled_keys_are_dropped() {
        for code in [
            CtKeyCode::F(1),
            CtKeyCode::Insert,
            CtKeyCode::Delete,
            CtKeyCode::CapsLock,
        ] {
            assert_eq!(
                KeyEvent::from_crossterm(CtKeyEvent::new(code, KeyModifiers::NONE)),
                None,
                "expected {code:?} to be dropped"
            );
        }
    }

    /// filter.go UpdateDraft/HandleKey read `msg.Code` (Backspace/Space/
    /// Esc/Enter/Tab) and append `msg.Text`; configeditor.go:570 iterates
    /// `msg.Text` chars. These are the tea.Key field semantics.
    #[test]
    fn code_and_text_semantics_match_tea() {
        // Plain printable chars carry their text.
        let x = key(CtKeyCode::Char('x'), KeyModifiers::NONE);
        assert_eq!(x.code, KeyCode::Char('x'));
        assert_eq!(x.text.as_deref(), Some("x"));
        assert_eq!(x.mods, KeyMods::NONE);

        // Digits carry text too (config editor int entry).
        let seven = key(CtKeyCode::Char('7'), KeyModifiers::NONE);
        assert_eq!(seven.text.as_deref(), Some("7"));

        // Uppercase folds to lowercase code + shift, keeping the shifted
        // text (ultraviolet parseUtf8).
        let upper = key(CtKeyCode::Char('N'), KeyModifiers::SHIFT);
        assert_eq!(upper.code, KeyCode::Char('n'));
        assert_eq!(upper.text.as_deref(), Some("N"));
        assert_eq!(upper.mods, KeyMods::SHIFT);

        // Ctrl and alt clear text (C0 table entries have none; the ESC
        // prefix path clears it: ultraviolet decoder.go:263-266).
        assert_eq!(key(CtKeyCode::Char('c'), KeyModifiers::CONTROL).text, None);
        assert_eq!(key(CtKeyCode::Char('r'), KeyModifiers::ALT).text, None);

        // Space is a named key with text " " (tea.KeySpace).
        let space = key(CtKeyCode::Char(' '), KeyModifiers::NONE);
        assert_eq!(space.code, KeyCode::Space);
        assert_eq!(space.text.as_deref(), Some(" "));

        // Named keys carry no text.
        let bs = key(CtKeyCode::Backspace, KeyModifiers::NONE);
        assert_eq!(bs.code, KeyCode::Backspace);
        assert_eq!(bs.text, None);
        assert_eq!(
            key(CtKeyCode::Enter, KeyModifiers::NONE).code,
            KeyCode::Enter
        );
        assert_eq!(key(CtKeyCode::Esc, KeyModifiers::NONE).code, KeyCode::Esc);
        assert_eq!(key(CtKeyCode::Tab, KeyModifiers::NONE).code, KeyCode::Tab);
    }

    #[test]
    fn keystroke_mod_order_is_ctrl_alt_shift() {
        let ev = KeyEvent {
            code: KeyCode::Char('a'),
            text: None,
            mods: KeyMods {
                ctrl: true,
                alt: true,
                shift: true,
            },
        };
        assert_eq!(ev.keystroke(), "ctrl+alt+shift+a");
    }

    #[test]
    fn normalize_key_maps_bare_space() {
        assert_eq!(normalize_key(" "), "space");
        assert_eq!(normalize_key("space"), "space");
        assert_eq!(normalize_key("ctrl+c"), "ctrl+c");
    }

    fn mouse(kind: MouseEventKind, x: u16, y: u16, mods: KeyModifiers) -> MouseEvent {
        MouseEvent::from_crossterm(CtMouseEvent {
            kind,
            column: x,
            row: y,
            modifiers: mods,
        })
    }

    /// The mouse fields leet reads: kind (msg type), button, X/Y cell
    /// coordinates, and `Mod == tea.ModAlt` for synced inspection.
    #[test]
    fn mouse_events_map_like_tea() {
        use KeyModifiers as M;
        let cases: &[(&str, MouseEventKind, KeyModifiers, MouseKind, MouseButton)] = &[
            (
                "left click",
                MouseEventKind::Down(CtMouseButton::Left),
                M::NONE,
                MouseKind::Click,
                MouseButton::Left,
            ),
            (
                "right click",
                MouseEventKind::Down(CtMouseButton::Right),
                M::NONE,
                MouseKind::Click,
                MouseButton::Right,
            ),
            (
                "middle click",
                MouseEventKind::Down(CtMouseButton::Middle),
                M::NONE,
                MouseKind::Click,
                MouseButton::Middle,
            ),
            (
                "right drag (inspection)",
                MouseEventKind::Drag(CtMouseButton::Right),
                M::NONE,
                MouseKind::Motion,
                MouseButton::Right,
            ),
            (
                "right release (end inspection)",
                MouseEventKind::Up(CtMouseButton::Right),
                M::NONE,
                MouseKind::Release,
                MouseButton::Right,
            ),
            (
                "pure motion",
                MouseEventKind::Moved,
                M::NONE,
                MouseKind::Motion,
                MouseButton::None,
            ),
            (
                "wheel up (zoom in)",
                MouseEventKind::ScrollUp,
                M::NONE,
                MouseKind::Wheel,
                MouseButton::WheelUp,
            ),
            (
                "wheel down (zoom out)",
                MouseEventKind::ScrollDown,
                M::NONE,
                MouseKind::Wheel,
                MouseButton::WheelDown,
            ),
            (
                "wheel left",
                MouseEventKind::ScrollLeft,
                M::NONE,
                MouseKind::Wheel,
                MouseButton::WheelLeft,
            ),
            (
                "wheel right",
                MouseEventKind::ScrollRight,
                M::NONE,
                MouseKind::Wheel,
                MouseButton::WheelRight,
            ),
            (
                "alt+right click (synced inspection)",
                MouseEventKind::Down(CtMouseButton::Right),
                M::ALT,
                MouseKind::Click,
                MouseButton::Right,
            ),
        ];
        for (name, kind, mods, want_kind, want_button) in cases {
            let got = mouse(*kind, 12, 5, *mods);
            assert_eq!(got.kind, *want_kind, "case {name:?}");
            assert_eq!(got.button, *want_button, "case {name:?}");
            assert_eq!((got.x, got.y), (12, 5), "case {name:?}");
        }
    }

    #[test]
    fn mouse_alt_mod_equality_matches_go_call_sites() {
        // Go: alt := mouse.Mod == tea.ModAlt (runhandlers.go:175, :228).
        let alt = mouse(
            MouseEventKind::Down(CtMouseButton::Right),
            0,
            0,
            KeyModifiers::ALT,
        );
        assert_eq!(alt.mods, KeyMods::ALT);

        let alt_shift = mouse(
            MouseEventKind::Down(CtMouseButton::Right),
            0,
            0,
            KeyModifiers::ALT.union(KeyModifiers::SHIFT),
        );
        assert_ne!(alt_shift.mods, KeyMods::ALT);

        let shift_drag = mouse(
            MouseEventKind::Drag(CtMouseButton::Left),
            3,
            4,
            KeyModifiers::SHIFT,
        );
        assert_eq!(shift_drag.mods, KeyMods::SHIFT);
    }
}

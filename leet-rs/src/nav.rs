//! Pane-navigation intents shared by key bindings and per-pane decoders.

use crossterm::event::{KeyCode, KeyEvent};

/// A pane-navigation action (up/down, page, boundary).
///
/// Intents are the shared vocabulary between the help/key-binding table and
/// the per-pane key decoders in the grids and paged lists.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum NavIntent {
    #[default]
    None,
    Up,
    Down,
    Left,
    Right,
    PageUp,
    PageDown,
    Home,
    End,
}

/// The single source of truth mapping intents to the key labels that trigger
/// them (order matches the help screen).
pub const NAV_KEYS: &[(NavIntent, &[&str])] = &[
    (NavIntent::Up, &["w", "up"]),
    (NavIntent::Down, &["s", "down"]),
    (NavIntent::Left, &["a", "left"]),
    (NavIntent::Right, &["d", "right"]),
    (NavIntent::PageUp, &["N", "pgup"]),
    (NavIntent::PageDown, &["n", "pgdown"]),
    (NavIntent::Home, &["home"]),
    (NavIntent::End, &["end"]),
];

/// The `NavIntent` a key press represents, or `None` when the key is not a
/// navigation key.
pub fn decode_nav(key: &KeyEvent) -> NavIntent {
    match key.code {
        KeyCode::Char('w') => NavIntent::Up,
        KeyCode::Up => NavIntent::Up,
        KeyCode::Char('s') => NavIntent::Down,
        KeyCode::Down => NavIntent::Down,
        KeyCode::Char('a') => NavIntent::Left,
        KeyCode::Left => NavIntent::Left,
        KeyCode::Char('d') => NavIntent::Right,
        KeyCode::Right => NavIntent::Right,
        KeyCode::Char('N') => NavIntent::PageUp,
        KeyCode::PageUp => NavIntent::PageUp,
        KeyCode::Char('n') => NavIntent::PageDown,
        KeyCode::PageDown => NavIntent::PageDown,
        KeyCode::Home => NavIntent::Home,
        KeyCode::End => NavIntent::End,
        _ => NavIntent::None,
    }
}

/// The canonical key labels bound to an intent (for help text).
pub fn nav_keys_for(intent: NavIntent) -> &'static [&'static str] {
    NAV_KEYS
        .iter()
        .find(|(i, _)| *i == intent)
        .map(|(_, keys)| *keys)
        .unwrap_or(&[])
}

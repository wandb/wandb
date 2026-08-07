//! Port of `core/internal/leet/nav.go` — the canonical nav-intent ↔ key
//! table shared by the binding tables in [`crate::keybindings`] and the
//! per-pane key decoders (panelgrid.go, pagedlist.go).
//!
//! The test-helper constructors from `navhelpers_test.go` live in
//! [`test_helpers`] (shared by the key-handling test transliterations);
//! `navtesthelpers_test.go` is an empty package stub — nothing to port.

use std::collections::HashMap;
use std::sync::LazyLock;

use crate::key::{KeyEvent, normalize_key};

/// NavIntent identifies a pane-navigation action (up/down, page, boundary).
///
/// Intents are the shared vocabulary between the help/key-binding table in
/// keybindings.go and the per-pane key decoders in panelgrid.go and
/// pagedlist.go. The single canonical table is [`NAV_KEYS`] below — both the
/// bindings and the runtime decoders read from it, so a new or changed
/// key only needs to be updated in one place.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum NavIntent {
    /// PARITY: `NavIntentNone` is Go's zero value — `Default` mirrors the
    /// zero-value map miss in `DecodeNav`.
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

/// navKeys is the single source of truth mapping intents to the key strings
/// that trigger them. The order here is the order shown in the help screen.
static NAV_KEYS: &[(NavIntent, &[&str])] = &[
    (NavIntent::Up, &["w", "up"]),
    (NavIntent::Down, &["s", "down"]),
    (NavIntent::Left, &["a", "left"]),
    (NavIntent::Right, &["d", "right"]),
    (NavIntent::PageUp, &["N", "pgup"]),
    (NavIntent::PageDown, &["n", "pgdown"]),
    (NavIntent::Home, &["home"]),
    (NavIntent::End, &["end"]),
];

/// keyToIntent is the inverse lookup built once at package init.
static KEY_TO_INTENT: LazyLock<HashMap<&'static str, NavIntent>> = LazyLock::new(|| {
    let mut m = HashMap::with_capacity(NAV_KEYS.len() * 2);
    for (intent, keys) in NAV_KEYS {
        for key in *keys {
            m.insert(normalize_key(key), *intent);
        }
    }
    m
});

/// DecodeNav returns the NavIntent a key press represents, or
/// [`NavIntent::None`] when the key is not a navigation key.
pub fn decode_nav(msg: &KeyEvent) -> NavIntent {
    // PARITY: a Go map read on a missing key yields the zero value
    // (NavIntentNone).
    KEY_TO_INTENT
        .get(normalize_key(&msg.key_string()))
        .copied()
        .unwrap_or(NavIntent::None)
}

/// NavKeysFor returns the canonical key strings bound to an intent. The
/// slice is shared; callers must not mutate it.
pub fn nav_keys_for(intent: NavIntent) -> &'static [&'static str] {
    for (entry_intent, keys) in NAV_KEYS {
        if *entry_intent == intent {
            return keys;
        }
    }
    // PARITY: Go returns nil for an unknown intent; an empty slice reads
    // the same (ranging nil is a no-op).
    &[]
}

/// concatKeys joins multiple key-lists into one slice for binding entries
/// that handle several intents with a single handler.
pub(crate) fn concat_keys(lists: &[&'static [&'static str]]) -> Vec<&'static str> {
    let mut n = 0;
    for l in lists {
        n += l.len();
    }
    let mut out = Vec::with_capacity(n);
    for l in lists {
        out.extend_from_slice(l);
    }
    out
}

/// Transliteration of `navhelpers_test.go`'s message constructors, shared by
/// the key-handling test transliterations (Go consumers: mediapane_test.go,
/// runhandlers_test.go, symon_keyhandling_test.go,
/// workspace_keyhandling_test.go).
// PHASE-5: `primary_nav_msg`/`secondary_nav_msg` gain their in-crate callers
// when those test files are transliterated; dead_code is allowed until then.
#[cfg(test)]
#[allow(dead_code)]
pub(crate) mod test_helpers {
    use super::{NavIntent, nav_keys_for};
    use crate::key::{KeyCode, KeyEvent, KeyMods};

    pub(crate) fn primary_nav_msg(intent: NavIntent) -> KeyEvent {
        nav_msg_at(intent, 0)
    }

    pub(crate) fn secondary_nav_msg(intent: NavIntent) -> KeyEvent {
        nav_msg_at(intent, 1)
    }

    pub(crate) fn nav_msg_at(intent: NavIntent, variant: usize) -> KeyEvent {
        let keys = nav_keys_for(intent);
        assert!(
            keys.len() > variant,
            "intent {intent:?} is missing variant {variant}"
        );
        nav_binding_msg(keys[variant])
    }

    pub(crate) fn nav_binding_msg(key: &str) -> KeyEvent {
        let code = match key {
            "up" => Some(KeyCode::Up),
            "down" => Some(KeyCode::Down),
            "left" => Some(KeyCode::Left),
            "right" => Some(KeyCode::Right),
            "pgup" => Some(KeyCode::PgUp),
            "pgdown" => Some(KeyCode::PgDown),
            "home" => Some(KeyCode::Home),
            "end" => Some(KeyCode::End),
            _ => None,
        };
        if let Some(code) = code {
            return KeyEvent {
                code,
                text: None,
                mods: KeyMods::NONE,
            };
        }

        let runes: Vec<char> = key.chars().collect();
        assert_eq!(runes.len(), 1, "unsupported nav binding {key:?}");
        KeyEvent {
            code: KeyCode::Char(runes[0]),
            text: Some(key.to_string()),
            mods: KeyMods::NONE,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::test_helpers::nav_msg_at;
    use super::*;
    use crate::key::{KeyCode, KeyMods};

    /// Go: `TestDecodeNav_MatchesDeclaredBindings` (navhelpers_test.go).
    #[test]
    fn decode_nav_matches_declared_bindings() {
        let intents = [
            NavIntent::Up,
            NavIntent::Down,
            NavIntent::Left,
            NavIntent::Right,
            NavIntent::PageUp,
            NavIntent::PageDown,
            NavIntent::Home,
            NavIntent::End,
        ];
        for intent in intents {
            let keys = nav_keys_for(intent);
            assert!(!keys.is_empty(), "intent {intent:?} should have keys");
            for (i, key) in keys.iter().enumerate() {
                assert_eq!(
                    decode_nav(&nav_msg_at(intent, i)),
                    intent,
                    "binding {key:?} should decode to intent {intent:?}"
                );
            }
        }

        assert_eq!(
            decode_nav(&KeyEvent {
                code: KeyCode::Char('q'),
                text: Some("q".to_string()),
                mods: KeyMods::NONE,
            }),
            NavIntent::None
        );
    }
}

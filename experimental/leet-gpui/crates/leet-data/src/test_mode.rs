//! Determinism hooks, mirroring `core/internal/leet/testmode.go`.
//!
//! The differential harness runs both implementations with
//! `WANDB_LEET_TEST=1`; frames must be a pure function of
//! (fixture, scenario events, terminal size). See the Go file and
//! docs/PARITY.md for the full hook list.

use std::sync::OnceLock;

/// Whether determinism hooks are active (`WANDB_LEET_TEST=1`).
pub fn enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| std::env::var("WANDB_LEET_TEST").as_deref() == Ok("1"))
}

/// Whether the forced background is light (`WANDB_LEET_TEST_BG=light`).
/// Only meaningful in test mode; the default is a dark background.
pub fn forced_light_background() -> bool {
    static LIGHT: OnceLock<bool> = OnceLock::new();
    *LIGHT.get_or_init(|| std::env::var("WANDB_LEET_TEST_BG").as_deref() == Ok("light"))
}

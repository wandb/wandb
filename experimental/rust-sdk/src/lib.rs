//! Experimental Rust client for [Weights & Biases](https://wandb.ai) (W&B),
//! the AI developer platform.
//!
//! Like the Python SDK, this crate is a thin client for the `wandb-core`
//! service, which it starts as a child process and communicates with over a
//! socket. The `wandb-core` binary ships with the `wandb` Python package; it
//! is found via the `WANDB_CORE_PATH` environment variable or on `PATH`.
//!
//! ```no_run
//! use serde_json::json;
//!
//! fn main() -> wandb::Result<()> {
//!     let run = wandb::init(wandb::Settings {
//!         project: Some("my-project".to_string()),
//!         ..Default::default()
//!     })?;
//!
//!     run.update_config(json!({"learning_rate": 3e-4}))?;
//!     for step in 0..10 {
//!         run.log(json!({"loss": 1.0 / (step + 1) as f64}))?;
//!     }
//!     run.finish()
//! }
//! ```

mod connection;
mod error;
mod launcher;
mod printer;
mod run;
mod session;
mod settings;

#[allow(clippy::all, rustdoc::all)]
#[rustfmt::skip]
pub mod wandb_internal;

pub use error::{Error, Result};
pub use run::Run;
pub use session::Session;
pub use settings::{Mode, Settings};

/// Starts a new run in its own session.
///
/// The wandb-core service shuts down when the returned run is finished or
/// dropped. To host several runs in one service process, use [`Session`].
pub fn init(settings: Settings) -> Result<Run> {
    Session::new(settings)?.init_run()
}

/// Generates a random ID of `length` lowercase alphanumeric characters.
pub(crate) fn generate_id(length: usize) -> String {
    use rand::Rng;

    const ALPHABET: &[u8] = b"abcdefghijklmnopqrstuvwxyz0123456789";
    let mut rng = rand::rng();
    (0..length)
        .map(|_| ALPHABET[rng.random_range(0..ALPHABET.len())] as char)
        .collect()
}

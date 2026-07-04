use std::time::Duration;

/// An error returned by the W&B SDK.
#[derive(Debug, thiserror::Error)]
#[non_exhaustive]
pub enum Error {
    /// An I/O failure, e.g. while talking to the wandb-core service.
    #[error(transparent)]
    Io(#[from] std::io::Error),

    /// Failed to start or connect to the wandb-core service.
    #[error("wandb-core service: {0}")]
    Service(String),

    /// The connection to wandb-core closed while a response was pending.
    #[error("connection to wandb-core closed")]
    ConnectionClosed,

    /// A request to wandb-core did not complete within the deadline.
    #[error("timed out after {0:?} waiting for wandb-core")]
    Timeout(Duration),

    /// An error reported by wandb-core or the W&B server.
    #[error("{0}")]
    Server(String),

    /// A response from wandb-core did not have the expected type.
    #[error("unexpected response from wandb-core: {0}")]
    UnexpectedResponse(&'static str),

    /// Invalid input, e.g. logging a value that is not a JSON object.
    #[error("invalid input: {0}")]
    InvalidInput(String),
}

/// A specialized `Result` type for W&B SDK operations.
pub type Result<T> = std::result::Result<T, Error>;

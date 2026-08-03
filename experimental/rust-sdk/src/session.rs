//! A session owns a wandb-core service process and the connection to it.

use std::sync::Arc;
use std::time::Duration;

use crate::connection::Connection;
use crate::error::{Error, Result};
use crate::launcher::CoreProcess;
use crate::run::Run;
use crate::settings::Settings;
use crate::wandb_internal as pb;

const AUTHENTICATE_TIMEOUT: Duration = Duration::from_secs(30);

/// How long to let wandb-core finish uploading run data on shutdown.
/// Process exit is the signal that all data has been flushed.
const TEARDOWN_TIMEOUT: Duration = Duration::from_secs(300);

/// A connection to a wandb-core service that can host multiple runs.
///
/// The service process is started on creation and shut down when the
/// session and all of its runs are dropped.
pub struct Session {
    inner: Arc<SessionInner>,
}

impl Session {
    /// Starts wandb-core and connects to it.
    pub fn new(settings: Settings) -> Result<Session> {
        let process = CoreProcess::launch()?;
        let connection = Connection::connect(&process.transport)?;
        Ok(Session {
            inner: Arc::new(SessionInner {
                connection,
                process,
                settings,
            }),
        })
    }

    /// Starts a new run.
    pub fn init_run(&self) -> Result<Run> {
        Run::init(Arc::clone(&self.inner))
    }

    /// Verifies the configured API key with the W&B server and returns the
    /// default entity for it.
    pub fn authenticate(&self) -> Result<String> {
        let api_key = self.inner.settings.api_key().ok_or_else(|| {
            Error::InvalidInput("no API key configured; set WANDB_API_KEY".to_string())
        })?;

        // wandb-core responds to authenticate requests without a request_id,
        // echoing `_info` instead; send the request ID as the stream ID too.
        let request_id = crate::generate_id(12);
        let request = pb::ServerRequest {
            request_id: request_id.clone(),
            server_request_type: Some(pb::server_request::ServerRequestType::Authenticate(
                pb::ServerAuthenticateRequest {
                    api_key,
                    base_url: self.inner.settings.base_url(),
                    info: Some(pb::RecordInfo {
                        stream_id: request_id.clone(),
                        ..Default::default()
                    }),
                },
            )),
        };
        let response = self
            .inner
            .connection
            .request(&request_id, request, AUTHENTICATE_TIMEOUT)?;

        match response.server_response_type {
            Some(pb::server_response::ServerResponseType::AuthenticateResponse(auth)) => {
                if auth.error_status.is_empty() {
                    Ok(auth.default_entity)
                } else {
                    Err(Error::Server(auth.error_status))
                }
            }
            _ => Err(Error::UnexpectedResponse("expected authenticate response")),
        }
    }
}

/// Shared session state, kept alive by the session and each of its runs.
pub(crate) struct SessionInner {
    pub connection: Connection,
    process: CoreProcess,
    pub settings: Settings,
}

impl Drop for SessionInner {
    fn drop(&mut self) {
        // Ask wandb-core to flush all runs and exit, then wait for it.
        let _ = self.connection.notify(pb::ServerRequest {
            server_request_type: Some(pb::server_request::ServerRequestType::InformTeardown(
                pb::ServerInformTeardownRequest {
                    exit_code: 0,
                    info: None,
                },
            )),
            ..Default::default()
        });
        self.connection.close();
        if let Err(e) = self.process.join(TEARDOWN_TIMEOUT) {
            tracing::warn!("failed to shut down wandb-core: {e}");
        }
    }
}

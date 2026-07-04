//! A single W&B run.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use crate::error::{Error, Result};
use crate::printer;
use crate::session::SessionInner;
use crate::settings::RunSettings;
use crate::wandb_internal as pb;

const INIT_TIMEOUT: Duration = Duration::from_secs(90);
const RUN_START_TIMEOUT: Duration = Duration::from_secs(30);
const SUMMARY_TIMEOUT: Duration = Duration::from_secs(30);
const FINISH_TIMEOUT: Duration = Duration::from_secs(600);

/// An active W&B run.
///
/// Created with [`crate::init`] or [`crate::Session::init_run`]. Call
/// [`Run::finish`] to flush and upload all data at the end of the run.
pub struct Run {
    settings: RunSettings,
    session: Arc<SessionInner>,
}

impl Run {
    /// The unique ID of the run.
    pub fn id(&self) -> &str {
        &self.settings.run_id
    }

    /// The display name of the run.
    pub fn name(&self) -> &str {
        &self.settings.run_name
    }

    /// The URL of the run in the W&B UI, or `None` in offline mode.
    pub fn url(&self) -> Option<String> {
        if self.settings.offline() {
            None
        } else {
            Some(self.settings.run_url())
        }
    }

    /// Declares the run to wandb-core and waits for it to be created.
    pub(crate) fn init(session: Arc<SessionInner>) -> Result<Run> {
        let settings = RunSettings::resolve(&session.settings);
        let settings_proto = settings.to_proto()?;
        settings.create_dirs()?;
        let mut run = Run { settings, session };

        // Create the stream that owns this run in wandb-core.
        let request_id = crate::generate_id(12);
        run.session.connection.request(
            &request_id,
            pb::ServerRequest {
                request_id: request_id.clone(),
                server_request_type: Some(pb::server_request::ServerRequestType::InformInit(
                    pb::ServerInformInitRequest {
                        settings: Some(settings_proto),
                        info: Some(run.record_info()),
                    },
                )),
            },
            INIT_TIMEOUT,
        )?;

        // The stream now exists in wandb-core; close it if starting the run
        // fails, so that a failed init doesn't leak its resources.
        if let Err(e) = run.start() {
            let _ = run.inform_finish();
            return Err(e);
        }

        if run.settings.offline() {
            printer::print_offline_header();
        } else {
            printer::print_header(&run.settings.run_name, &run.settings.run_url());
        }
        Ok(run)
    }

    /// Creates the run upstream and starts its upload machinery.
    fn start(&mut self) -> Result<()> {
        // Mark the start of the transaction log.
        self.publish(pb::record::RecordType::Header(pb::HeaderRecord::default()))?;

        // Create the run upstream (or locally in offline mode) and adopt the
        // server-assigned attributes.
        let result = self.deliver(
            pb::record::RecordType::Run(pb::RunRecord {
                run_id: self.settings.run_id.clone(),
                entity: self.settings.entity.clone(),
                project: self.settings.project.clone(),
                display_name: self.settings.run_name.clone(),
                tags: self.settings.run_tags.clone(),
                info: Some(self.record_info()),
                ..Default::default()
            }),
            INIT_TIMEOUT,
        )?;
        match result.result_type {
            Some(pb::result::ResultType::RunResult(update)) => {
                if let Some(error) = update.error {
                    return Err(Error::Server(error.message));
                }
                let upserted = update.run.unwrap_or_default();
                self.settings.entity = upserted.entity;
                self.settings.project = upserted.project;
                self.settings.run_name = upserted.display_name;
            }
            _ => return Err(Error::UnexpectedResponse("expected a run result")),
        }

        // Start the run's internal upload machinery.
        self.deliver(
            request_record(pb::request::RequestType::RunStart(pb::RunStartRequest {
                run: Some(pb::RunRecord {
                    run_id: self.settings.run_id.clone(),
                    ..Default::default()
                }),
                info: None,
            })),
            RUN_START_TIMEOUT,
        )?;
        Ok(())
    }

    /// Tells wandb-core that no more messages will be sent for this run,
    /// closing its stream.
    fn inform_finish(&self) -> Result<()> {
        self.publish_server_request(pb::server_request::ServerRequestType::InformFinish(
            pb::ServerInformFinishRequest {
                info: Some(self.record_info()),
            },
        ))
    }

    /// Logs metrics to the run's history.
    ///
    /// `data` must be a JSON object; each call creates one history row.
    ///
    /// ```no_run
    /// # fn main() -> wandb::Result<()> {
    /// # let run = wandb::init(Default::default())?;
    /// run.log(serde_json::json!({"loss": 0.42, "accuracy": 0.9}))?;
    /// # Ok(())
    /// # }
    /// ```
    pub fn log(&self, data: serde_json::Value) -> Result<()> {
        let item = to_items(data)?
            .map(|(key, value_json)| pb::HistoryItem {
                key,
                value_json,
                ..Default::default()
            })
            .collect();
        self.publish(request_record(pb::request::RequestType::PartialHistory(
            pb::PartialHistoryRequest {
                item,
                ..Default::default()
            },
        )))
    }

    /// Updates keys in the run's config.
    ///
    /// `config` must be a JSON object.
    pub fn update_config(&self, config: serde_json::Value) -> Result<()> {
        let update = to_items(config)?
            .map(|(key, value_json)| pb::ConfigItem {
                key,
                value_json,
                ..Default::default()
            })
            .collect();
        self.publish(pb::record::RecordType::Config(pb::ConfigRecord {
            update,
            ..Default::default()
        }))
    }

    /// Updates keys in the run's summary.
    ///
    /// `summary` must be a JSON object. Logging to history also updates the
    /// summary with the latest value of each metric.
    pub fn update_summary(&self, summary: serde_json::Value) -> Result<()> {
        let update = to_items(summary)?
            .map(|(key, value_json)| pb::SummaryItem {
                key,
                value_json,
                ..Default::default()
            })
            .collect();
        self.publish(pb::record::RecordType::Summary(pb::SummaryRecord {
            update,
            ..Default::default()
        }))
    }

    /// Returns the run's current summary as a JSON object.
    pub fn summary(&self) -> Result<serde_json::Value> {
        let items = self.get_summary_items()?;
        let mut summary = serde_json::Map::new();
        for item in items {
            let Ok(value) = serde_json::from_str(&item.value_json) else {
                continue;
            };
            // Items are keyed by either `key` or a `nested_key` path.
            if item.nested_key.is_empty() {
                summary.insert(item.key, value);
                continue;
            }
            let mut node = &mut summary;
            let (leaf, path) = item.nested_key.split_last().expect("checked non-empty");
            for part in path {
                node = node
                    .entry(part.clone())
                    .or_insert_with(|| serde_json::Value::Object(Default::default()))
                    .as_object_mut()
                    .ok_or(Error::UnexpectedResponse(
                        "summary key is both a value and an object",
                    ))?;
            }
            node.insert(leaf.clone(), value);
        }
        Ok(serde_json::Value::Object(summary))
    }

    /// Finishes the run, flushing and uploading all remaining data.
    pub fn finish(self) -> Result<()> {
        self.deliver(
            pb::record::RecordType::Exit(pb::RunExitRecord {
                exit_code: 0,
                ..Default::default()
            }),
            FINISH_TIMEOUT,
        )?;

        // Fetch final history and summary for the footer, best-effort.
        let history = self.sampled_history().unwrap_or_default();
        let summary: HashMap<String, String> = self
            .get_summary_items()
            .unwrap_or_default()
            .into_iter()
            .map(|item| (item.key, item.value_json))
            .collect();
        let sparklines: HashMap<String, (Vec<f32>, Option<String>)> = history
            .into_iter()
            .map(|(key, values)| {
                let summary_value = summary.get(&key).cloned();
                (key, (values, summary_value))
            })
            .collect();

        // Tell wandb-core no more messages will be sent for this run.
        self.inform_finish()?;

        let sync_dir = self.settings.sync_dir().to_string_lossy().into_owned();
        if self.settings.offline() {
            printer::print_offline_footer(&sync_dir, sparklines);
        } else {
            printer::print_footer(
                &self.settings.run_name,
                &self.settings.run_url(),
                &sync_dir,
                sparklines,
            );
        }
        Ok(())
    }

    /// Returns sampled values of each history metric, for sparklines.
    fn sampled_history(&self) -> Result<HashMap<String, Vec<f32>>> {
        let result = self.deliver(
            request_record(pb::request::RequestType::SampledHistory(
                pb::SampledHistoryRequest { info: None },
            )),
            SUMMARY_TIMEOUT,
        )?;
        let items = match response_of(result)? {
            pb::response::ResponseType::SampledHistoryResponse(r) => r.item,
            _ => return Err(Error::UnexpectedResponse("expected sampled history")),
        };
        Ok(items
            .into_iter()
            .map(|item| {
                let values = if item.values_float.is_empty() {
                    item.values_int.iter().map(|&v| v as f32).collect()
                } else {
                    item.values_float
                };
                (item.key, values)
            })
            .collect())
    }

    fn get_summary_items(&self) -> Result<Vec<pb::SummaryItem>> {
        let result = self.deliver(
            request_record(pb::request::RequestType::GetSummary(
                pb::GetSummaryRequest { info: None },
            )),
            SUMMARY_TIMEOUT,
        )?;
        match response_of(result)? {
            pb::response::ResponseType::GetSummaryResponse(r) => Ok(r.item),
            _ => Err(Error::UnexpectedResponse("expected a summary response")),
        }
    }

    fn record_info(&self) -> pb::RecordInfo {
        pb::RecordInfo {
            stream_id: self.settings.run_id.clone(),
            ..Default::default()
        }
    }

    /// Sends a record for this run without waiting for a response.
    fn publish(&self, record_type: pb::record::RecordType) -> Result<()> {
        self.publish_server_request(pb::server_request::ServerRequestType::RecordPublish(
            self.record(record_type),
        ))
    }

    fn publish_server_request(
        &self,
        request_type: pb::server_request::ServerRequestType,
    ) -> Result<()> {
        self.session.connection.notify(pb::ServerRequest {
            server_request_type: Some(request_type),
            ..Default::default()
        })
    }

    /// Sends a record for this run and waits for its result.
    fn deliver(
        &self,
        record_type: pb::record::RecordType,
        timeout: Duration,
    ) -> Result<pb::Result> {
        let request_id = crate::generate_id(12);
        let mut record = self.record(record_type);
        record.control = Some(pb::Control {
            mailbox_slot: request_id.clone(),
            req_resp: true,
            ..Default::default()
        });

        let response = self.session.connection.request(
            &request_id,
            pb::ServerRequest {
                request_id: request_id.clone(),
                server_request_type: Some(pb::server_request::ServerRequestType::RecordPublish(
                    record,
                )),
            },
            timeout,
        )?;
        match response.server_response_type {
            Some(pb::server_response::ServerResponseType::ResultCommunicate(result)) => Ok(result),
            _ => Err(Error::UnexpectedResponse("expected a record result")),
        }
    }

    fn record(&self, record_type: pb::record::RecordType) -> pb::Record {
        pb::Record {
            record_type: Some(record_type),
            info: Some(self.record_info()),
            ..Default::default()
        }
    }
}

/// Wraps a request in a record, as required by the wandb protocol.
fn request_record(request_type: pb::request::RequestType) -> pb::record::RecordType {
    pb::record::RecordType::Request(pb::Request {
        request_type: Some(request_type),
    })
}

/// Unwraps the response carried by a record result.
fn response_of(result: pb::Result) -> Result<pb::response::ResponseType> {
    match result.result_type {
        Some(pb::result::ResultType::Response(pb::Response {
            response_type: Some(response_type),
        })) => Ok(response_type),
        _ => Err(Error::UnexpectedResponse("expected a request response")),
    }
}

/// Converts a JSON object into `(key, value_json)` pairs.
fn to_items(data: serde_json::Value) -> Result<impl Iterator<Item = (String, String)>> {
    match data {
        serde_json::Value::Object(map) => {
            Ok(map.into_iter().map(|(key, value)| (key, value.to_string())))
        }
        other => Err(Error::InvalidInput(format!(
            "expected a JSON object, got: {other}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn to_items_requires_object() {
        assert!(to_items(serde_json::json!(42)).is_err());
        let items: Vec<_> = to_items(serde_json::json!({"a": 1, "b": "x"}))
            .unwrap()
            .collect();
        assert_eq!(
            items,
            vec![
                ("a".to_string(), "1".to_string()),
                ("b".to_string(), "\"x\"".to_string()),
            ]
        );
    }
}

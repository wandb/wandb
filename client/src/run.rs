use pyo3::prelude::*;

use crate::connection::Interface;
use crate::wandb_internal;
use std::collections::HashMap;
use tracing;

use crate::session::Settings;

#[pyclass]
pub struct Run {
    pub id: String,
    pub settings: Settings,
    pub interface: Interface,
}

#[pymethods]
impl Run {
    pub fn init(&mut self) {
        tracing::debug!("Initializing run {}", self.id);

        let server_inform_init_request = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::InformInit(
                    wandb_internal::ServerInformInitRequest {
                        settings: Some(self.settings.proto.clone()),
                        info: Some(wandb_internal::RecordInfo {
                            stream_id: self.id.clone(),
                            ..Default::default()
                        }),
                    },
                ),
            ),
        };

        self.interface
            .conn
            .send_message(&server_inform_init_request)
            .unwrap();

        let server_publish_run_request = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::RecordCommunicate(
                    wandb_internal::Record {
                        record_type: Some(wandb_internal::record::RecordType::Run(
                            wandb_internal::RunRecord {
                                run_id: self.id.clone(),
                                // display_name: "gooba-gaba".to_string(),
                                info: Some(wandb_internal::RecordInfo {
                                    stream_id: self.id.clone(),
                                    ..Default::default()
                                }),
                                ..Default::default()
                            },
                        )),
                        info: Some(wandb_internal::RecordInfo {
                            stream_id: self.id.clone(),
                            ..Default::default()
                        }),
                        ..Default::default()
                    },
                ),
            ),
        };

        self.interface
            .conn
            .send_message(&server_publish_run_request)
            .unwrap();

        let mut server_publish_run_start = wandb_internal::Record {
            record_type: Some(wandb_internal::record::RecordType::Request(
                wandb_internal::Request {
                    request_type: Some(wandb_internal::request::RequestType::RunStart(
                        wandb_internal::RunStartRequest {
                            run: Some(wandb_internal::RunRecord {
                                run_id: self.id.clone(),
                                ..Default::default()
                            }),
                            info: Some(wandb_internal::RequestInfo {
                                stream_id: self.id.clone(),
                                ..Default::default()
                            }),
                        },
                    )),
                },
            )),
            control: Some(wandb_internal::Control {
                local: true,
                ..Default::default()
            }),
            info: Some(wandb_internal::RecordInfo {
                stream_id: self.id.clone(),
                ..Default::default()
            }),
            ..Default::default()
        };
        let result = self
            .interface
            .conn
            .send_and_recv_message(&mut server_publish_run_start, &mut self.interface.handles);

        tracing::debug!("Result: {:?}", result);
    }

    pub fn log(&self, data: HashMap<String, f64>) {
        tracing::debug!("Logging to run {}", self.id);

        // let history_record = wandb_internal::HistoryRecord {
        //     item: data
        //         .iter()
        //         .map(|(k, v)| wandb_internal::HistoryItem {
        //             key: k.clone(),
        //             value_json: v.to_string(),
        //             ..Default::default()
        //         })
        //         .collect(),
        //     ..Default::default()
        // };

        // let record = wandb_internal::Record {
        //     record_type: Some(wandb_internal::record::RecordType::History(history_record)),
        //     info: Some(wandb_internal::RecordInfo {
        //         stream_id: self.id.clone(),
        //         ..Default::default()
        //     }),
        //     ..Default::default()
        // };

        // let message = wandb_internal::ServerRequest {
        //     server_request_type: Some(
        //         wandb_internal::server_request::ServerRequestType::RecordPublish(record),
        //     ),
        // };

        // self.interface.conn.send_message(&message).unwrap();

        let partial_history_request = wandb_internal::PartialHistoryRequest {
            item: data
                .iter()
                .map(|(k, v)| wandb_internal::HistoryItem {
                    key: k.clone(),
                    value_json: v.to_string(),
                    ..Default::default()
                })
                .collect(),
            ..Default::default()
        };

        let record = wandb_internal::Record {
            record_type: Some(wandb_internal::record::RecordType::Request(
                wandb_internal::Request {
                    request_type: Some(wandb_internal::request::RequestType::PartialHistory(
                        partial_history_request,
                    )),
                },
            )),
            info: Some(wandb_internal::RecordInfo {
                stream_id: self.id.clone(),
                ..Default::default()
            }),
            ..Default::default()
        };

        let message = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::RecordPublish(record),
            ),
        };

        self.interface.conn.send_message(&message).unwrap();
    }

    pub fn finish(&mut self) {
        tracing::debug!("Finishing run {}", self.id);

        let finish_record = wandb_internal::RunExitRecord {
            exit_code: 0,
            info: Some(wandb_internal::RecordInfo {
                stream_id: self.id.clone(),
                ..Default::default()
            }),
            ..Default::default()
        };

        let mut record = wandb_internal::Record {
            record_type: Some(wandb_internal::record::RecordType::Exit(finish_record)),
            info: Some(wandb_internal::RecordInfo {
                stream_id: self.id.clone(),
                ..Default::default()
            }),
            ..Default::default()
        };

        self.interface
            .conn
            .send_and_recv_message(&mut record, &mut self.interface.handles);

        let mut shutdown_request = wandb_internal::Record {
            record_type: Some(wandb_internal::record::RecordType::Request(
                wandb_internal::Request {
                    request_type: Some(wandb_internal::request::RequestType::Shutdown(
                        wandb_internal::ShutdownRequest {
                            info: Some(wandb_internal::RequestInfo {
                                stream_id: self.id.clone(),
                                ..Default::default()
                            }),
                        },
                    )),
                },
            )),
            info: Some(wandb_internal::RecordInfo {
                stream_id: self.id.clone(),
                ..Default::default()
            }),
            ..Default::default()
        };

        let result = self
            .interface
            .conn
            .send_and_recv_message(&mut shutdown_request, &mut self.interface.handles);

        tracing::debug!("Result: {:?}", result);

        let inform_finish_request = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::InformFinish(
                    wandb_internal::ServerInformFinishRequest {
                        info: Some(wandb_internal::RecordInfo {
                            stream_id: self.id.clone(),
                            ..Default::default()
                        }),
                    },
                ),
            ),
        };
        tracing::debug!("Sending inform finish request {:?}", inform_finish_request);
        self.interface
            .conn
            .send_message(&inform_finish_request)
            .unwrap();

        // loop {}
    }
}

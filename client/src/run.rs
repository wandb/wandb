use crate::connection::Connection;
use crate::wandb_internal;
use crate::wandb_internal::Settings;
use std::collections::HashMap;

// #[pyclass]
pub struct Run {
    pub id: String,
    pub settings: Settings,
    pub conn: Connection,
}

// #[pymethods]
impl Run {
    pub fn init(&self) {
        println!("Initializing run {}", self.id);

        let server_inform_init_request = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::InformInit(
                    wandb_internal::ServerInformInitRequest {
                        settings: Some(self.settings.clone()),
                        info: Some(wandb_internal::RecordInfo {
                            stream_id: self.id.clone(),
                            ..Default::default()
                        }),
                    },
                ),
            ),
        };

        self.conn.send_message(&server_inform_init_request).unwrap();

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

        self.conn.send_message(&server_publish_run_request).unwrap();

        let server_publish_run_start = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::RecordCommunicate(
                    wandb_internal::Record {
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
                    },
                ),
            ),
        };
        self.conn.send_message(&server_publish_run_start).unwrap();
    }

    pub fn log(&self, data: HashMap<String, f64>) {
        println!("Logging to run {}", self.id);

        let history_record = wandb_internal::HistoryRecord {
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
            record_type: Some(wandb_internal::record::RecordType::History(history_record)),
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

        self.conn.send_message(&message).unwrap();
    }

    pub fn finish(&self) {
        println!("Finishing run {}", self.id);

        let finish_record = wandb_internal::RunExitRecord {
            exit_code: 0,
            info: Some(wandb_internal::RecordInfo {
                stream_id: self.id.clone(),
                ..Default::default()
            }),
            ..Default::default()
        };

        let record = wandb_internal::Record {
            record_type: Some(wandb_internal::record::RecordType::Exit(finish_record)),
            info: Some(wandb_internal::RecordInfo {
                stream_id: self.id.clone(),
                ..Default::default()
            }),
            ..Default::default()
        };

        let message = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::RecordCommunicate(record),
            ),
        };
        self.conn.send_message(&message).unwrap();

        let message = wandb_internal::ServerRequest {
            server_request_type: Some(
                wandb_internal::server_request::ServerRequestType::RecordCommunicate(
                    wandb_internal::Record {
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
                    },
                ),
            ),
        };
        println!("Sending shutdown request {:?}", message);
        // self.conn.send_message(&message).unwrap();

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
        println!("Sending inform finish request {:?}", inform_finish_request);
        // self.conn.send_message(&inform_finish_request).unwrap();

        loop {}
    }
}

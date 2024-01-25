use pyo3::prelude::*;

use crate::wandb_internal::Settings as SettingsProto;

#[pyclass]
#[derive(Clone)]
pub struct Settings {
    pub proto: SettingsProto,
}

#[pymethods]
impl Settings {
    #[new]
    pub fn new(
        base_url: Option<String>,
        project: Option<String>,
        mode: Option<String>,
        stats_pid: Option<i32>,
        stats_sample_rate_seconds: Option<f64>,
        stats_samples_to_average: Option<i32>,
        // log_internal: Option<String>,
        // sync_file: Option<String>,
    ) -> Settings {
        let pid = std::process::id() as i32;

        let proto = SettingsProto {
            base_url: Some(base_url.unwrap_or("https://api.wandb.ai".to_string())),
            mode: Some(mode.unwrap_or("online".to_string())),
            stats_sample_rate_seconds: Some(stats_sample_rate_seconds.unwrap_or(5.0)),
            stats_samples_to_average: Some(stats_samples_to_average.unwrap_or(1)),
            project: Some(project.unwrap_or("uncategorized".to_string())),
            log_internal: Some("wandb-internal.log".to_string()),
            sync_file: Some("lol.wandb".to_string()),
            stats_pid: Some(stats_pid.unwrap_or(pid)),
            ..Default::default()
        };
        Settings { proto }
    }

    // TODO: auto-generate all getters and setters? tried a bunch of stuff, but no luck so far
    #[getter]
    pub fn base_url(&self) -> String {
        self.proto.base_url.clone().unwrap()
    }

    #[getter]
    pub fn run_name(&self) -> String {
        self.proto.run_name.clone().unwrap()
    }

    #[getter]
    pub fn run_url(&self) -> String {
        self.proto.run_url.clone().unwrap()
    }

    #[getter]
    pub fn sync_dir(&self) -> String {
        self.proto.sync_dir.clone().unwrap()
    }

    #[getter]
    pub fn files_dir(&self) -> String {
        self.proto.files_dir.clone().unwrap()
    }

    #[getter]
    pub fn offline(&self) -> bool {
        self.proto.offline.clone().unwrap()
    }
}

impl Settings {
    pub fn clone(&self) -> Settings {
        let proto = self.proto.clone();
        Settings { proto }
    }
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            proto: SettingsProto {
                base_url: Some("https://api.wandb.ai".to_string()),
                mode: Some("online".to_string()),
                stats_sample_rate_seconds: Some(5.0),
                stats_samples_to_average: Some(1),
                project: Some("uncategorized".to_string()),
                log_internal: Some("wandb-internal.log".to_string()),
                stats_pid: Some(std::process::id() as i32),
                ..Default::default()
            },
        }
    }
}

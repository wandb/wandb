use crate::wandb_internal::Settings as SettingsProto;

#[derive(Clone, Debug)]
pub struct Settings {
    pub proto: SettingsProto,
}

impl Settings {
    pub fn new(
        base_url: Option<String>,
        log_dir: Option<String>,
        log_internal: Option<String>,
        mode: Option<String>,
        project: Option<String>,
        stats_pid: Option<i32>,
        stats_sample_rate_seconds: Option<f64>,
        sync_file: Option<String>,
        sync_dir: Option<String>,
    ) -> Settings {
        let mut proto = Settings::default().proto.clone();

        proto.base_url = base_url.or(proto.base_url);
        proto.log_dir = log_dir.or(proto.log_dir);
        proto.log_internal = log_internal.or(proto.log_internal);
        proto.mode = mode.or(proto.mode);
        proto.project = project.or(proto.project);
        proto.x_stats_pid = stats_pid.or(proto.x_stats_pid);
        proto.x_stats_sampling_interval =
            stats_sample_rate_seconds.or(proto.x_stats_sampling_interval);
        proto.sync_file = sync_file.or(proto.sync_file);
        proto.sync_dir = sync_dir.or(proto.sync_dir);

        Settings { proto }
    }

    // TODO: auto-generate all getters and setters? tried a bunch of stuff, but no luck so far
    pub fn base_url(&self) -> String {
        self.proto.base_url.clone().unwrap()
    }

    pub fn run_name(&self) -> String {
        self.proto.run_name.clone().unwrap()
    }

    pub fn run_url(&self) -> String {
        self.proto.run_url.clone().unwrap()
    }

    pub fn sync_file(&self) -> String {
        self.proto.sync_file.clone().unwrap()
    }

    pub fn sync_dir(&self) -> String {
        self.proto.sync_dir.clone().unwrap()
    }

    pub fn offline(&self) -> bool {
        self.proto.offline.clone().unwrap()
    }

    pub fn log_dir(&self) -> String {
        self.proto.log_dir.clone().unwrap()
    }

    pub fn project(&self) -> String {
        self.proto.project.clone().unwrap()
    }

    pub fn set_project(&mut self, project: String) {
        self.proto.project = Some(project);
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
                log_dir: Some(".wandb/None-None-None/logs".to_string()),
                log_internal: Some("wandb-internal.log".to_string()),
                mode: Some("online".to_string()),
                offline: Some(false),
                project: Some("uncategorized".to_string()),
                x_stats_pid: Some(std::process::id() as i32),
                x_stats_sampling_interval: Some(10.0),
                sync_file: Some("lol.wandb".to_string()),
                sync_dir: Some(".wandb/None-None-None".to_string()),
                run_url: Some("undefined".to_string()),
                run_name: Some("gloomy-morning-1".to_string()),
                ..Default::default()
            },
        }
    }
}

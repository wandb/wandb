///
/// _RecordInfo, _RequestInfo: extra info for all records and requests
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RecordInfo {
    #[prost(string, tag = "1")]
    pub stream_id: ::prost::alloc::string::String,
    #[prost(string, tag = "100")]
    pub tracelog_id: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RequestInfo {
    #[prost(string, tag = "1")]
    pub stream_id: ::prost::alloc::string::String,
}
///
/// _ResultInfo: extra info for all results
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ResultInfo {
    #[prost(string, tag = "100")]
    pub tracelog_id: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ListStringValue {
    #[prost(string, repeated, tag = "1")]
    pub value: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct MapStringKeyStringValue {
    #[prost(map = "string, string", tag = "1")]
    pub value: ::std::collections::HashMap<
        ::prost::alloc::string::String,
        ::prost::alloc::string::String,
    >,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct MapStringKeyMapStringKeyStringValue {
    #[prost(map = "string, message", tag = "1")]
    pub value: ::std::collections::HashMap<
        ::prost::alloc::string::String,
        MapStringKeyStringValue,
    >,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct OpenMetricsFilters {
    #[prost(oneof = "open_metrics_filters::Value", tags = "1, 2")]
    pub value: ::core::option::Option<open_metrics_filters::Value>,
}
/// Nested message and enum types in `OpenMetricsFilters`.
pub mod open_metrics_filters {
    #[allow(clippy::derive_partial_eq_without_eq)]
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum Value {
        #[prost(message, tag = "1")]
        Sequence(super::ListStringValue),
        #[prost(message, tag = "2")]
        Mapping(super::MapStringKeyMapStringKeyStringValue),
    }
}
/// Settings for the SDK.
///
/// There is a hierarchy of settings, with at least the following levels:
///
/// 1. User process settings
/// 2. Run settings
///
/// Some fields such as `run_id` only make sense at the run level.
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Settings {
    /// The W&B API key.
    ///
    /// This can be empty if we're in offline mode.
    #[prost(message, optional, tag = "55")]
    pub api_key: ::core::option::Option<::prost::alloc::string::String>,
    /// The ID of the run.
    #[prost(message, optional, tag = "107")]
    pub run_id: ::core::option::Option<::prost::alloc::string::String>,
    /// The W&B URL where the run can be viewed.
    #[prost(message, optional, tag = "113")]
    pub run_url: ::core::option::Option<::prost::alloc::string::String>,
    /// The W&B project ID.
    #[prost(message, optional, tag = "97")]
    pub project: ::core::option::Option<::prost::alloc::string::String>,
    /// The W&B entity, like a user or a team.
    #[prost(message, optional, tag = "69")]
    pub entity: ::core::option::Option<::prost::alloc::string::String>,
    /// The directory for storing log files.
    #[prost(message, optional, tag = "85")]
    pub log_dir: ::core::option::Option<::prost::alloc::string::String>,
    /// Filename to use for internal logs.
    #[prost(message, optional, tag = "86")]
    pub log_internal: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "1")]
    pub args: ::core::option::Option<ListStringValue>,
    #[prost(message, optional, tag = "2")]
    pub aws_lambda: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "3")]
    pub async_upload_concurrency_limit: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "4")]
    pub cli_only_mode: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "5")]
    pub colab: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "6")]
    pub cuda: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "7")]
    pub disable_meta: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "8")]
    pub disable_service: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "9")]
    pub disable_setproctitle: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "10")]
    pub disable_stats: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "11")]
    pub disable_viewer: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "12")]
    pub except_exit: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "13")]
    pub executable: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "14")]
    pub extra_http_headers: ::core::option::Option<MapStringKeyStringValue>,
    #[prost(message, optional, tag = "15")]
    pub file_stream_timeout_seconds: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "16")]
    pub flow_control_custom: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "17")]
    pub flow_control_disabled: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "18")]
    pub internal_check_process: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "19")]
    pub internal_queue_timeout: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "20")]
    pub ipython: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "21")]
    pub jupyter: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "22")]
    pub jupyter_root: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "23")]
    pub kaggle: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "24")]
    pub live_policy_rate_limit: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "25")]
    pub live_policy_wait_time: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "26")]
    pub log_level: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "27")]
    pub network_buffer: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "28")]
    pub noop: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "29")]
    pub notebook: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "30")]
    pub offline: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "31")]
    pub sync: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "32")]
    pub os: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "33")]
    pub platform: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "34")]
    pub python: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "35")]
    pub runqueue_item_id: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "36")]
    pub require_core: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "37")]
    pub save_requirements: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "38")]
    pub service_transport: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "39")]
    pub service_wait: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "40")]
    pub start_datetime: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "41")]
    pub start_time: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "42")]
    pub stats_pid: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "43")]
    pub stats_sample_rate_seconds: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "44")]
    pub stats_samples_to_average: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "45")]
    pub stats_join_assets: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "46")]
    pub stats_neuron_monitor_config_path: ::core::option::Option<
        ::prost::alloc::string::String,
    >,
    #[prost(message, optional, tag = "47")]
    pub stats_open_metrics_endpoints: ::core::option::Option<MapStringKeyStringValue>,
    #[prost(message, optional, tag = "48")]
    pub stats_open_metrics_filters: ::core::option::Option<OpenMetricsFilters>,
    #[prost(message, optional, tag = "49")]
    pub tmp_code_dir: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "50")]
    pub tracelog: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "51")]
    pub unsaved_keys: ::core::option::Option<ListStringValue>,
    #[prost(message, optional, tag = "52")]
    pub windows: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "53")]
    pub allow_val_change: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "54")]
    pub anonymous: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "56")]
    pub azure_account_url_to_access_key: ::core::option::Option<MapStringKeyStringValue>,
    #[prost(message, optional, tag = "57")]
    pub base_url: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "58")]
    pub code_dir: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "59")]
    pub config_paths: ::core::option::Option<ListStringValue>,
    #[prost(message, optional, tag = "60")]
    pub console: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "61")]
    pub deployment: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "62")]
    pub disable_code: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "63")]
    pub disable_git: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "64")]
    pub disable_hints: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "65")]
    pub disable_job_creation: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "66")]
    pub disabled: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "67")]
    pub docker: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "68")]
    pub email: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "70")]
    pub files_dir: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "71")]
    pub force: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "72")]
    pub git_commit: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "73")]
    pub git_remote: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "74")]
    pub git_remote_url: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "75")]
    pub git_root: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "76")]
    pub heartbeat_seconds: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "77")]
    pub host: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "78")]
    pub ignore_globs: ::core::option::Option<ListStringValue>,
    #[prost(message, optional, tag = "79")]
    pub init_timeout: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "80")]
    pub is_local: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "81")]
    pub job_source: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "82")]
    pub label_disable: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "83")]
    pub launch: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "84")]
    pub launch_config_path: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "87")]
    pub log_symlink_internal: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "88")]
    pub log_symlink_user: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "89")]
    pub log_user: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "90")]
    pub login_timeout: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "92")]
    pub mode: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "93")]
    pub notebook_name: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "94")]
    pub problem: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "95")]
    pub program: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "96")]
    pub program_relpath: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "98")]
    pub project_url: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "99")]
    pub quiet: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "100")]
    pub reinit: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "101")]
    pub relogin: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "102")]
    pub resume: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "103")]
    pub resume_fname: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "104")]
    pub resumed: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "105")]
    pub root_dir: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "106")]
    pub run_group: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "108")]
    pub run_job_type: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "109")]
    pub run_mode: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "110")]
    pub run_name: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "111")]
    pub run_notes: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "112")]
    pub run_tags: ::core::option::Option<ListStringValue>,
    #[prost(message, optional, tag = "114")]
    pub sagemaker_disable: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "115")]
    pub save_code: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "116")]
    pub settings_system: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "117")]
    pub settings_workspace: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "118")]
    pub show_colors: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "119")]
    pub show_emoji: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "120")]
    pub show_errors: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "121")]
    pub show_info: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "122")]
    pub show_warnings: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "123")]
    pub silent: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "124")]
    pub start_method: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "125")]
    pub strict: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "126")]
    pub summary_errors: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "127")]
    pub summary_timeout: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "128")]
    pub summary_warnings: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "129")]
    pub sweep_id: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "130")]
    pub sweep_param_path: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "131")]
    pub sweep_url: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "132")]
    pub symlink: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "133")]
    pub sync_dir: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "134")]
    pub sync_file: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "135")]
    pub sync_symlink_latest: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "136")]
    pub system_sample: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "137")]
    pub system_sample_seconds: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "138")]
    pub table_raise_on_max_row_limit_exceeded: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "139")]
    pub timespec: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "140")]
    pub tmp_dir: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "141")]
    pub username: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "142")]
    pub wandb_dir: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "143")]
    pub jupyter_name: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "144")]
    pub jupyter_path: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "145")]
    pub job_name: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "146")]
    pub stats_disk_paths: ::core::option::Option<ListStringValue>,
    #[prost(message, optional, tag = "147")]
    pub file_stream_retry_max: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "148")]
    pub file_stream_retry_wait_min_seconds: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "149")]
    pub file_stream_retry_wait_max_seconds: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "150")]
    pub file_transfer_retry_max: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "151")]
    pub file_transfer_retry_wait_min_seconds: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "152")]
    pub file_transfer_retry_wait_max_seconds: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "153")]
    pub file_transfer_timeout_seconds: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "154")]
    pub graphql_retry_max: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "155")]
    pub graphql_retry_wait_min_seconds: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "156")]
    pub graphql_retry_wait_max_seconds: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "157")]
    pub graphql_timeout_seconds: ::core::option::Option<f64>,
    #[prost(message, optional, tag = "158")]
    pub disable_machine_info: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "159")]
    pub program_abspath: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "160")]
    pub colab_url: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "161")]
    pub stats_buffer_size: ::core::option::Option<i32>,
    #[prost(message, optional, tag = "162")]
    pub shared: ::core::option::Option<bool>,
    #[prost(message, optional, tag = "163")]
    pub code_path_local: ::core::option::Option<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "200")]
    pub proxies: ::core::option::Option<MapStringKeyStringValue>,
}
///
/// Telemetry
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TelemetryRecord {
    #[prost(message, optional, tag = "1")]
    pub imports_init: ::core::option::Option<Imports>,
    #[prost(message, optional, tag = "2")]
    pub imports_finish: ::core::option::Option<Imports>,
    #[prost(message, optional, tag = "3")]
    pub feature: ::core::option::Option<Feature>,
    #[prost(string, tag = "4")]
    pub python_version: ::prost::alloc::string::String,
    #[prost(string, tag = "5")]
    pub cli_version: ::prost::alloc::string::String,
    #[prost(string, tag = "6")]
    pub huggingface_version: ::prost::alloc::string::String,
    /// string  framework = 7;
    #[prost(message, optional, tag = "8")]
    pub env: ::core::option::Option<Env>,
    #[prost(message, optional, tag = "9")]
    pub label: ::core::option::Option<Labels>,
    #[prost(message, optional, tag = "10")]
    pub deprecated: ::core::option::Option<Deprecated>,
    #[prost(message, optional, tag = "11")]
    pub issues: ::core::option::Option<Issues>,
    #[prost(string, tag = "12")]
    pub core_version: ::prost::alloc::string::String,
    #[prost(string, tag = "13")]
    pub platform: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TelemetryResult {}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Imports {
    #[prost(bool, tag = "1")]
    pub torch: bool,
    #[prost(bool, tag = "2")]
    pub keras: bool,
    #[prost(bool, tag = "3")]
    pub tensorflow: bool,
    #[prost(bool, tag = "4")]
    pub fastai: bool,
    #[prost(bool, tag = "5")]
    pub sklearn: bool,
    #[prost(bool, tag = "6")]
    pub xgboost: bool,
    #[prost(bool, tag = "7")]
    pub catboost: bool,
    #[prost(bool, tag = "8")]
    pub lightgbm: bool,
    #[prost(bool, tag = "9")]
    pub pytorch_lightning: bool,
    #[prost(bool, tag = "10")]
    pub ignite: bool,
    #[prost(bool, tag = "11")]
    pub transformers: bool,
    #[prost(bool, tag = "12")]
    pub jax: bool,
    #[prost(bool, tag = "13")]
    pub metaflow: bool,
    #[prost(bool, tag = "14")]
    pub allennlp: bool,
    #[prost(bool, tag = "15")]
    pub autogluon: bool,
    #[prost(bool, tag = "16")]
    pub autokeras: bool,
    /// bool avalanche = 17;
    #[prost(bool, tag = "18")]
    pub catalyst: bool,
    /// bool dalle_pytorch = 19;
    /// bool datasets = 20;
    #[prost(bool, tag = "21")]
    pub deepchem: bool,
    #[prost(bool, tag = "22")]
    pub deepctr: bool,
    /// bool deeppavlov = 23;
    /// bool detectron = 24;
    /// bool paddle = 25;
    /// bool parlai = 26;
    /// bool prophet = 27;
    #[prost(bool, tag = "28")]
    pub pycaret: bool,
    #[prost(bool, tag = "29")]
    pub pytorchvideo: bool,
    #[prost(bool, tag = "30")]
    pub ray: bool,
    #[prost(bool, tag = "31")]
    pub simpletransformers: bool,
    #[prost(bool, tag = "32")]
    pub skorch: bool,
    #[prost(bool, tag = "33")]
    pub spacy: bool,
    #[prost(bool, tag = "34")]
    pub flash: bool,
    #[prost(bool, tag = "35")]
    pub optuna: bool,
    #[prost(bool, tag = "36")]
    pub recbole: bool,
    #[prost(bool, tag = "37")]
    pub mmcv: bool,
    #[prost(bool, tag = "38")]
    pub mmdet: bool,
    #[prost(bool, tag = "39")]
    pub torchdrug: bool,
    #[prost(bool, tag = "40")]
    pub torchtext: bool,
    #[prost(bool, tag = "41")]
    pub torchvision: bool,
    #[prost(bool, tag = "42")]
    pub elegy: bool,
    #[prost(bool, tag = "43")]
    pub detectron2: bool,
    #[prost(bool, tag = "44")]
    pub flair: bool,
    #[prost(bool, tag = "45")]
    pub flax: bool,
    #[prost(bool, tag = "46")]
    pub syft: bool,
    #[prost(bool, tag = "47")]
    pub tts: bool,
    #[prost(bool, tag = "48")]
    pub monai: bool,
    #[prost(bool, tag = "49")]
    pub huggingface_hub: bool,
    #[prost(bool, tag = "50")]
    pub hydra: bool,
    #[prost(bool, tag = "51")]
    pub datasets: bool,
    #[prost(bool, tag = "52")]
    pub sacred: bool,
    #[prost(bool, tag = "53")]
    pub joblib: bool,
    #[prost(bool, tag = "54")]
    pub dask: bool,
    #[prost(bool, tag = "55")]
    pub asyncio: bool,
    #[prost(bool, tag = "56")]
    pub paddleocr: bool,
    #[prost(bool, tag = "57")]
    pub ppdet: bool,
    #[prost(bool, tag = "58")]
    pub paddleseg: bool,
    #[prost(bool, tag = "59")]
    pub paddlenlp: bool,
    #[prost(bool, tag = "60")]
    pub mmseg: bool,
    #[prost(bool, tag = "61")]
    pub mmocr: bool,
    #[prost(bool, tag = "62")]
    pub mmcls: bool,
    #[prost(bool, tag = "63")]
    pub timm: bool,
    #[prost(bool, tag = "64")]
    pub fairseq: bool,
    #[prost(bool, tag = "65")]
    pub deepchecks: bool,
    #[prost(bool, tag = "66")]
    pub composer: bool,
    #[prost(bool, tag = "67")]
    pub sparseml: bool,
    #[prost(bool, tag = "68")]
    pub anomalib: bool,
    #[prost(bool, tag = "69")]
    pub zenml: bool,
    #[prost(bool, tag = "70")]
    pub colossalai: bool,
    #[prost(bool, tag = "71")]
    pub accelerate: bool,
    #[prost(bool, tag = "72")]
    pub merlin: bool,
    #[prost(bool, tag = "73")]
    pub nanodet: bool,
    #[prost(bool, tag = "74")]
    pub segmentation_models_pytorch: bool,
    #[prost(bool, tag = "75")]
    pub sentence_transformers: bool,
    #[prost(bool, tag = "76")]
    pub dgl: bool,
    #[prost(bool, tag = "77")]
    pub torch_geometric: bool,
    #[prost(bool, tag = "78")]
    pub jina: bool,
    #[prost(bool, tag = "79")]
    pub kornia: bool,
    #[prost(bool, tag = "80")]
    pub albumentations: bool,
    #[prost(bool, tag = "81")]
    pub keras_cv: bool,
    #[prost(bool, tag = "82")]
    pub mmengine: bool,
    #[prost(bool, tag = "83")]
    pub diffusers: bool,
    #[prost(bool, tag = "84")]
    pub trl: bool,
    #[prost(bool, tag = "85")]
    pub trlx: bool,
    #[prost(bool, tag = "86")]
    pub langchain: bool,
    #[prost(bool, tag = "87")]
    pub llama_index: bool,
    #[prost(bool, tag = "88")]
    pub stability_sdk: bool,
    #[prost(bool, tag = "89")]
    pub prefect: bool,
    #[prost(bool, tag = "90")]
    pub prefect_ray: bool,
    /// pinecone-client
    #[prost(bool, tag = "91")]
    pub pinecone: bool,
    #[prost(bool, tag = "92")]
    pub chromadb: bool,
    /// weaviate-client
    #[prost(bool, tag = "93")]
    pub weaviate: bool,
    #[prost(bool, tag = "94")]
    pub promptlayer: bool,
    #[prost(bool, tag = "95")]
    pub openai: bool,
    #[prost(bool, tag = "96")]
    pub cohere: bool,
    #[prost(bool, tag = "97")]
    pub anthropic: bool,
    #[prost(bool, tag = "98")]
    pub peft: bool,
    #[prost(bool, tag = "99")]
    pub optimum: bool,
    #[prost(bool, tag = "100")]
    pub evaluate: bool,
    #[prost(bool, tag = "101")]
    pub langflow: bool,
    /// keras-core
    #[prost(bool, tag = "102")]
    pub keras_core: bool,
    /// lightning-fabric
    #[prost(bool, tag = "103")]
    pub lightning_fabric: bool,
    /// curated-transformers
    #[prost(bool, tag = "104")]
    pub curated_transformers: bool,
    #[prost(bool, tag = "105")]
    pub orjson: bool,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Feature {
    /// wandb.watch() called
    #[prost(bool, tag = "1")]
    pub watch: bool,
    /// wandb.finish() called
    #[prost(bool, tag = "2")]
    pub finish: bool,
    /// wandb.save() called
    #[prost(bool, tag = "3")]
    pub save: bool,
    /// offline run was synced
    #[prost(bool, tag = "4")]
    pub offline: bool,
    /// run was resumed
    #[prost(bool, tag = "5")]
    pub resumed: bool,
    /// grpc-server (java integration)
    #[prost(bool, tag = "6")]
    pub grpc: bool,
    /// define_metric() called
    #[prost(bool, tag = "7")]
    pub metric: bool,
    /// Keras WandbCallback used
    #[prost(bool, tag = "8")]
    pub keras: bool,
    /// User is using sagemaker
    #[prost(bool, tag = "9")]
    pub sagemaker: bool,
    /// Artifact(incremental=True) used
    #[prost(bool, tag = "10")]
    pub artifact_incremental: bool,
    /// Using metaflow integration
    #[prost(bool, tag = "11")]
    pub metaflow: bool,
    /// Using prodigy integration
    #[prost(bool, tag = "12")]
    pub prodigy: bool,
    /// users set run name from wandb.init
    #[prost(bool, tag = "13")]
    pub set_init_name: bool,
    /// users set run id from wandb.init
    #[prost(bool, tag = "14")]
    pub set_init_id: bool,
    /// users set tags within wandb.init
    #[prost(bool, tag = "15")]
    pub set_init_tags: bool,
    /// users set run config in wandb.init
    #[prost(bool, tag = "16")]
    pub set_init_config: bool,
    /// user sets run name via wandb.run.name = ...
    #[prost(bool, tag = "17")]
    pub set_run_name: bool,
    /// user sets run name via wandb.run.tags = ...
    #[prost(bool, tag = "18")]
    pub set_run_tags: bool,
    /// users set key in run config via run.config.key
    #[prost(bool, tag = "19")]
    pub set_config_item: bool,
    /// or run.config\["key"\]
    ///
    /// run is created through wandb launch
    #[prost(bool, tag = "20")]
    pub launch: bool,
    /// wandb.profiler.torch_trace_handler() called
    #[prost(bool, tag = "21")]
    pub torch_profiler_trace: bool,
    /// Using stable_baselines3 integration
    #[prost(bool, tag = "22")]
    pub sb3: bool,
    /// Using wandb service internal process
    #[prost(bool, tag = "23")]
    pub service: bool,
    /// wandb.init() called in the same process returning previous run
    #[prost(bool, tag = "24")]
    pub init_return_run: bool,
    /// lightgbm callback used
    #[prost(bool, tag = "25")]
    pub lightgbm_wandb_callback: bool,
    /// lightgbm log summary used
    #[prost(bool, tag = "26")]
    pub lightgbm_log_summary: bool,
    /// catboost callback used
    #[prost(bool, tag = "27")]
    pub catboost_wandb_callback: bool,
    /// catboost log summary used
    #[prost(bool, tag = "28")]
    pub catboost_log_summary: bool,
    /// wandb.tensorflow.log or wandb.tensorboard.log used
    #[prost(bool, tag = "29")]
    pub tensorboard_log: bool,
    /// wandb.tensorflow.WandbHook used
    #[prost(bool, tag = "30")]
    pub estimator_hook: bool,
    /// xgboost callback used
    #[prost(bool, tag = "31")]
    pub xgboost_wandb_callback: bool,
    /// xgboost old callback used (to be depreciated)
    #[prost(bool, tag = "32")]
    pub xgboost_old_wandb_callback: bool,
    /// attach to a run in another process
    #[prost(bool, tag = "33")]
    pub attach: bool,
    /// wandb.tensorboard.patch(...)
    #[prost(bool, tag = "34")]
    pub tensorboard_patch: bool,
    /// wandb.init(sync_tensorboard=True)
    #[prost(bool, tag = "35")]
    pub tensorboard_sync: bool,
    /// wandb.integration.kfp.wandb_log
    #[prost(bool, tag = "36")]
    pub kfp_wandb_log: bool,
    /// Run might have been overwritten
    #[prost(bool, tag = "37")]
    pub maybe_run_overwrite: bool,
    /// Keras WandbMetricsLogger used
    #[prost(bool, tag = "38")]
    pub keras_metrics_logger: bool,
    /// Keras WandbModelCheckpoint used
    #[prost(bool, tag = "39")]
    pub keras_model_checkpoint: bool,
    /// Keras WandbEvalCallback used
    #[prost(bool, tag = "40")]
    pub keras_wandb_eval_callback: bool,
    /// Hit flow control threshold
    #[prost(bool, tag = "41")]
    pub flow_control_overflow: bool,
    /// Run was synced with wandb sync
    #[prost(bool, tag = "42")]
    pub sync: bool,
    /// Flow control disabled by user
    #[prost(bool, tag = "43")]
    pub flow_control_disabled: bool,
    /// Flow control customized by user
    #[prost(bool, tag = "44")]
    pub flow_control_custom: bool,
    /// Service disabled by user
    #[prost(bool, tag = "45")]
    pub service_disabled: bool,
    /// Consuming metrics from an OpenMetrics endpoint
    #[prost(bool, tag = "46")]
    pub open_metrics: bool,
    /// Ultralytics YOLOv8 integration callbacks used
    #[prost(bool, tag = "47")]
    pub ultralytics_yolov8: bool,
    /// Using Import API for MLFlow
    #[prost(bool, tag = "48")]
    pub importer_mlflow: bool,
    /// Using wandb sync for tfevent files
    #[prost(bool, tag = "49")]
    pub sync_tfevents: bool,
    /// Async file uploads enabled by user
    #[prost(bool, tag = "50")]
    pub async_uploads: bool,
    /// OpenAI autolog used
    #[prost(bool, tag = "51")]
    pub openai_autolog: bool,
    /// Langchain wandb tracer callback used
    #[prost(bool, tag = "52")]
    pub langchain_tracer: bool,
    /// Cohere autolog used
    #[prost(bool, tag = "53")]
    pub cohere_autolog: bool,
    /// HuggingFace Autologging
    #[prost(bool, tag = "54")]
    pub hf_pipeline_autolog: bool,
    /// Using wandb core internal process
    #[prost(bool, tag = "55")]
    pub core: bool,
    /// Using c wandb library
    #[prost(bool, tag = "56")]
    pub lib_c: bool,
    /// Using cpp wandb library
    #[prost(bool, tag = "57")]
    pub lib_cpp: bool,
    /// Using openai finetuning WandbLogger
    #[prost(bool, tag = "58")]
    pub openai_finetuning: bool,
    /// Using Diffusers autologger
    #[prost(bool, tag = "59")]
    pub diffusers_autolog: bool,
    /// Using Lightning Fabric logger
    #[prost(bool, tag = "60")]
    pub lightning_fabric_logger: bool,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Env {
    /// jupyter env detected
    #[prost(bool, tag = "1")]
    pub jupyter: bool,
    /// kaggle env detected
    #[prost(bool, tag = "2")]
    pub kaggle: bool,
    /// windows detected
    #[prost(bool, tag = "3")]
    pub windows: bool,
    /// apple silicon M1 gpu found
    #[prost(bool, tag = "4")]
    pub m1_gpu: bool,
    /// multiprocessing spawn
    #[prost(bool, tag = "5")]
    pub start_spawn: bool,
    /// multiprocessing fork
    #[prost(bool, tag = "6")]
    pub start_fork: bool,
    /// multiprocessing forkserver
    #[prost(bool, tag = "7")]
    pub start_forkserver: bool,
    /// thread start method
    #[prost(bool, tag = "8")]
    pub start_thread: bool,
    /// maybe user running multiprocessing
    #[prost(bool, tag = "9")]
    pub maybe_mp: bool,
    /// AWS Trainium env detected
    #[prost(bool, tag = "10")]
    pub trainium: bool,
    /// pex env detected
    #[prost(bool, tag = "11")]
    pub pex: bool,
    /// colab env detected
    #[prost(bool, tag = "12")]
    pub colab: bool,
    /// ipython env detected
    #[prost(bool, tag = "13")]
    pub ipython: bool,
    /// running in AWS Lambda
    #[prost(bool, tag = "14")]
    pub aws_lambda: bool,
    /// AMD GPU detected
    #[prost(bool, tag = "15")]
    pub amd_gpu: bool,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Labels {
    /// code identification
    #[prost(string, tag = "1")]
    pub code_string: ::prost::alloc::string::String,
    /// repo identification
    #[prost(string, tag = "2")]
    pub repo_string: ::prost::alloc::string::String,
    /// code version
    #[prost(string, tag = "3")]
    pub code_version: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Deprecated {
    /// wandb.keras.WandbCallback(data_type=...) called
    #[prost(bool, tag = "1")]
    pub keras_callback_data_type: bool,
    /// wandb.run.mode called
    #[prost(bool, tag = "2")]
    pub run_mode: bool,
    /// wandb.run.save() called without arguments
    #[prost(bool, tag = "3")]
    pub run_save_no_args: bool,
    /// wandb.run.join() called
    #[prost(bool, tag = "4")]
    pub run_join: bool,
    /// wandb.plots.* called
    #[prost(bool, tag = "5")]
    pub plots: bool,
    /// wandb.run.log(sync=...) called
    #[prost(bool, tag = "6")]
    pub run_log_sync: bool,
    /// wandb.init(config_include_keys=...) called
    #[prost(bool, tag = "7")]
    pub init_config_include_keys: bool,
    /// wandb.init(config_exclude_keys=...) called
    #[prost(bool, tag = "8")]
    pub init_config_exclude_keys: bool,
    /// wandb.keras.WandbCallback(save_model=True) called
    #[prost(bool, tag = "9")]
    pub keras_callback_save_model: bool,
    /// wandb.integration.langchain.WandbTracer called
    #[prost(bool, tag = "10")]
    pub langchain_tracer: bool,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Issues {
    /// validation warnings for settings
    #[prost(bool, tag = "1")]
    pub settings_validation_warnings: bool,
    /// unexpected settings init args
    #[prost(bool, tag = "2")]
    pub settings_unexpected_args: bool,
    /// settings preprocessing warnings
    #[prost(bool, tag = "3")]
    pub settings_preprocessing_warnings: bool,
}
///
/// Record: joined record for message passing and persistence
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Record {
    #[prost(int64, tag = "1")]
    pub num: i64,
    #[prost(message, optional, tag = "16")]
    pub control: ::core::option::Option<Control>,
    #[prost(string, tag = "19")]
    pub uuid: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
    #[prost(
        oneof = "record::RecordType",
        tags = "2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 17, 18, 20, 21, 22, 23, 24, 25, 26, 100"
    )]
    pub record_type: ::core::option::Option<record::RecordType>,
}
/// Nested message and enum types in `Record`.
pub mod record {
    #[allow(clippy::derive_partial_eq_without_eq)]
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum RecordType {
        /// Low numbers for more frequent data
        #[prost(message, tag = "2")]
        History(super::HistoryRecord),
        #[prost(message, tag = "3")]
        Summary(super::SummaryRecord),
        #[prost(message, tag = "4")]
        Output(super::OutputRecord),
        #[prost(message, tag = "5")]
        Config(super::ConfigRecord),
        #[prost(message, tag = "6")]
        Files(super::FilesRecord),
        #[prost(message, tag = "7")]
        Stats(super::StatsRecord),
        #[prost(message, tag = "8")]
        Artifact(super::ArtifactRecord),
        #[prost(message, tag = "9")]
        Tbrecord(super::TbRecord),
        #[prost(message, tag = "10")]
        Alert(super::AlertRecord),
        #[prost(message, tag = "11")]
        Telemetry(super::TelemetryRecord),
        #[prost(message, tag = "12")]
        Metric(super::MetricRecord),
        #[prost(message, tag = "13")]
        OutputRaw(super::OutputRawRecord),
        /// Higher numbers for less frequent data
        #[prost(message, tag = "17")]
        Run(super::RunRecord),
        #[prost(message, tag = "18")]
        Exit(super::RunExitRecord),
        #[prost(message, tag = "20")]
        Final(super::FinalRecord),
        #[prost(message, tag = "21")]
        Header(super::HeaderRecord),
        #[prost(message, tag = "22")]
        Footer(super::FooterRecord),
        #[prost(message, tag = "23")]
        Preempting(super::RunPreemptingRecord),
        #[prost(message, tag = "24")]
        LinkArtifact(super::LinkArtifactRecord),
        #[prost(message, tag = "25")]
        UseArtifact(super::UseArtifactRecord),
        #[prost(message, tag = "26")]
        WandbConfigParameters(super::LaunchWandbConfigParametersRecord),
        /// request field does not belong here longterm
        #[prost(message, tag = "100")]
        Request(super::Request),
    }
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Control {
    /// record is expecting a result
    #[prost(bool, tag = "1")]
    pub req_resp: bool,
    /// should not be persisted or synchronized
    #[prost(bool, tag = "2")]
    pub local: bool,
    /// used by service transport to identify correct stream
    #[prost(string, tag = "3")]
    pub relay_id: ::prost::alloc::string::String,
    /// mailbox slot
    #[prost(string, tag = "4")]
    pub mailbox_slot: ::prost::alloc::string::String,
    /// message to sender
    #[prost(bool, tag = "5")]
    pub always_send: bool,
    /// message should be passed to flow control
    #[prost(bool, tag = "6")]
    pub flow_control: bool,
    /// end of message offset of this written message
    #[prost(int64, tag = "7")]
    pub end_offset: i64,
    /// connection id
    #[prost(string, tag = "8")]
    pub connection_id: ::prost::alloc::string::String,
}
///
/// Result: all results
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Result {
    #[prost(message, optional, tag = "16")]
    pub control: ::core::option::Option<Control>,
    #[prost(string, tag = "24")]
    pub uuid: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<ResultInfo>,
    #[prost(oneof = "result::ResultType", tags = "17, 18, 20, 21, 22, 23, 100")]
    pub result_type: ::core::option::Option<result::ResultType>,
}
/// Nested message and enum types in `Result`.
pub mod result {
    #[allow(clippy::derive_partial_eq_without_eq)]
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum ResultType {
        #[prost(message, tag = "17")]
        RunResult(super::RunUpdateResult),
        #[prost(message, tag = "18")]
        ExitResult(super::RunExitResult),
        #[prost(message, tag = "20")]
        LogResult(super::HistoryResult),
        #[prost(message, tag = "21")]
        SummaryResult(super::SummaryResult),
        #[prost(message, tag = "22")]
        OutputResult(super::OutputResult),
        #[prost(message, tag = "23")]
        ConfigResult(super::ConfigResult),
        /// response field does not belong here longterm
        #[prost(message, tag = "100")]
        Response(super::Response),
    }
}
///
/// FinalRecord
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct FinalRecord {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
///
/// Version definition
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct VersionInfo {
    /// The version of the SDK backend that produced the data
    #[prost(string, tag = "1")]
    pub producer: ::prost::alloc::string::String,
    /// Minimum version of the wandb server that can read the data
    #[prost(string, tag = "2")]
    pub min_consumer: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
///
/// HeaderRecord
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct HeaderRecord {
    #[prost(message, optional, tag = "1")]
    pub version_info: ::core::option::Option<VersionInfo>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
///
/// FooterRecord
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct FooterRecord {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
///
/// RunRecord: wandb/sdk/wandb_run/Run
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RunRecord {
    #[prost(string, tag = "1")]
    pub run_id: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub entity: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub project: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "4")]
    pub config: ::core::option::Option<ConfigRecord>,
    #[prost(message, optional, tag = "5")]
    pub summary: ::core::option::Option<SummaryRecord>,
    #[prost(string, tag = "6")]
    pub run_group: ::prost::alloc::string::String,
    #[prost(string, tag = "7")]
    pub job_type: ::prost::alloc::string::String,
    #[prost(string, tag = "8")]
    pub display_name: ::prost::alloc::string::String,
    #[prost(string, tag = "9")]
    pub notes: ::prost::alloc::string::String,
    #[prost(string, repeated, tag = "10")]
    pub tags: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "11")]
    pub settings: ::core::option::Option<SettingsRecord>,
    #[prost(string, tag = "12")]
    pub sweep_id: ::prost::alloc::string::String,
    #[prost(string, tag = "13")]
    pub host: ::prost::alloc::string::String,
    #[prost(int64, tag = "14")]
    pub starting_step: i64,
    #[prost(string, tag = "16")]
    pub storage_id: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "17")]
    pub start_time: ::core::option::Option<::prost_types::Timestamp>,
    #[prost(bool, tag = "18")]
    pub resumed: bool,
    #[prost(message, optional, tag = "19")]
    pub telemetry: ::core::option::Option<TelemetryRecord>,
    #[prost(int32, tag = "20")]
    pub runtime: i32,
    #[prost(message, optional, tag = "21")]
    pub git: ::core::option::Option<GitRepoRecord>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct GitRepoRecord {
    #[prost(string, tag = "1")]
    pub remote_url: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub commit: ::prost::alloc::string::String,
}
/// Path within nested configuration object.
///
/// The path is a list of strings, each string is a key in the nested configuration
/// dict.
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ConfigFilterPath {
    #[prost(string, repeated, tag = "1")]
    pub path: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
}
/// Specifies include and exclude paths for filtering job inputs.
///
/// If this record is published to the core internal process then it will filter
/// the given paths into or out of the job inputs it builds.
///
/// If include_paths is not empty, then endpoints of the config not prefixed by
/// an include path will be ignored.
///
/// If exclude_paths is not empty, then endpoints of the config prefixed by an
/// exclude path will be ignored.
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct LaunchWandbConfigParametersRecord {
    #[prost(message, repeated, tag = "1")]
    pub include_paths: ::prost::alloc::vec::Vec<ConfigFilterPath>,
    #[prost(message, repeated, tag = "2")]
    pub exclude_paths: ::prost::alloc::vec::Vec<ConfigFilterPath>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RunUpdateResult {
    #[prost(message, optional, tag = "1")]
    pub run: ::core::option::Option<RunRecord>,
    #[prost(message, optional, tag = "2")]
    pub error: ::core::option::Option<ErrorInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ErrorInfo {
    #[prost(string, tag = "1")]
    pub message: ::prost::alloc::string::String,
    #[prost(enumeration = "error_info::ErrorCode", tag = "2")]
    pub code: i32,
}
/// Nested message and enum types in `ErrorInfo`.
pub mod error_info {
    #[derive(
        Clone,
        Copy,
        Debug,
        PartialEq,
        Eq,
        Hash,
        PartialOrd,
        Ord,
        ::prost::Enumeration
    )]
    #[repr(i32)]
    pub enum ErrorCode {
        Unknown = 0,
        Communication = 1,
        Authentication = 2,
        Usage = 3,
        Unsupported = 4,
    }
    impl ErrorCode {
        /// String value of the enum field names used in the ProtoBuf definition.
        ///
        /// The values are not transformed in any way and thus are considered stable
        /// (if the ProtoBuf definition does not change) and safe for programmatic use.
        pub fn as_str_name(&self) -> &'static str {
            match self {
                ErrorCode::Unknown => "UNKNOWN",
                ErrorCode::Communication => "COMMUNICATION",
                ErrorCode::Authentication => "AUTHENTICATION",
                ErrorCode::Usage => "USAGE",
                ErrorCode::Unsupported => "UNSUPPORTED",
            }
        }
        /// Creates an enum from field names used in the ProtoBuf definition.
        pub fn from_str_name(value: &str) -> ::core::option::Option<Self> {
            match value {
                "UNKNOWN" => Some(Self::Unknown),
                "COMMUNICATION" => Some(Self::Communication),
                "AUTHENTICATION" => Some(Self::Authentication),
                "USAGE" => Some(Self::Usage),
                "UNSUPPORTED" => Some(Self::Unsupported),
                _ => None,
            }
        }
    }
}
///
/// RunExitRecord: exit status of process
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RunExitRecord {
    #[prost(int32, tag = "1")]
    pub exit_code: i32,
    #[prost(int32, tag = "2")]
    pub runtime: i32,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RunExitResult {}
///
/// RunPreemptingRecord: run being preempted
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RunPreemptingRecord {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RunPreemptingResult {}
///
/// SettingsRecord: wandb/sdk/wandb_settings/Settings
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SettingsRecord {
    #[prost(message, repeated, tag = "1")]
    pub item: ::prost::alloc::vec::Vec<SettingsItem>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SettingsItem {
    #[prost(string, tag = "1")]
    pub key: ::prost::alloc::string::String,
    #[prost(string, tag = "16")]
    pub value_json: ::prost::alloc::string::String,
}
///
/// HistoryRecord: wandb/sdk/wandb_history/History
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct HistoryStep {
    #[prost(int64, tag = "1")]
    pub num: i64,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct HistoryRecord {
    #[prost(message, repeated, tag = "1")]
    pub item: ::prost::alloc::vec::Vec<HistoryItem>,
    #[prost(message, optional, tag = "2")]
    pub step: ::core::option::Option<HistoryStep>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct HistoryItem {
    #[prost(string, tag = "1")]
    pub key: ::prost::alloc::string::String,
    #[prost(string, repeated, tag = "2")]
    pub nested_key: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
    #[prost(string, tag = "16")]
    pub value_json: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct HistoryResult {}
///
/// OutputRecord: console output
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct OutputRecord {
    #[prost(enumeration = "output_record::OutputType", tag = "1")]
    pub output_type: i32,
    #[prost(message, optional, tag = "2")]
    pub timestamp: ::core::option::Option<::prost_types::Timestamp>,
    #[prost(string, tag = "3")]
    pub line: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
/// Nested message and enum types in `OutputRecord`.
pub mod output_record {
    #[derive(
        Clone,
        Copy,
        Debug,
        PartialEq,
        Eq,
        Hash,
        PartialOrd,
        Ord,
        ::prost::Enumeration
    )]
    #[repr(i32)]
    pub enum OutputType {
        Stderr = 0,
        Stdout = 1,
    }
    impl OutputType {
        /// String value of the enum field names used in the ProtoBuf definition.
        ///
        /// The values are not transformed in any way and thus are considered stable
        /// (if the ProtoBuf definition does not change) and safe for programmatic use.
        pub fn as_str_name(&self) -> &'static str {
            match self {
                OutputType::Stderr => "STDERR",
                OutputType::Stdout => "STDOUT",
            }
        }
        /// Creates an enum from field names used in the ProtoBuf definition.
        pub fn from_str_name(value: &str) -> ::core::option::Option<Self> {
            match value {
                "STDERR" => Some(Self::Stderr),
                "STDOUT" => Some(Self::Stdout),
                _ => None,
            }
        }
    }
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct OutputResult {}
///
/// OutputRawRecord: raw console output
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct OutputRawRecord {
    #[prost(enumeration = "output_raw_record::OutputType", tag = "1")]
    pub output_type: i32,
    #[prost(message, optional, tag = "2")]
    pub timestamp: ::core::option::Option<::prost_types::Timestamp>,
    #[prost(string, tag = "3")]
    pub line: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
/// Nested message and enum types in `OutputRawRecord`.
pub mod output_raw_record {
    #[derive(
        Clone,
        Copy,
        Debug,
        PartialEq,
        Eq,
        Hash,
        PartialOrd,
        Ord,
        ::prost::Enumeration
    )]
    #[repr(i32)]
    pub enum OutputType {
        Stderr = 0,
        Stdout = 1,
    }
    impl OutputType {
        /// String value of the enum field names used in the ProtoBuf definition.
        ///
        /// The values are not transformed in any way and thus are considered stable
        /// (if the ProtoBuf definition does not change) and safe for programmatic use.
        pub fn as_str_name(&self) -> &'static str {
            match self {
                OutputType::Stderr => "STDERR",
                OutputType::Stdout => "STDOUT",
            }
        }
        /// Creates an enum from field names used in the ProtoBuf definition.
        pub fn from_str_name(value: &str) -> ::core::option::Option<Self> {
            match value {
                "STDERR" => Some(Self::Stderr),
                "STDOUT" => Some(Self::Stdout),
                _ => None,
            }
        }
    }
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct OutputRawResult {}
///
/// MetricRecord: wandb/sdk/wandb_metric/Metric
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct MetricRecord {
    /// only name or globname is set
    #[prost(string, tag = "1")]
    pub name: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub glob_name: ::prost::alloc::string::String,
    /// step metric index can be used instead of step_metric when
    /// MetricRecord is encoded in a list of MetricRecords
    #[prost(string, tag = "4")]
    pub step_metric: ::prost::alloc::string::String,
    /// one-based array index
    #[prost(int32, tag = "5")]
    pub step_metric_index: i32,
    #[prost(message, optional, tag = "6")]
    pub options: ::core::option::Option<MetricOptions>,
    #[prost(message, optional, tag = "7")]
    pub summary: ::core::option::Option<MetricSummary>,
    #[prost(enumeration = "metric_record::MetricGoal", tag = "8")]
    pub goal: i32,
    #[prost(message, optional, tag = "9")]
    pub control: ::core::option::Option<MetricControl>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
/// Nested message and enum types in `MetricRecord`.
pub mod metric_record {
    #[derive(
        Clone,
        Copy,
        Debug,
        PartialEq,
        Eq,
        Hash,
        PartialOrd,
        Ord,
        ::prost::Enumeration
    )]
    #[repr(i32)]
    pub enum MetricGoal {
        GoalUnset = 0,
        GoalMinimize = 1,
        GoalMaximize = 2,
    }
    impl MetricGoal {
        /// String value of the enum field names used in the ProtoBuf definition.
        ///
        /// The values are not transformed in any way and thus are considered stable
        /// (if the ProtoBuf definition does not change) and safe for programmatic use.
        pub fn as_str_name(&self) -> &'static str {
            match self {
                MetricGoal::GoalUnset => "GOAL_UNSET",
                MetricGoal::GoalMinimize => "GOAL_MINIMIZE",
                MetricGoal::GoalMaximize => "GOAL_MAXIMIZE",
            }
        }
        /// Creates an enum from field names used in the ProtoBuf definition.
        pub fn from_str_name(value: &str) -> ::core::option::Option<Self> {
            match value {
                "GOAL_UNSET" => Some(Self::GoalUnset),
                "GOAL_MINIMIZE" => Some(Self::GoalMinimize),
                "GOAL_MAXIMIZE" => Some(Self::GoalMaximize),
                _ => None,
            }
        }
    }
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct MetricResult {}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct MetricOptions {
    #[prost(bool, tag = "1")]
    pub step_sync: bool,
    #[prost(bool, tag = "2")]
    pub hidden: bool,
    /// metric explicitly defined (not from glob match or step metric)
    #[prost(bool, tag = "3")]
    pub defined: bool,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct MetricControl {
    #[prost(bool, tag = "1")]
    pub overwrite: bool,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct MetricSummary {
    #[prost(bool, tag = "1")]
    pub min: bool,
    #[prost(bool, tag = "2")]
    pub max: bool,
    #[prost(bool, tag = "3")]
    pub mean: bool,
    #[prost(bool, tag = "4")]
    pub best: bool,
    #[prost(bool, tag = "5")]
    pub last: bool,
    #[prost(bool, tag = "6")]
    pub none: bool,
    #[prost(bool, tag = "7")]
    pub copy: bool,
}
///
/// ConfigRecord: wandb/sdk/wandb_config/Config
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ConfigRecord {
    #[prost(message, repeated, tag = "1")]
    pub update: ::prost::alloc::vec::Vec<ConfigItem>,
    #[prost(message, repeated, tag = "2")]
    pub remove: ::prost::alloc::vec::Vec<ConfigItem>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ConfigItem {
    #[prost(string, tag = "1")]
    pub key: ::prost::alloc::string::String,
    #[prost(string, repeated, tag = "2")]
    pub nested_key: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
    #[prost(string, tag = "16")]
    pub value_json: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ConfigResult {}
///
/// SummaryRecord: wandb/sdk/wandb_summary/Summary
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SummaryRecord {
    #[prost(message, repeated, tag = "1")]
    pub update: ::prost::alloc::vec::Vec<SummaryItem>,
    #[prost(message, repeated, tag = "2")]
    pub remove: ::prost::alloc::vec::Vec<SummaryItem>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SummaryItem {
    #[prost(string, tag = "1")]
    pub key: ::prost::alloc::string::String,
    #[prost(string, repeated, tag = "2")]
    pub nested_key: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
    #[prost(string, tag = "16")]
    pub value_json: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SummaryResult {}
///
/// FilesRecord: files added to run
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct FilesRecord {
    #[prost(message, repeated, tag = "1")]
    pub files: ::prost::alloc::vec::Vec<FilesItem>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct FilesItem {
    #[prost(string, tag = "1")]
    pub path: ::prost::alloc::string::String,
    #[prost(enumeration = "files_item::PolicyType", tag = "2")]
    pub policy: i32,
    #[prost(enumeration = "files_item::FileType", tag = "3")]
    pub r#type: i32,
    #[prost(string, tag = "16")]
    pub external_path: ::prost::alloc::string::String,
}
/// Nested message and enum types in `FilesItem`.
pub mod files_item {
    #[derive(
        Clone,
        Copy,
        Debug,
        PartialEq,
        Eq,
        Hash,
        PartialOrd,
        Ord,
        ::prost::Enumeration
    )]
    #[repr(i32)]
    pub enum PolicyType {
        Now = 0,
        End = 1,
        Live = 2,
    }
    impl PolicyType {
        /// String value of the enum field names used in the ProtoBuf definition.
        ///
        /// The values are not transformed in any way and thus are considered stable
        /// (if the ProtoBuf definition does not change) and safe for programmatic use.
        pub fn as_str_name(&self) -> &'static str {
            match self {
                PolicyType::Now => "NOW",
                PolicyType::End => "END",
                PolicyType::Live => "LIVE",
            }
        }
        /// Creates an enum from field names used in the ProtoBuf definition.
        pub fn from_str_name(value: &str) -> ::core::option::Option<Self> {
            match value {
                "NOW" => Some(Self::Now),
                "END" => Some(Self::End),
                "LIVE" => Some(Self::Live),
                _ => None,
            }
        }
    }
    #[derive(
        Clone,
        Copy,
        Debug,
        PartialEq,
        Eq,
        Hash,
        PartialOrd,
        Ord,
        ::prost::Enumeration
    )]
    #[repr(i32)]
    pub enum FileType {
        Other = 0,
        Wandb = 1,
        Media = 2,
        Artifact = 3,
    }
    impl FileType {
        /// String value of the enum field names used in the ProtoBuf definition.
        ///
        /// The values are not transformed in any way and thus are considered stable
        /// (if the ProtoBuf definition does not change) and safe for programmatic use.
        pub fn as_str_name(&self) -> &'static str {
            match self {
                FileType::Other => "OTHER",
                FileType::Wandb => "WANDB",
                FileType::Media => "MEDIA",
                FileType::Artifact => "ARTIFACT",
            }
        }
        /// Creates an enum from field names used in the ProtoBuf definition.
        pub fn from_str_name(value: &str) -> ::core::option::Option<Self> {
            match value {
                "OTHER" => Some(Self::Other),
                "WANDB" => Some(Self::Wandb),
                "MEDIA" => Some(Self::Media),
                "ARTIFACT" => Some(Self::Artifact),
                _ => None,
            }
        }
    }
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct FilesResult {}
///
/// StatsRecord: system metrics
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct StatsRecord {
    #[prost(enumeration = "stats_record::StatsType", tag = "1")]
    pub stats_type: i32,
    #[prost(message, optional, tag = "2")]
    pub timestamp: ::core::option::Option<::prost_types::Timestamp>,
    #[prost(message, repeated, tag = "3")]
    pub item: ::prost::alloc::vec::Vec<StatsItem>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
/// Nested message and enum types in `StatsRecord`.
pub mod stats_record {
    #[derive(
        Clone,
        Copy,
        Debug,
        PartialEq,
        Eq,
        Hash,
        PartialOrd,
        Ord,
        ::prost::Enumeration
    )]
    #[repr(i32)]
    pub enum StatsType {
        System = 0,
    }
    impl StatsType {
        /// String value of the enum field names used in the ProtoBuf definition.
        ///
        /// The values are not transformed in any way and thus are considered stable
        /// (if the ProtoBuf definition does not change) and safe for programmatic use.
        pub fn as_str_name(&self) -> &'static str {
            match self {
                StatsType::System => "SYSTEM",
            }
        }
        /// Creates an enum from field names used in the ProtoBuf definition.
        pub fn from_str_name(value: &str) -> ::core::option::Option<Self> {
            match value {
                "SYSTEM" => Some(Self::System),
                _ => None,
            }
        }
    }
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct StatsItem {
    #[prost(string, tag = "1")]
    pub key: ::prost::alloc::string::String,
    #[prost(string, tag = "16")]
    pub value_json: ::prost::alloc::string::String,
}
///
/// ArtifactRecord: track artifacts
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ArtifactRecord {
    #[prost(string, tag = "1")]
    pub run_id: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub project: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub entity: ::prost::alloc::string::String,
    #[prost(string, tag = "4")]
    pub r#type: ::prost::alloc::string::String,
    #[prost(string, tag = "5")]
    pub name: ::prost::alloc::string::String,
    #[prost(string, tag = "6")]
    pub digest: ::prost::alloc::string::String,
    #[prost(string, tag = "7")]
    pub description: ::prost::alloc::string::String,
    #[prost(string, tag = "8")]
    pub metadata: ::prost::alloc::string::String,
    #[prost(bool, tag = "9")]
    pub user_created: bool,
    #[prost(bool, tag = "10")]
    pub use_after_commit: bool,
    #[prost(string, repeated, tag = "11")]
    pub aliases: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "12")]
    pub manifest: ::core::option::Option<ArtifactManifest>,
    #[prost(string, tag = "13")]
    pub distributed_id: ::prost::alloc::string::String,
    #[prost(bool, tag = "14")]
    pub finalize: bool,
    #[prost(string, tag = "15")]
    pub client_id: ::prost::alloc::string::String,
    #[prost(string, tag = "16")]
    pub sequence_client_id: ::prost::alloc::string::String,
    #[prost(string, tag = "17")]
    pub base_id: ::prost::alloc::string::String,
    #[prost(int64, tag = "18")]
    pub ttl_duration_seconds: i64,
    #[prost(bool, tag = "100")]
    pub incremental_beta1: bool,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ArtifactManifest {
    #[prost(int32, tag = "1")]
    pub version: i32,
    #[prost(string, tag = "2")]
    pub storage_policy: ::prost::alloc::string::String,
    #[prost(message, repeated, tag = "3")]
    pub storage_policy_config: ::prost::alloc::vec::Vec<StoragePolicyConfigItem>,
    #[prost(message, repeated, tag = "4")]
    pub contents: ::prost::alloc::vec::Vec<ArtifactManifestEntry>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ArtifactManifestEntry {
    #[prost(string, tag = "1")]
    pub path: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub digest: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub r#ref: ::prost::alloc::string::String,
    #[prost(int64, tag = "4")]
    pub size: i64,
    #[prost(string, tag = "5")]
    pub mimetype: ::prost::alloc::string::String,
    #[prost(string, tag = "6")]
    pub local_path: ::prost::alloc::string::String,
    #[prost(string, tag = "7")]
    pub birth_artifact_id: ::prost::alloc::string::String,
    #[prost(message, repeated, tag = "16")]
    pub extra: ::prost::alloc::vec::Vec<ExtraItem>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ExtraItem {
    #[prost(string, tag = "1")]
    pub key: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub value_json: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct StoragePolicyConfigItem {
    #[prost(string, tag = "1")]
    pub key: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub value_json: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ArtifactResult {}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct LinkArtifactResult {}
///
/// LinkArtifactRecord: link artifact to portfolio
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct LinkArtifactRecord {
    #[prost(string, tag = "1")]
    pub client_id: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub server_id: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub portfolio_name: ::prost::alloc::string::String,
    #[prost(string, tag = "4")]
    pub portfolio_entity: ::prost::alloc::string::String,
    #[prost(string, tag = "5")]
    pub portfolio_project: ::prost::alloc::string::String,
    #[prost(string, repeated, tag = "6")]
    pub portfolio_aliases: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
///
/// TBRecord: store tb locations
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TbRecord {
    #[prost(string, tag = "1")]
    pub log_dir: ::prost::alloc::string::String,
    #[prost(bool, tag = "2")]
    pub save: bool,
    #[prost(string, tag = "3")]
    pub root_dir: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TbResult {}
///
/// AlertRecord: store alert notifications
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct AlertRecord {
    #[prost(string, tag = "1")]
    pub title: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub text: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub level: ::prost::alloc::string::String,
    #[prost(int64, tag = "4")]
    pub wait_duration: i64,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct AlertResult {}
///
/// Request: all non persistent messages
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Request {
    #[prost(
        oneof = "request::RequestType",
        tags = "1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 17, 20, 21, 22, 23, 24, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 1000"
    )]
    pub request_type: ::core::option::Option<request::RequestType>,
}
/// Nested message and enum types in `Request`.
pub mod request {
    #[allow(clippy::derive_partial_eq_without_eq)]
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum RequestType {
        #[prost(message, tag = "1")]
        StopStatus(super::StopStatusRequest),
        #[prost(message, tag = "2")]
        NetworkStatus(super::NetworkStatusRequest),
        #[prost(message, tag = "3")]
        Defer(super::DeferRequest),
        #[prost(message, tag = "4")]
        GetSummary(super::GetSummaryRequest),
        #[prost(message, tag = "5")]
        Login(super::LoginRequest),
        #[prost(message, tag = "6")]
        Pause(super::PauseRequest),
        #[prost(message, tag = "7")]
        Resume(super::ResumeRequest),
        #[prost(message, tag = "8")]
        PollExit(super::PollExitRequest),
        #[prost(message, tag = "9")]
        SampledHistory(super::SampledHistoryRequest),
        #[prost(message, tag = "10")]
        PartialHistory(super::PartialHistoryRequest),
        #[prost(message, tag = "11")]
        RunStart(super::RunStartRequest),
        #[prost(message, tag = "12")]
        CheckVersion(super::CheckVersionRequest),
        #[prost(message, tag = "13")]
        LogArtifact(super::LogArtifactRequest),
        #[prost(message, tag = "14")]
        DownloadArtifact(super::DownloadArtifactRequest),
        #[prost(message, tag = "17")]
        Keepalive(super::KeepaliveRequest),
        #[prost(message, tag = "20")]
        RunStatus(super::RunStatusRequest),
        #[prost(message, tag = "21")]
        Cancel(super::CancelRequest),
        #[prost(message, tag = "22")]
        Metadata(super::MetadataRequest),
        #[prost(message, tag = "23")]
        InternalMessages(super::InternalMessagesRequest),
        #[prost(message, tag = "24")]
        PythonPackages(super::PythonPackagesRequest),
        #[prost(message, tag = "64")]
        Shutdown(super::ShutdownRequest),
        #[prost(message, tag = "65")]
        Attach(super::AttachRequest),
        #[prost(message, tag = "66")]
        Status(super::StatusRequest),
        #[prost(message, tag = "67")]
        ServerInfo(super::ServerInfoRequest),
        #[prost(message, tag = "68")]
        SenderMark(super::SenderMarkRequest),
        #[prost(message, tag = "69")]
        SenderRead(super::SenderReadRequest),
        #[prost(message, tag = "70")]
        StatusReport(super::StatusReportRequest),
        #[prost(message, tag = "71")]
        SummaryRecord(super::SummaryRecordRequest),
        #[prost(message, tag = "72")]
        TelemetryRecord(super::TelemetryRecordRequest),
        #[prost(message, tag = "73")]
        JobInfo(super::JobInfoRequest),
        #[prost(message, tag = "74")]
        GetSystemMetrics(super::GetSystemMetricsRequest),
        #[prost(message, tag = "75")]
        FileTransferInfo(super::FileTransferInfoRequest),
        #[prost(message, tag = "76")]
        Sync(super::SyncRequest),
        #[prost(message, tag = "1000")]
        TestInject(super::TestInjectRequest),
    }
}
///
/// Response: all non persistent responses to Requests
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Response {
    #[prost(
        oneof = "response::ResponseType",
        tags = "18, 19, 20, 24, 25, 26, 27, 28, 29, 30, 31, 35, 36, 37, 64, 65, 66, 67, 68, 69, 70, 1000"
    )]
    pub response_type: ::core::option::Option<response::ResponseType>,
}
/// Nested message and enum types in `Response`.
pub mod response {
    #[allow(clippy::derive_partial_eq_without_eq)]
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum ResponseType {
        #[prost(message, tag = "18")]
        KeepaliveResponse(super::KeepaliveResponse),
        #[prost(message, tag = "19")]
        StopStatusResponse(super::StopStatusResponse),
        #[prost(message, tag = "20")]
        NetworkStatusResponse(super::NetworkStatusResponse),
        #[prost(message, tag = "24")]
        LoginResponse(super::LoginResponse),
        #[prost(message, tag = "25")]
        GetSummaryResponse(super::GetSummaryResponse),
        #[prost(message, tag = "26")]
        PollExitResponse(super::PollExitResponse),
        #[prost(message, tag = "27")]
        SampledHistoryResponse(super::SampledHistoryResponse),
        #[prost(message, tag = "28")]
        RunStartResponse(super::RunStartResponse),
        #[prost(message, tag = "29")]
        CheckVersionResponse(super::CheckVersionResponse),
        #[prost(message, tag = "30")]
        LogArtifactResponse(super::LogArtifactResponse),
        #[prost(message, tag = "31")]
        DownloadArtifactResponse(super::DownloadArtifactResponse),
        #[prost(message, tag = "35")]
        RunStatusResponse(super::RunStatusResponse),
        #[prost(message, tag = "36")]
        CancelResponse(super::CancelResponse),
        #[prost(message, tag = "37")]
        InternalMessagesResponse(super::InternalMessagesResponse),
        #[prost(message, tag = "64")]
        ShutdownResponse(super::ShutdownResponse),
        #[prost(message, tag = "65")]
        AttachResponse(super::AttachResponse),
        #[prost(message, tag = "66")]
        StatusResponse(super::StatusResponse),
        #[prost(message, tag = "67")]
        ServerInfoResponse(super::ServerInfoResponse),
        #[prost(message, tag = "68")]
        JobInfoResponse(super::JobInfoResponse),
        #[prost(message, tag = "69")]
        GetSystemMetricsResponse(super::GetSystemMetricsResponse),
        #[prost(message, tag = "70")]
        SyncResponse(super::SyncResponse),
        #[prost(message, tag = "1000")]
        TestInjectResponse(super::TestInjectResponse),
    }
}
///
/// DeferRequest: internal message to defer work
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct DeferRequest {
    /// Internal message, no _info field needed
    #[prost(enumeration = "defer_request::DeferState", tag = "1")]
    pub state: i32,
}
/// Nested message and enum types in `DeferRequest`.
pub mod defer_request {
    #[derive(
        Clone,
        Copy,
        Debug,
        PartialEq,
        Eq,
        Hash,
        PartialOrd,
        Ord,
        ::prost::Enumeration
    )]
    #[repr(i32)]
    pub enum DeferState {
        Begin = 0,
        FlushRun = 1,
        FlushStats = 2,
        FlushPartialHistory = 3,
        FlushTb = 4,
        FlushSum = 5,
        FlushDebouncer = 6,
        FlushOutput = 7,
        FlushJob = 8,
        FlushDir = 9,
        FlushFp = 10,
        JoinFp = 11,
        FlushFs = 12,
        FlushFinal = 13,
        End = 14,
    }
    impl DeferState {
        /// String value of the enum field names used in the ProtoBuf definition.
        ///
        /// The values are not transformed in any way and thus are considered stable
        /// (if the ProtoBuf definition does not change) and safe for programmatic use.
        pub fn as_str_name(&self) -> &'static str {
            match self {
                DeferState::Begin => "BEGIN",
                DeferState::FlushRun => "FLUSH_RUN",
                DeferState::FlushStats => "FLUSH_STATS",
                DeferState::FlushPartialHistory => "FLUSH_PARTIAL_HISTORY",
                DeferState::FlushTb => "FLUSH_TB",
                DeferState::FlushSum => "FLUSH_SUM",
                DeferState::FlushDebouncer => "FLUSH_DEBOUNCER",
                DeferState::FlushOutput => "FLUSH_OUTPUT",
                DeferState::FlushJob => "FLUSH_JOB",
                DeferState::FlushDir => "FLUSH_DIR",
                DeferState::FlushFp => "FLUSH_FP",
                DeferState::JoinFp => "JOIN_FP",
                DeferState::FlushFs => "FLUSH_FS",
                DeferState::FlushFinal => "FLUSH_FINAL",
                DeferState::End => "END",
            }
        }
        /// Creates an enum from field names used in the ProtoBuf definition.
        pub fn from_str_name(value: &str) -> ::core::option::Option<Self> {
            match value {
                "BEGIN" => Some(Self::Begin),
                "FLUSH_RUN" => Some(Self::FlushRun),
                "FLUSH_STATS" => Some(Self::FlushStats),
                "FLUSH_PARTIAL_HISTORY" => Some(Self::FlushPartialHistory),
                "FLUSH_TB" => Some(Self::FlushTb),
                "FLUSH_SUM" => Some(Self::FlushSum),
                "FLUSH_DEBOUNCER" => Some(Self::FlushDebouncer),
                "FLUSH_OUTPUT" => Some(Self::FlushOutput),
                "FLUSH_JOB" => Some(Self::FlushJob),
                "FLUSH_DIR" => Some(Self::FlushDir),
                "FLUSH_FP" => Some(Self::FlushFp),
                "JOIN_FP" => Some(Self::JoinFp),
                "FLUSH_FS" => Some(Self::FlushFs),
                "FLUSH_FINAL" => Some(Self::FlushFinal),
                "END" => Some(Self::End),
                _ => None,
            }
        }
    }
}
///
/// PauseRequest: internal message to pause the heartbeat
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PauseRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PauseResponse {}
///
/// ResumeRequest: internal message to resume the heartbeat
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ResumeRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ResumeResponse {}
///
/// LoginRequest: wandb/sdk/wandb_login
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct LoginRequest {
    #[prost(string, tag = "1")]
    pub api_key: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct LoginResponse {
    #[prost(string, tag = "1")]
    pub active_entity: ::prost::alloc::string::String,
}
///
/// GetSummaryRequest: request consolidated summary
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct GetSummaryRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct GetSummaryResponse {
    #[prost(message, repeated, tag = "1")]
    pub item: ::prost::alloc::vec::Vec<SummaryItem>,
}
///
/// GetSystemMetrics: request system metrics
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct GetSystemMetricsRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SystemMetricSample {
    #[prost(message, optional, tag = "1")]
    pub timestamp: ::core::option::Option<::prost_types::Timestamp>,
    #[prost(float, tag = "2")]
    pub value: f32,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SystemMetricsBuffer {
    #[prost(message, repeated, tag = "1")]
    pub record: ::prost::alloc::vec::Vec<SystemMetricSample>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct GetSystemMetricsResponse {
    #[prost(map = "string, message", tag = "1")]
    pub system_metrics: ::std::collections::HashMap<
        ::prost::alloc::string::String,
        SystemMetricsBuffer,
    >,
}
///
/// StatusRequest:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct StatusRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct StatusResponse {
    #[prost(bool, tag = "1")]
    pub run_should_stop: bool,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct StopStatusRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct StopStatusResponse {
    #[prost(bool, tag = "1")]
    pub run_should_stop: bool,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct NetworkStatusRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct NetworkStatusResponse {
    #[prost(message, repeated, tag = "1")]
    pub network_responses: ::prost::alloc::vec::Vec<HttpResponse>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct HttpResponse {
    #[prost(int32, tag = "1")]
    pub http_status_code: i32,
    #[prost(string, tag = "2")]
    pub http_response_text: ::prost::alloc::string::String,
}
///
/// InternalMessagesRequest:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct InternalMessagesRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct InternalMessagesResponse {
    #[prost(message, optional, tag = "1")]
    pub messages: ::core::option::Option<InternalMessages>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct InternalMessages {
    #[prost(string, repeated, tag = "1")]
    pub warning: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
}
///
/// PollExitRequest:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PollExitRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PollExitResponse {
    #[prost(bool, tag = "1")]
    pub done: bool,
    #[prost(message, optional, tag = "2")]
    pub exit_result: ::core::option::Option<RunExitResult>,
    #[prost(message, optional, tag = "3")]
    pub pusher_stats: ::core::option::Option<FilePusherStats>,
    #[prost(message, optional, tag = "4")]
    pub file_counts: ::core::option::Option<FileCounts>,
}
///
/// Sender requests
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SyncOverwrite {
    #[prost(string, tag = "1")]
    pub run_id: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub entity: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub project: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SyncSkip {
    #[prost(bool, tag = "1")]
    pub output_raw: bool,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SenderMarkRequest {}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SyncRequest {
    #[prost(int64, tag = "1")]
    pub start_offset: i64,
    #[prost(int64, tag = "2")]
    pub final_offset: i64,
    #[prost(message, optional, tag = "3")]
    pub overwrite: ::core::option::Option<SyncOverwrite>,
    #[prost(message, optional, tag = "4")]
    pub skip: ::core::option::Option<SyncSkip>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SyncResponse {
    #[prost(string, tag = "1")]
    pub url: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "2")]
    pub error: ::core::option::Option<ErrorInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SenderReadRequest {
    #[prost(int64, tag = "1")]
    pub start_offset: i64,
    /// TODO: implement cancel for paused ops
    /// repeated string cancel_list = 3;
    #[prost(int64, tag = "2")]
    pub final_offset: i64,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct StatusReportRequest {
    #[prost(int64, tag = "1")]
    pub record_num: i64,
    #[prost(int64, tag = "2")]
    pub sent_offset: i64,
    #[prost(message, optional, tag = "3")]
    pub sync_time: ::core::option::Option<::prost_types::Timestamp>,
}
///
/// Requests wrapping Records
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SummaryRecordRequest {
    #[prost(message, optional, tag = "1")]
    pub summary: ::core::option::Option<SummaryRecord>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TelemetryRecordRequest {
    #[prost(message, optional, tag = "1")]
    pub telemetry: ::core::option::Option<TelemetryRecord>,
}
///
/// ServerInfoRequest:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInfoRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInfoResponse {
    #[prost(message, optional, tag = "1")]
    pub local_info: ::core::option::Option<LocalInfo>,
    #[prost(message, optional, tag = "2")]
    pub server_messages: ::core::option::Option<ServerMessages>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerMessages {
    #[prost(message, repeated, tag = "1")]
    pub item: ::prost::alloc::vec::Vec<ServerMessage>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerMessage {
    #[prost(string, tag = "1")]
    pub plain_text: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub utf_text: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub html_text: ::prost::alloc::string::String,
    #[prost(string, tag = "4")]
    pub r#type: ::prost::alloc::string::String,
    #[prost(int32, tag = "5")]
    pub level: i32,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct FileCounts {
    #[prost(int32, tag = "1")]
    pub wandb_count: i32,
    #[prost(int32, tag = "2")]
    pub media_count: i32,
    #[prost(int32, tag = "3")]
    pub artifact_count: i32,
    #[prost(int32, tag = "4")]
    pub other_count: i32,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct FilePusherStats {
    #[prost(int64, tag = "1")]
    pub uploaded_bytes: i64,
    #[prost(int64, tag = "2")]
    pub total_bytes: i64,
    #[prost(int64, tag = "3")]
    pub deduped_bytes: i64,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct FilesUploaded {
    #[prost(string, repeated, tag = "1")]
    pub files: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct FileTransferInfoRequest {
    #[prost(enumeration = "file_transfer_info_request::TransferType", tag = "1")]
    pub r#type: i32,
    #[prost(string, tag = "2")]
    pub path: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub url: ::prost::alloc::string::String,
    #[prost(int64, tag = "4")]
    pub size: i64,
    #[prost(int64, tag = "5")]
    pub processed: i64,
    #[prost(message, optional, tag = "6")]
    pub file_counts: ::core::option::Option<FileCounts>,
}
/// Nested message and enum types in `FileTransferInfoRequest`.
pub mod file_transfer_info_request {
    #[derive(
        Clone,
        Copy,
        Debug,
        PartialEq,
        Eq,
        Hash,
        PartialOrd,
        Ord,
        ::prost::Enumeration
    )]
    #[repr(i32)]
    pub enum TransferType {
        Upload = 0,
        Download = 1,
    }
    impl TransferType {
        /// String value of the enum field names used in the ProtoBuf definition.
        ///
        /// The values are not transformed in any way and thus are considered stable
        /// (if the ProtoBuf definition does not change) and safe for programmatic use.
        pub fn as_str_name(&self) -> &'static str {
            match self {
                TransferType::Upload => "Upload",
                TransferType::Download => "Download",
            }
        }
        /// Creates an enum from field names used in the ProtoBuf definition.
        pub fn from_str_name(value: &str) -> ::core::option::Option<Self> {
            match value {
                "Upload" => Some(Self::Upload),
                "Download" => Some(Self::Download),
                _ => None,
            }
        }
    }
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct LocalInfo {
    #[prost(string, tag = "1")]
    pub version: ::prost::alloc::string::String,
    #[prost(bool, tag = "2")]
    pub out_of_date: bool,
}
///
/// ShutdownRequest:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ShutdownRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ShutdownResponse {}
///
/// AttachRequest:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct AttachRequest {
    #[prost(string, tag = "20")]
    pub attach_id: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct AttachResponse {
    #[prost(message, optional, tag = "1")]
    pub run: ::core::option::Option<RunRecord>,
    #[prost(message, optional, tag = "2")]
    pub error: ::core::option::Option<ErrorInfo>,
}
///
/// TestInjectRequest:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TestInjectRequest {
    #[prost(bool, tag = "1")]
    pub handler_exc: bool,
    #[prost(bool, tag = "2")]
    pub handler_exit: bool,
    #[prost(bool, tag = "3")]
    pub handler_abort: bool,
    #[prost(bool, tag = "4")]
    pub sender_exc: bool,
    #[prost(bool, tag = "5")]
    pub sender_exit: bool,
    #[prost(bool, tag = "6")]
    pub sender_abort: bool,
    #[prost(bool, tag = "7")]
    pub req_exc: bool,
    #[prost(bool, tag = "8")]
    pub req_exit: bool,
    #[prost(bool, tag = "9")]
    pub req_abort: bool,
    #[prost(bool, tag = "10")]
    pub resp_exc: bool,
    #[prost(bool, tag = "11")]
    pub resp_exit: bool,
    #[prost(bool, tag = "12")]
    pub resp_abort: bool,
    #[prost(bool, tag = "13")]
    pub msg_drop: bool,
    #[prost(bool, tag = "14")]
    pub msg_hang: bool,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TestInjectResponse {}
///
/// PartialHistoryRequest:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct HistoryAction {
    #[prost(bool, tag = "1")]
    pub flush: bool,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PartialHistoryRequest {
    #[prost(message, repeated, tag = "1")]
    pub item: ::prost::alloc::vec::Vec<HistoryItem>,
    #[prost(message, optional, tag = "2")]
    pub step: ::core::option::Option<HistoryStep>,
    #[prost(message, optional, tag = "3")]
    pub action: ::core::option::Option<HistoryAction>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PartialHistoryResponse {}
///
/// SampledHistoryRequest:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SampledHistoryRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SampledHistoryItem {
    #[prost(string, tag = "1")]
    pub key: ::prost::alloc::string::String,
    #[prost(string, repeated, tag = "2")]
    pub nested_key: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
    #[prost(float, repeated, tag = "3")]
    pub values_float: ::prost::alloc::vec::Vec<f32>,
    #[prost(int64, repeated, tag = "4")]
    pub values_int: ::prost::alloc::vec::Vec<i64>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct SampledHistoryResponse {
    #[prost(message, repeated, tag = "1")]
    pub item: ::prost::alloc::vec::Vec<SampledHistoryItem>,
}
///
/// RunStatusRequest:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RunStatusRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RunStatusResponse {
    #[prost(int64, tag = "1")]
    pub sync_items_total: i64,
    #[prost(int64, tag = "2")]
    pub sync_items_pending: i64,
    /// TODO(flowcontrol): can we give the user an indication of step position
    /// int64 sync_history_step = 3;
    /// google.protobuf.Timestamp sync_history_time = 4;
    #[prost(message, optional, tag = "3")]
    pub sync_time: ::core::option::Option<::prost_types::Timestamp>,
}
///
/// RunStartRequest: start the run
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RunStartRequest {
    #[prost(message, optional, tag = "1")]
    pub run: ::core::option::Option<RunRecord>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct RunStartResponse {}
///
/// CheckVersion:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct CheckVersionRequest {
    #[prost(string, tag = "1")]
    pub current_version: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct CheckVersionResponse {
    #[prost(string, tag = "1")]
    pub upgrade_message: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub yank_message: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub delete_message: ::prost::alloc::string::String,
}
///
/// JobInfo:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct JobInfoRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct JobInfoResponse {
    #[prost(string, tag = "1")]
    pub sequence_id: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub version: ::prost::alloc::string::String,
}
///
/// LogArtifact:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct LogArtifactRequest {
    #[prost(message, optional, tag = "1")]
    pub artifact: ::core::option::Option<ArtifactRecord>,
    #[prost(int64, tag = "2")]
    pub history_step: i64,
    #[prost(string, tag = "3")]
    pub staging_dir: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct LogArtifactResponse {
    #[prost(string, tag = "1")]
    pub artifact_id: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub error_message: ::prost::alloc::string::String,
}
///
/// DownloadArtifact:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct DownloadArtifactRequest {
    #[prost(string, tag = "1")]
    pub artifact_id: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub download_root: ::prost::alloc::string::String,
    #[prost(bool, tag = "4")]
    pub allow_missing_references: bool,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct DownloadArtifactResponse {
    #[prost(string, tag = "1")]
    pub error_message: ::prost::alloc::string::String,
}
///
/// Keepalive:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct KeepaliveRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct KeepaliveResponse {}
///
/// Job info specific for Partial -> Job upgrade
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ArtifactInfo {
    #[prost(string, tag = "1")]
    pub artifact: ::prost::alloc::string::String,
    #[prost(string, repeated, tag = "2")]
    pub entrypoint: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
    #[prost(bool, tag = "3")]
    pub notebook: bool,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct GitInfo {
    #[prost(string, tag = "1")]
    pub remote: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub commit: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct GitSource {
    #[prost(message, optional, tag = "1")]
    pub git_info: ::core::option::Option<GitInfo>,
    #[prost(string, repeated, tag = "2")]
    pub entrypoint: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
    #[prost(bool, tag = "3")]
    pub notebook: bool,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ImageSource {
    #[prost(string, tag = "1")]
    pub image: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Source {
    #[prost(message, optional, tag = "1")]
    pub git: ::core::option::Option<GitSource>,
    #[prost(message, optional, tag = "2")]
    pub artifact: ::core::option::Option<ArtifactInfo>,
    #[prost(message, optional, tag = "3")]
    pub image: ::core::option::Option<ImageSource>,
}
///
/// Mirrors JobSourceDict:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct JobSource {
    #[prost(string, tag = "1")]
    pub version: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub source_type: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "3")]
    pub source: ::core::option::Option<Source>,
    #[prost(string, tag = "4")]
    pub runtime: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PartialJobArtifact {
    #[prost(string, tag = "1")]
    pub job_name: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "2")]
    pub source_info: ::core::option::Option<JobSource>,
}
///
/// UseArtifact:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct UseArtifactRecord {
    #[prost(string, tag = "1")]
    pub id: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub r#type: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub name: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "4")]
    pub partial: ::core::option::Option<PartialJobArtifact>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct UseArtifactResult {}
///
/// Cancel:
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct CancelRequest {
    /// mailbox slot
    #[prost(string, tag = "1")]
    pub cancel_slot: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RequestInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct CancelResponse {}
///
/// MetadataRequest
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct DiskInfo {
    #[prost(uint64, tag = "1")]
    pub total: u64,
    #[prost(uint64, tag = "2")]
    pub used: u64,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct MemoryInfo {
    #[prost(uint64, tag = "1")]
    pub total: u64,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct CpuInfo {
    #[prost(uint32, tag = "1")]
    pub count: u32,
    #[prost(uint32, tag = "2")]
    pub count_logical: u32,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct GpuAppleInfo {
    #[prost(string, tag = "1")]
    pub gpu_type: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub vendor: ::prost::alloc::string::String,
    #[prost(uint32, tag = "3")]
    pub cores: u32,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct GpuNvidiaInfo {
    #[prost(string, tag = "1")]
    pub name: ::prost::alloc::string::String,
    #[prost(uint64, tag = "2")]
    pub memory_total: u64,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct GpuAmdInfo {
    #[prost(string, tag = "1")]
    pub id: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub unique_id: ::prost::alloc::string::String,
    #[prost(string, tag = "3")]
    pub vbios_version: ::prost::alloc::string::String,
    #[prost(string, tag = "4")]
    pub performance_level: ::prost::alloc::string::String,
    #[prost(string, tag = "5")]
    pub gpu_overdrive: ::prost::alloc::string::String,
    #[prost(string, tag = "6")]
    pub gpu_memory_overdrive: ::prost::alloc::string::String,
    #[prost(string, tag = "7")]
    pub max_power: ::prost::alloc::string::String,
    #[prost(string, tag = "8")]
    pub series: ::prost::alloc::string::String,
    #[prost(string, tag = "9")]
    pub model: ::prost::alloc::string::String,
    #[prost(string, tag = "10")]
    pub vendor: ::prost::alloc::string::String,
    #[prost(string, tag = "11")]
    pub sku: ::prost::alloc::string::String,
    #[prost(string, tag = "12")]
    pub sclk_range: ::prost::alloc::string::String,
    #[prost(string, tag = "13")]
    pub mclk_range: ::prost::alloc::string::String,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct MetadataRequest {
    #[prost(string, tag = "1")]
    pub os: ::prost::alloc::string::String,
    #[prost(string, tag = "2")]
    pub python: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "3")]
    pub heartbeat_at: ::core::option::Option<::prost_types::Timestamp>,
    #[prost(message, optional, tag = "4")]
    pub started_at: ::core::option::Option<::prost_types::Timestamp>,
    #[prost(string, tag = "5")]
    pub docker: ::prost::alloc::string::String,
    #[prost(string, tag = "6")]
    pub cuda: ::prost::alloc::string::String,
    #[prost(string, repeated, tag = "7")]
    pub args: ::prost::alloc::vec::Vec<::prost::alloc::string::String>,
    #[prost(string, tag = "8")]
    pub state: ::prost::alloc::string::String,
    #[prost(string, tag = "9")]
    pub program: ::prost::alloc::string::String,
    #[prost(string, tag = "10")]
    pub code_path: ::prost::alloc::string::String,
    #[prost(message, optional, tag = "11")]
    pub git: ::core::option::Option<GitRepoRecord>,
    #[prost(string, tag = "12")]
    pub email: ::prost::alloc::string::String,
    #[prost(string, tag = "13")]
    pub root: ::prost::alloc::string::String,
    #[prost(string, tag = "14")]
    pub host: ::prost::alloc::string::String,
    #[prost(string, tag = "15")]
    pub username: ::prost::alloc::string::String,
    #[prost(string, tag = "16")]
    pub executable: ::prost::alloc::string::String,
    #[prost(string, tag = "17")]
    pub code_path_local: ::prost::alloc::string::String,
    #[prost(string, tag = "18")]
    pub colab: ::prost::alloc::string::String,
    #[prost(uint32, tag = "19")]
    pub cpu_count: u32,
    #[prost(uint32, tag = "20")]
    pub cpu_count_logical: u32,
    #[prost(string, tag = "21")]
    pub gpu_type: ::prost::alloc::string::String,
    #[prost(uint32, tag = "22")]
    pub gpu_count: u32,
    #[prost(map = "string, message", tag = "23")]
    pub disk: ::std::collections::HashMap<::prost::alloc::string::String, DiskInfo>,
    #[prost(message, optional, tag = "24")]
    pub memory: ::core::option::Option<MemoryInfo>,
    #[prost(message, optional, tag = "25")]
    pub cpu: ::core::option::Option<CpuInfo>,
    #[prost(message, optional, tag = "26")]
    pub gpu_apple: ::core::option::Option<GpuAppleInfo>,
    #[prost(message, repeated, tag = "27")]
    pub gpu_nvidia: ::prost::alloc::vec::Vec<GpuNvidiaInfo>,
    #[prost(message, repeated, tag = "28")]
    pub gpu_amd: ::prost::alloc::vec::Vec<GpuAmdInfo>,
    #[prost(map = "string, string", tag = "29")]
    pub slurm: ::std::collections::HashMap<
        ::prost::alloc::string::String,
        ::prost::alloc::string::String,
    >,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PythonPackagesRequest {
    #[prost(message, repeated, tag = "1")]
    pub package: ::prost::alloc::vec::Vec<python_packages_request::PythonPackage>,
}
/// Nested message and enum types in `PythonPackagesRequest`.
pub mod python_packages_request {
    #[allow(clippy::derive_partial_eq_without_eq)]
    #[derive(Clone, PartialEq, ::prost::Message)]
    pub struct PythonPackage {
        #[prost(string, tag = "1")]
        pub name: ::prost::alloc::string::String,
        #[prost(string, tag = "2")]
        pub version: ::prost::alloc::string::String,
    }
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerShutdownRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerShutdownResponse {}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerStatusRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerStatusResponse {}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInformInitRequest {
    #[prost(message, optional, tag = "1")]
    pub settings: ::core::option::Option<Settings>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInformInitResponse {}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInformStartRequest {
    #[prost(message, optional, tag = "1")]
    pub settings: ::core::option::Option<Settings>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInformStartResponse {}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInformFinishRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInformFinishResponse {}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInformAttachRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInformAttachResponse {
    #[prost(message, optional, tag = "1")]
    pub settings: ::core::option::Option<Settings>,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInformDetachRequest {
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInformDetachResponse {}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInformTeardownRequest {
    #[prost(int32, tag = "1")]
    pub exit_code: i32,
    #[prost(message, optional, tag = "200")]
    pub info: ::core::option::Option<RecordInfo>,
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerInformTeardownResponse {}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerRequest {
    #[prost(
        oneof = "server_request::ServerRequestType",
        tags = "1, 2, 3, 4, 5, 6, 7, 8"
    )]
    pub server_request_type: ::core::option::Option<server_request::ServerRequestType>,
}
/// Nested message and enum types in `ServerRequest`.
pub mod server_request {
    #[allow(clippy::derive_partial_eq_without_eq)]
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum ServerRequestType {
        #[prost(message, tag = "1")]
        RecordPublish(super::Record),
        #[prost(message, tag = "2")]
        RecordCommunicate(super::Record),
        #[prost(message, tag = "3")]
        InformInit(super::ServerInformInitRequest),
        #[prost(message, tag = "4")]
        InformFinish(super::ServerInformFinishRequest),
        #[prost(message, tag = "5")]
        InformAttach(super::ServerInformAttachRequest),
        #[prost(message, tag = "6")]
        InformDetach(super::ServerInformDetachRequest),
        #[prost(message, tag = "7")]
        InformTeardown(super::ServerInformTeardownRequest),
        #[prost(message, tag = "8")]
        InformStart(super::ServerInformStartRequest),
    }
}
#[allow(clippy::derive_partial_eq_without_eq)]
#[derive(Clone, PartialEq, ::prost::Message)]
pub struct ServerResponse {
    #[prost(oneof = "server_response::ServerResponseType", tags = "2, 3, 4, 5, 6, 7, 8")]
    pub server_response_type: ::core::option::Option<
        server_response::ServerResponseType,
    >,
}
/// Nested message and enum types in `ServerResponse`.
pub mod server_response {
    #[allow(clippy::derive_partial_eq_without_eq)]
    #[derive(Clone, PartialEq, ::prost::Oneof)]
    pub enum ServerResponseType {
        #[prost(message, tag = "2")]
        ResultCommunicate(super::Result),
        #[prost(message, tag = "3")]
        InformInitResponse(super::ServerInformInitResponse),
        #[prost(message, tag = "4")]
        InformFinishResponse(super::ServerInformFinishResponse),
        #[prost(message, tag = "5")]
        InformAttachResponse(super::ServerInformAttachResponse),
        #[prost(message, tag = "6")]
        InformDetachResponse(super::ServerInformDetachResponse),
        #[prost(message, tag = "7")]
        InformTeardownResponse(super::ServerInformTeardownResponse),
        #[prost(message, tag = "8")]
        InformStartResponse(super::ServerInformStartResponse),
    }
}

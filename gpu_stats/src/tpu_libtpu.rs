//! TPU metrics via direct libtpu.so SDK integration.
//!
//! Loads libtpu.so at runtime via `libloading`, resolves `GetLibtpuSdkApi`,
//! and calls through the returned C vtable to read TPU metrics (notably
//! `tensorcore_util`, which is only available through this path).
//!
//! No Python, no CGO — pure Rust FFI 🦀.

use crate::metrics::MetricValue;
use crate::monitors::GpuMonitor;
use crate::wandb_internal::EnvironmentRecord;

use async_trait::async_trait;
use libloading::{Library, Symbol};
use log::{debug, warn};
use std::collections::HashMap;
use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

// ---- LibtpuSdkApi vtable layout ----
//
// Recovered from libtpu.so via disassembly (GetLibtpuSdkApi@@VERS_1.0).
// The struct begins with an 8-byte header (two u32), then function pointers.
//
// All API functions: fn(args: *mut SomeArgs) -> *mut c_void (NULL on success, else error handle).

// Vtable byte offsets from start of the LibtpuSdkApi struct.
// The struct has an 8-byte header (two uint32), then function pointers.
// Offsets verified against the CGO probe that successfully reads metrics.
const OFF_ERROR_MESSAGE: usize = 0x08;
const OFF_DESTROY_ERROR: usize = 0x10;
const OFF_CREATE_CLIENT: usize = 0x20;
const OFF_DESTROY_CLIENT: usize = 0x28;
const OFF_GET_METRIC: usize = 0x50;
const OFF_GET_METRIC_DESC: usize = 0x58;
const OFF_GET_METRIC_VALS: usize = 0x60;

// ---- Arg structs matching the C ABI ----

#[repr(C)]
struct CreateClientArgs {
    client: *mut std::ffi::c_void,
}

#[repr(C)]
struct DestroyClientArgs {
    client: *mut std::ffi::c_void,
}

#[repr(C)]
struct GetMetricArgs {
    client: *mut std::ffi::c_void,
    metric_name: *const c_char,
    metric: *mut std::ffi::c_void,
}

#[repr(C)]
struct GetMetricDescriptionArgs {
    metric: *const std::ffi::c_void,
    description: *const c_char,
    description_len: usize,
}

#[repr(C)]
struct GetMetricValuesArgs {
    metric: *const std::ffi::c_void,
    values: *const *const c_char,
    value_count: usize,
}

#[repr(C)]
struct ErrorMessageArgs {
    error: *mut std::ffi::c_void,
    message: *const c_char,
    message_len: usize,
}

#[repr(C)]
struct DestroyErrorArgs {
    error: *mut std::ffi::c_void,
}

type ApiFn = unsafe extern "C" fn(*mut std::ffi::c_void) -> *mut std::ffi::c_void;

/// Reads a function pointer from the vtable at the given byte offset.
unsafe fn vtable_fn(api: *const u8, offset: usize) -> ApiFn {
    let ptr = api.add(offset) as *const ApiFn;
    std::ptr::read(ptr)
}

// ---- Desired metrics ----

struct DesiredMetric {
    logical_name: &'static str,
    aliases: &'static [&'static str],
}

const DESIRED_METRICS: &[DesiredMetric] = &[
    DesiredMetric {
        logical_name: "tensorcore_utilization",
        aliases: &["tensorcore_utilization", "tensorcore_util"],
    },
    DesiredMetric {
        logical_name: "duty_cycle_pct",
        aliases: &["duty_cycle_pct"],
    },
    DesiredMetric {
        logical_name: "hbm_capacity_total",
        aliases: &["hbm_capacity_total"],
    },
    DesiredMetric {
        logical_name: "hbm_capacity_usage",
        aliases: &["hbm_capacity_usage"],
    },
    DesiredMetric {
        logical_name: "buffer_transfer_latency",
        aliases: &["buffer_transfer_latency"],
    },
    DesiredMetric {
        logical_name: "host_to_device_transfer_latency",
        aliases: &["host_to_device_transfer_latency"],
    },
    DesiredMetric {
        logical_name: "device_to_host_transfer_latency",
        aliases: &["device_to_host_transfer_latency"],
    },
    DesiredMetric {
        logical_name: "collective_e2e_latency",
        aliases: &["collective_e2e_latency"],
    },
    DesiredMetric {
        logical_name: "grpc_tcp_min_rtt",
        aliases: &["grpc_tcp_min_rtt", "grpc_tcp_min_round_trip_times"],
    },
    DesiredMetric {
        logical_name: "grpc_tcp_delivery_rate",
        aliases: &["grpc_tcp_delivery_rate", "grpc_tcp_delivery_rates"],
    },
    DesiredMetric {
        logical_name: "hlo_exec_timing",
        aliases: &["hlo_exec_timing"],
    },
    DesiredMetric {
        logical_name: "hlo_queue_size",
        aliases: &["hlo_queue_size"],
    },
];

/// Metric data returned by the SDK.
struct MetricData {
    description: String,
    values: Vec<String>,
}

/// TPU monitor that loads libtpu.so and uses the SDK C API vtable.
pub struct TpuLibtpuMonitor {
    _lib: Library, // must outlive api_ptr and client
    api_ptr: *const u8,
    client: *mut std::ffi::c_void,
    resolved: Mutex<Option<HashMap<String, String>>>,
}

// Safety: the Library, api_ptr, and client are used only through &self methods
// that do synchronized FFI calls. The vtable and client are thread-safe per
// libtpu's documented guarantees (one client per process, metric reads are
// stateless queries).
unsafe impl Send for TpuLibtpuMonitor {}
unsafe impl Sync for TpuLibtpuMonitor {}

impl TpuLibtpuMonitor {
    /// Try to create a TPU libtpu monitor. Returns None if libtpu.so
    /// is not found or GetLibtpuSdkApi is not available.
    pub fn new() -> Option<Self> {
        let path = find_libtpu_path()?;
        debug!("Loading libtpu from: {}", path.display());

        // Safety: we're loading a native library; the symbol resolution
        // and calling conventions are validated against the known ABI.
        let lib = unsafe { Library::new(&path) }.ok()?;

        let api_ptr: *const u8 = unsafe {
            let get_api: Symbol<unsafe extern "C" fn() -> *const u8> =
                lib.get(b"GetLibtpuSdkApi").ok()?;
            get_api()
        };
        if api_ptr.is_null() {
            warn!("GetLibtpuSdkApi() returned NULL");
            return None;
        }

        // Create a client to validate the vtable works.
        let client = unsafe {
            let mut args = CreateClientArgs {
                client: std::ptr::null_mut(),
            };
            let create_fn = vtable_fn(api_ptr, OFF_CREATE_CLIENT);
            let err = create_fn((&raw mut args) as *mut std::ffi::c_void);
            if !err.is_null() {
                let msg = read_error(api_ptr, err);
                warn!("libtpu CreateClient failed: {}", msg);
                return None;
            }
            args.client
        };
        if client.is_null() {
            warn!("libtpu CreateClient returned null client");
            return None;
        }

        debug!("libtpu SDK client created successfully");
        Some(Self {
            _lib: lib,
            api_ptr,
            client,
            resolved: Mutex::new(None),
        })
    }

    /// Discover which metrics are available by probing each desired metric.
    fn resolve_metrics(&self) -> HashMap<String, String> {
        let mut guard = self.resolved.lock().unwrap();
        if let Some(ref resolved) = *guard {
            return resolved.clone();
        }

        let mut resolved = HashMap::new();
        for desired in DESIRED_METRICS {
            for alias in desired.aliases {
                if self.read_metric(alias).is_ok() {
                    resolved.insert(desired.logical_name.to_string(), alias.to_string());
                    break;
                }
            }
        }
        debug!("libtpu resolved metrics: {:?}", resolved);
        *guard = Some(resolved.clone());
        resolved
    }

    /// Read a single metric by name, returning its description and values.
    fn read_metric(&self, name: &str) -> Result<MetricData, String> {
        let cname = CString::new(name).map_err(|e| e.to_string())?;

        // GetMetric
        let metric = unsafe {
            let mut args = GetMetricArgs {
                client: self.client,
                metric_name: cname.as_ptr(),
                metric: std::ptr::null_mut(),
            };
            let get_fn = vtable_fn(self.api_ptr, OFF_GET_METRIC);
            let err = get_fn((&raw mut args) as *mut std::ffi::c_void);
            if !err.is_null() {
                return Err(read_error(self.api_ptr, err));
            }
            if args.metric.is_null() {
                return Err(format!("GetMetric({name}): null handle"));
            }
            args.metric
        };

        // GetMetricDescription
        let description = unsafe {
            let mut args = GetMetricDescriptionArgs {
                metric,
                description: std::ptr::null(),
                description_len: 0,
            };
            let desc_fn = vtable_fn(self.api_ptr, OFF_GET_METRIC_DESC);
            let err = desc_fn((&raw mut args) as *mut std::ffi::c_void);
            if !err.is_null() {
                return Err(read_error(self.api_ptr, err));
            }
            if args.description.is_null() || args.description_len == 0 {
                String::new()
            } else {
                let slice =
                    std::slice::from_raw_parts(args.description as *const u8, args.description_len);
                String::from_utf8_lossy(slice).into_owned()
            }
        };

        // GetMetricValues
        let values = unsafe {
            let mut args = GetMetricValuesArgs {
                metric,
                values: std::ptr::null(),
                value_count: 0,
            };
            let vals_fn = vtable_fn(self.api_ptr, OFF_GET_METRIC_VALS);
            let err = vals_fn((&raw mut args) as *mut std::ffi::c_void);
            if !err.is_null() {
                return Err(read_error(self.api_ptr, err));
            }
            let mut result = Vec::with_capacity(args.value_count);
            for i in 0..args.value_count {
                let str_ptr = *args.values.add(i);
                if str_ptr.is_null() {
                    result.push(String::new());
                } else {
                    result.push(CStr::from_ptr(str_ptr).to_string_lossy().into_owned());
                }
            }
            result
        };

        Ok(MetricData {
            description,
            values,
        })
    }

    /// Collect all resolved TPU metrics.
    fn collect_tpu_metrics(&self) -> Vec<(String, MetricValue)> {
        let resolved = self.resolve_metrics();
        let mut metrics = Vec::new();

        for desired in DESIRED_METRICS {
            let actual_name = match resolved.get(desired.logical_name) {
                Some(name) => name,
                None => continue,
            };

            let data = match self.read_metric(actual_name) {
                Ok(d) => d,
                Err(e) => {
                    debug!("libtpu {}: {}", desired.logical_name, e);
                    continue;
                }
            };

            match desired.logical_name {
                "tensorcore_utilization" => {
                    append_indexed_float(&mut metrics, "tpu.{}.tensorcoreUtilization", &data.values);
                }
                "duty_cycle_pct" => {
                    append_indexed_float(&mut metrics, "tpu.{}.dutyCycle", &data.values);
                }
                "hbm_capacity_total" => {
                    append_indexed_float(&mut metrics, "tpu.{}.hbmCapacityTotal", &data.values);
                }
                "hbm_capacity_usage" => {
                    append_indexed_float(&mut metrics, "tpu.{}.hbmCapacityUsage", &data.values);
                }
                "buffer_transfer_latency" => {
                    append_labeled_distribution(
                        &mut metrics,
                        "tpu.bufferTransferLatency",
                        "Us",
                        &data.description,
                        &data.values,
                    );
                }
                "host_to_device_transfer_latency" => {
                    append_labeled_distribution(
                        &mut metrics,
                        "tpu.hostToDeviceTransferLatency",
                        "Us",
                        &data.description,
                        &data.values,
                    );
                }
                "device_to_host_transfer_latency" => {
                    append_labeled_distribution(
                        &mut metrics,
                        "tpu.deviceToHostTransferLatency",
                        "Us",
                        &data.description,
                        &data.values,
                    );
                }
                "collective_e2e_latency" => {
                    append_labeled_distribution(
                        &mut metrics,
                        "tpu.collectiveE2ELatency",
                        "Us",
                        &data.description,
                        &data.values,
                    );
                }
                "grpc_tcp_min_rtt" => {
                    append_flat_distribution(
                        &mut metrics,
                        "tpu.grpcTcpMinRtt",
                        "Us",
                        &data.description,
                        &data.values,
                    );
                }
                "grpc_tcp_delivery_rate" => {
                    append_flat_distribution(
                        &mut metrics,
                        "tpu.grpcTcpDeliveryRate",
                        "Mbps",
                        &data.description,
                        &data.values,
                    );
                }
                "hlo_exec_timing" => {
                    append_labeled_distribution(
                        &mut metrics,
                        "tpu.hloExecTiming",
                        "Us",
                        &data.description,
                        &data.values,
                    );
                }
                "hlo_queue_size" => {
                    append_colon_values(&mut metrics, "tpu.hloQueueSize", &data.values);
                }
                _ => {}
            }
        }

        metrics
    }
}

impl Drop for TpuLibtpuMonitor {
    fn drop(&mut self) {
        if !self.client.is_null() {
            unsafe {
                let mut args = DestroyClientArgs {
                    client: self.client,
                };
                let destroy_fn = vtable_fn(self.api_ptr, OFF_DESTROY_CLIENT);
                destroy_fn((&raw mut args) as *mut std::ffi::c_void);
            }
        }
    }
}

#[async_trait]
impl GpuMonitor for TpuLibtpuMonitor {
    async fn collect_metrics(
        &self,
        _pid: i32,
        _gpu_device_ids: Option<Vec<i32>>,
    ) -> Result<Vec<(String, MetricValue)>, Box<dyn std::error::Error>> {
        Ok(self.collect_tpu_metrics())
    }

    async fn collect_metadata(
        &self,
        _samples: &HashMap<String, &MetricValue>,
    ) -> EnvironmentRecord {
        EnvironmentRecord::default()
    }
}

// ---- Error handling ----

unsafe fn read_error(api_ptr: *const u8, err_handle: *mut std::ffi::c_void) -> String {
    let mut msg_args = ErrorMessageArgs {
        error: err_handle,
        message: std::ptr::null(),
        message_len: 0,
    };
    let msg_fn = vtable_fn(api_ptr, OFF_ERROR_MESSAGE);
    msg_fn((&raw mut msg_args) as *mut std::ffi::c_void);

    let msg = if !msg_args.message.is_null() && msg_args.message_len > 0 {
        let slice =
            std::slice::from_raw_parts(msg_args.message as *const u8, msg_args.message_len);
        String::from_utf8_lossy(slice).into_owned()
    } else {
        "unknown error".to_string()
    };

    let mut destroy_args = DestroyErrorArgs {
        error: err_handle,
    };
    let destroy_fn = vtable_fn(api_ptr, OFF_DESTROY_ERROR);
    destroy_fn((&raw mut destroy_args) as *mut std::ffi::c_void);

    msg
}

// ---- Metric formatting helpers ----

fn append_indexed_float(
    out: &mut Vec<(String, MetricValue)>,
    key_pattern: &str,
    values: &[String],
) {
    for (i, raw) in values.iter().enumerate() {
        if let Ok(v) = raw.trim().parse::<f64>() {
            out.push((key_pattern.replace("{}", &i.to_string()), MetricValue::Float(v)));
        }
    }
}

fn append_labeled_distribution(
    out: &mut Vec<(String, MetricValue)>,
    base_key: &str,
    unit_suffix: &str,
    description: &str,
    data: &[String],
) {
    for raw in data {
        let parts = split_metric_line(raw);
        if parts.len() < 2 {
            continue;
        }
        let label = sanitize_label(&parts[0]);
        let stats = &parts[1..];
        let names = distribution_stat_names(description, stats.len());
        for (idx, raw_val) in stats.iter().enumerate() {
            if idx >= names.len() {
                break;
            }
            if let Ok(v) = raw_val.trim().parse::<f64>() {
                let name = &names[idx];
                out.push((
                    format!("{base_key}.{label}.{name}{unit_suffix}"),
                    MetricValue::Float(v),
                ));
            }
        }
    }
}

fn append_flat_distribution(
    out: &mut Vec<(String, MetricValue)>,
    base_key: &str,
    unit_suffix: &str,
    description: &str,
    data: &[String],
) {
    // Collect into owned strings to avoid lifetime issues with split_metric_line.
    let stats: Vec<String> = if data.len() == 1 {
        let parts: Vec<String> = split_metric_line(&data[0])
            .into_iter()
            .map(String::from)
            .collect();
        if parts.len() > 1 {
            parts
        } else {
            data.to_vec()
        }
    } else {
        data.to_vec()
    };
    let names = distribution_stat_names(description, stats.len());
    for (idx, raw_val) in stats.iter().enumerate() {
        if idx >= names.len() {
            break;
        }
        if let Ok(v) = raw_val.trim().parse::<f64>() {
            let name = &names[idx];
            out.push((
                format!("{base_key}.{name}{unit_suffix}"),
                MetricValue::Float(v),
            ));
        }
    }
}

fn append_colon_values(
    out: &mut Vec<(String, MetricValue)>,
    base_key: &str,
    data: &[String],
) {
    for (idx, raw) in data.iter().enumerate() {
        let (label, value_str) = if let Some(pos) = raw.find(':') {
            (
                sanitize_label(&raw[..pos]),
                raw[pos + 1..].to_string(),
            )
        } else {
            (format!("item_{idx}"), raw.clone())
        };
        if let Ok(v) = value_str.trim().parse::<f64>() {
            out.push((format!("{base_key}.{label}"), MetricValue::Float(v)));
        }
    }
}

fn distribution_stat_names(description: &str, count: usize) -> Vec<String> {
    let desc_lower = description.to_lowercase();
    match count {
        5 => {
            if desc_lower.contains("p99") && !desc_lower.contains("p95") {
                vec!["mean", "p50", "p90", "p99", "p999"]
            } else {
                vec!["mean", "p50", "p90", "p95", "p999"]
            }
        }
        4 => vec!["p50", "p90", "p95", "p999"],
        _ => (0..count).map(|i| format!("stat{i}")).collect(),
    }
    .into_iter()
    .map(String::from)
    .collect()
}

fn split_metric_line(raw: &str) -> Vec<&str> {
    let raw = raw.trim().trim_matches(&['[', ']'][..]);
    if raw.is_empty() {
        return vec![];
    }
    raw.split(',')
        .map(|s| s.trim().trim_matches(&['"', '\''][..]))
        .filter(|s| !s.is_empty())
        .collect()
}

fn sanitize_label(label: &str) -> String {
    let label = label.trim().to_lowercase();
    let label = label.replace('+', "_plus_").replace('%', "pct");
    let mut result = String::with_capacity(label.len());
    let mut last_underscore = false;
    for c in label.chars() {
        if c.is_ascii_lowercase() || c.is_ascii_digit() {
            result.push(c);
            last_underscore = false;
        } else if !last_underscore {
            result.push('_');
            last_underscore = true;
        }
    }
    let result = result.trim_matches('_').to_string();
    if result.is_empty() {
        "unknown".to_string()
    } else {
        result
    }
}

// ---- libtpu.so discovery ----

fn find_libtpu_path() -> Option<PathBuf> {
    // Environment overrides.
    for var in &["WANDB_LIBTPU_PATH", "TPU_LIBRARY_PATH", "LIBTPU_PATH"] {
        if let Ok(val) = std::env::var(var) {
            let val = val.trim();
            if !val.is_empty() {
                let path = resolve_libtpu_path(Path::new(val));
                if path.is_some() {
                    return path;
                }
            }
        }
    }

    // Standard search paths.
    let mut candidates: Vec<PathBuf> = vec![
        "/lib/libtpu.so".into(),
        "/usr/lib/libtpu.so".into(),
        "/usr/local/lib/libtpu.so".into(),
    ];

    if let Ok(home) = std::env::var("HOME") {
        for pattern in &[
            format!("{home}/.local/lib/python*/site-packages/libtpu/libtpu.so"),
            format!("{home}/.local/lib/python*/site-packages/torch_xla/lib/libtpu.so"),
            format!("{home}/.venv/lib/python*/site-packages/libtpu/libtpu.so"),
        ] {
            if let Ok(matches) = glob::glob(pattern) {
                for path in matches.flatten() {
                    candidates.push(path);
                }
            }
        }
    }

    for pattern in &[
        "/usr/local/lib/python*/dist-packages/libtpu/libtpu.so",
        "/usr/local/lib/python*/dist-packages/torch_xla/lib/libtpu.so",
    ] {
        if let Ok(matches) = glob::glob(pattern) {
            for path in matches.flatten() {
                candidates.push(path);
            }
        }
    }

    candidates.into_iter().find_map(|p| resolve_libtpu_path(&p))
}

fn resolve_libtpu_path(path: &Path) -> Option<PathBuf> {
    if path.is_dir() {
        let joined = path.join("libtpu.so");
        if joined.is_file() {
            return Some(joined);
        }
        return None;
    }
    if path.is_file() {
        return Some(path.to_path_buf());
    }
    None
}

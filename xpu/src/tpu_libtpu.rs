//! TPU metrics via libtpu.so SDK (primary) with gRPC fallback.
//!
//! The SDK path loads libtpu.so at runtime, resolves `GetLibtpuSdkApi`,
//! and calls through the C vtable. This is the only way to get
//! `tensorcore_util`.
//!
//! If the SDK is unavailable or a metric fails, the gRPC fallback
//! connects to the TPU runtime service on localhost:8431.

use crate::metrics::MetricValue;
use crate::monitors::GpuMonitor;
use crate::tpu_runtime as proto;
use crate::wandb_internal::EnvironmentRecord;

use async_trait::async_trait;
use libloading::{Library, Symbol};
use log::{debug, warn};
use std::collections::HashMap;
use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use tonic::transport::Channel;

// ============================================================
// Public monitor — orchestrates SDK + gRPC
// ============================================================

pub struct TpuMonitor {
    sdk: Option<SdkClient>,
    grpc: Mutex<Option<GrpcClient>>,
}

impl TpuMonitor {
    pub fn new() -> Option<Self> {
        let sdk = SdkClient::new();
        let grpc_available = is_grpc_available();

        if sdk.is_none() && !grpc_available {
            return None;
        }

        if sdk.is_some() {
            debug!("TPU: libtpu SDK client initialized");
        }
        if grpc_available {
            debug!("TPU: gRPC runtime service available on localhost:8431");
        }

        Some(Self {
            sdk,
            grpc: Mutex::new(None),
        })
    }

    fn collect_tpu_metrics(&self) -> Vec<(String, MetricValue)> {
        let mut metrics = Vec::new();
        let mut sdk_failures = Vec::new();

        // Phase 1: collect everything we can from the SDK.
        if let Some(sdk) = &self.sdk {
            let resolved = sdk.resolve_metrics();
            for desired in DESIRED_METRICS {
                if let Some(actual_name) = resolved.get(desired.logical_name) {
                    match sdk.read_metric(actual_name) {
                        Ok(data) => {
                            format_metric(desired.logical_name, &data, &mut metrics);
                            continue;
                        }
                        Err(e) => {
                            debug!("TPU SDK {}: {e}", desired.logical_name);
                            sdk_failures.push(desired.logical_name);
                        }
                    }
                } else {
                    sdk_failures.push(desired.logical_name);
                }
            }
        } else {
            sdk_failures.extend(DESIRED_METRICS.iter().map(|d| d.logical_name));
        }

        // Phase 2: fill gaps from gRPC.
        if !sdk_failures.is_empty() {
            if let Some(grpc) = self.get_grpc_client() {
                for logical_name in sdk_failures {
                    if let Some(grpc_name) = GRPC_METRIC_MAP.get(logical_name) {
                        match grpc.get_metric(grpc_name) {
                            Ok(tpu_metric) => {
                                format_grpc_metric(logical_name, &tpu_metric, &mut metrics);
                            }
                            Err(e) => {
                                debug!("TPU gRPC {logical_name}: {e}");
                            }
                        }
                    }
                }
            }
        }

        metrics
    }

    fn get_grpc_client(&self) -> Option<GrpcClient> {
        let mut guard = self.grpc.lock().unwrap();
        if guard.is_none() {
            *guard = GrpcClient::new();
        }
        guard.clone()
    }
}

#[async_trait]
impl GpuMonitor for TpuMonitor {
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

// ============================================================
// Desired metrics and naming
// ============================================================

struct DesiredMetric {
    logical_name: &'static str,
    sdk_aliases: &'static [&'static str],
}

const DESIRED_METRICS: &[DesiredMetric] = &[
    DesiredMetric {
        logical_name: "tensorcore_utilization",
        sdk_aliases: &["tensorcore_utilization", "tensorcore_util"],
    },
    DesiredMetric {
        logical_name: "duty_cycle_pct",
        sdk_aliases: &["duty_cycle_pct"],
    },
    DesiredMetric {
        logical_name: "hbm_capacity_total",
        sdk_aliases: &["hbm_capacity_total"],
    },
    DesiredMetric {
        logical_name: "hbm_capacity_usage",
        sdk_aliases: &["hbm_capacity_usage"],
    },
    DesiredMetric {
        logical_name: "buffer_transfer_latency",
        sdk_aliases: &["buffer_transfer_latency"],
    },
    DesiredMetric {
        logical_name: "inbound_buffer_transfer_latency",
        sdk_aliases: &["inbound_buffer_transfer_latency"],
    },
    DesiredMetric {
        logical_name: "host_to_device_transfer_latency",
        sdk_aliases: &["host_to_device_transfer_latency"],
    },
    DesiredMetric {
        logical_name: "device_to_host_transfer_latency",
        sdk_aliases: &["device_to_host_transfer_latency"],
    },
    DesiredMetric {
        logical_name: "collective_e2e_latency",
        sdk_aliases: &["collective_e2e_latency"],
    },
    DesiredMetric {
        logical_name: "host_compute_latency",
        sdk_aliases: &["host_compute_latency"],
    },
    DesiredMetric {
        logical_name: "grpc_tcp_min_rtt",
        sdk_aliases: &["grpc_tcp_min_rtt", "grpc_tcp_min_round_trip_times"],
    },
    DesiredMetric {
        logical_name: "grpc_tcp_delivery_rate",
        sdk_aliases: &["grpc_tcp_delivery_rate", "grpc_tcp_delivery_rates"],
    },
    DesiredMetric {
        logical_name: "hlo_exec_timing",
        sdk_aliases: &["hlo_exec_timing"],
    },
    DesiredMetric {
        logical_name: "hlo_queue_size",
        sdk_aliases: &["hlo_queue_size"],
    },
];

static GRPC_METRIC_MAP: std::sync::LazyLock<HashMap<&'static str, &'static str>> =
    std::sync::LazyLock::new(|| {
        HashMap::from([
            ("duty_cycle_pct", "tpu.runtime.tensorcore.dutycycle.percent"),
            ("hbm_capacity_total", "tpu.runtime.hbm.memory.total.bytes"),
            ("hbm_capacity_usage", "tpu.runtime.hbm.memory.usage.bytes"),
            (
                "buffer_transfer_latency",
                "megascale.dcn_transfer_latencies.microsecond.cumulative.distribution",
            ),
            (
                "inbound_buffer_transfer_latency",
                "megascale.dcn_inbound_transfer_latencies.microsecond.cumulative.distribution",
            ),
            (
                "host_to_device_transfer_latency",
                "megascale.host_to_device_transfer_latencies.microsecond.cumulative.distribution",
            ),
            (
                "device_to_host_transfer_latency",
                "megascale.device_to_host_transfer_latencies.microsecond.cumulative.distribution",
            ),
            (
                "collective_e2e_latency",
                "megascale.collective_end_to_end_latencies.microsecond.cumulative.distribution",
            ),
            (
                "host_compute_latency",
                "megascale.mxla_compute_latencies.microsecond.cumulative.distribution",
            ),
            (
                "grpc_tcp_min_rtt",
                "megascale.grpc_tcp_min_rtt.microsecond.cumulative.distribution",
            ),
            (
                "grpc_tcp_delivery_rate",
                "megascale.grpc_tcp_delivery_rate.Mbps.cumulative.distribution",
            ),
            (
                "hlo_exec_timing",
                "hlo.execution.timing.distribution.microseconds",
            ),
            ("hlo_queue_size", "hlo.queue.size.gauge"),
        ])
    });

// ============================================================
// SDK client — libtpu.so via FFI
// ============================================================

// Vtable byte offsets from start of LibtpuSdkApi struct.
// Verified against libtpu and 0.0.38 (VERS_1.0 ABI).
const OFF_ERROR_MESSAGE: usize = 0x08;
const OFF_DESTROY_ERROR: usize = 0x10;
const OFF_CREATE_CLIENT: usize = 0x20;
const OFF_DESTROY_CLIENT: usize = 0x28;
const OFF_GET_METRIC: usize = 0x50;
const OFF_GET_METRIC_DESC: usize = 0x58;
const OFF_GET_METRIC_VALS: usize = 0x60;

type ApiFn = unsafe extern "C" fn(*mut std::ffi::c_void) -> *mut std::ffi::c_void;

unsafe fn vtable_fn(api: *const u8, offset: usize) -> ApiFn {
    unsafe { std::ptr::read(api.add(offset) as *const ApiFn) }
}

struct SdkMetricData {
    description: String,
    values: Vec<String>,
}

struct SdkClient {
    _lib: Library,
    api_ptr: *const u8,
    client: *mut std::ffi::c_void,
    resolved: Mutex<Option<HashMap<String, String>>>,
}

unsafe impl Send for SdkClient {}
unsafe impl Sync for SdkClient {}

impl SdkClient {
    fn new() -> Option<Self> {
        let path = find_libtpu_path()?;
        debug!("Loading libtpu from: {}", path.display());

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

        #[repr(C)]
        struct CreateClientArgs {
            client: *mut std::ffi::c_void,
        }

        let client = unsafe {
            let mut args = CreateClientArgs {
                client: std::ptr::null_mut(),
            };
            let err =
                vtable_fn(api_ptr, OFF_CREATE_CLIENT)((&raw mut args) as *mut std::ffi::c_void);
            if !err.is_null() {
                let msg = read_error(api_ptr, err);
                warn!("libtpu CreateClient failed: {msg}");
                return None;
            }
            args.client
        };
        if client.is_null() {
            warn!("libtpu CreateClient returned null");
            return None;
        }

        Some(Self {
            _lib: lib,
            api_ptr,
            client,
            resolved: Mutex::new(None),
        })
    }

    fn resolve_metrics(&self) -> HashMap<String, String> {
        let mut guard = self.resolved.lock().unwrap();
        if let Some(ref r) = *guard {
            return r.clone();
        }
        let mut resolved = HashMap::new();
        for desired in DESIRED_METRICS {
            for alias in desired.sdk_aliases {
                if self.read_metric(alias).is_ok() {
                    resolved.insert(desired.logical_name.to_string(), alias.to_string());
                    break;
                }
            }
        }
        *guard = Some(resolved.clone());
        resolved
    }

    fn read_metric(&self, name: &str) -> Result<SdkMetricData, String> {
        let cname = CString::new(name).map_err(|e| e.to_string())?;

        #[repr(C)]
        struct GetMetricArgs {
            client: *mut std::ffi::c_void,
            metric_name: *const c_char,
            metric: *mut std::ffi::c_void,
        }

        let metric = unsafe {
            let mut args = GetMetricArgs {
                client: self.client,
                metric_name: cname.as_ptr(),
                metric: std::ptr::null_mut(),
            };
            let err =
                vtable_fn(self.api_ptr, OFF_GET_METRIC)((&raw mut args) as *mut std::ffi::c_void);
            if !err.is_null() {
                return Err(read_error(self.api_ptr, err));
            }
            if args.metric.is_null() {
                return Err(format!("GetMetric({name}): null"));
            }
            args.metric
        };

        #[repr(C)]
        struct GetDescArgs {
            metric: *mut std::ffi::c_void,
            description: *const c_char,
            description_len: usize,
        }

        let description = unsafe {
            let mut args = GetDescArgs {
                metric,
                description: std::ptr::null(),
                description_len: 0,
            };
            let err = vtable_fn(self.api_ptr, OFF_GET_METRIC_DESC)(
                (&raw mut args) as *mut std::ffi::c_void,
            );
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

        #[repr(C)]
        struct GetValsArgs {
            metric: *mut std::ffi::c_void,
            values: *const *const c_char,
            value_count: usize,
        }

        let values = unsafe {
            let mut args = GetValsArgs {
                metric,
                values: std::ptr::null(),
                value_count: 0,
            };
            let err = vtable_fn(self.api_ptr, OFF_GET_METRIC_VALS)(
                (&raw mut args) as *mut std::ffi::c_void,
            );
            if !err.is_null() {
                return Err(read_error(self.api_ptr, err));
            }
            (0..args.value_count)
                .map(|i| {
                    let p = *args.values.add(i);
                    if p.is_null() {
                        String::new()
                    } else {
                        CStr::from_ptr(p).to_string_lossy().into_owned()
                    }
                })
                .collect()
        };

        Ok(SdkMetricData {
            description,
            values,
        })
    }
}

impl Drop for SdkClient {
    fn drop(&mut self) {
        if !self.client.is_null() {
            #[repr(C)]
            struct DestroyClientArgs {
                client: *mut std::ffi::c_void,
            }
            unsafe {
                let mut args = DestroyClientArgs {
                    client: self.client,
                };
                vtable_fn(self.api_ptr, OFF_DESTROY_CLIENT)(
                    (&raw mut args) as *mut std::ffi::c_void,
                );
            }
        }
    }
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

unsafe fn read_error(api_ptr: *const u8, err: *mut std::ffi::c_void) -> String {
    let mut msg_args = ErrorMessageArgs {
        error: err,
        message: std::ptr::null(),
        message_len: 0,
    };
    unsafe { vtable_fn(api_ptr, OFF_ERROR_MESSAGE)((&raw mut msg_args) as *mut std::ffi::c_void) };
    let msg = if !msg_args.message.is_null() && msg_args.message_len > 0 {
        let s = unsafe { std::slice::from_raw_parts(msg_args.message as *const u8, msg_args.message_len) };
        String::from_utf8_lossy(s).into_owned()
    } else {
        "unknown error".to_string()
    };
    let mut d = DestroyErrorArgs { error: err };
    unsafe { vtable_fn(api_ptr, OFF_DESTROY_ERROR)((&raw mut d) as *mut std::ffi::c_void) };
    msg
}

// ============================================================
// gRPC client — localhost:8431 fallback
// ============================================================

const GRPC_ADDR: &str = "http://localhost:8431";

#[derive(Clone)]
struct GrpcClient {
    client: proto::runtime_metric_service_client::RuntimeMetricServiceClient<Channel>,
}

impl GrpcClient {
    fn new() -> Option<Self> {
        let rt = tokio::runtime::Handle::try_current().ok()?;
        let channel = rt.block_on(async {
            Channel::from_static(GRPC_ADDR)
                .connect_timeout(std::time::Duration::from_secs(2))
                .connect()
                .await
                .ok()
        })?;
        Some(Self {
            client: proto::runtime_metric_service_client::RuntimeMetricServiceClient::new(channel),
        })
    }

    fn get_metric(&self, metric_name: &str) -> Result<proto::TpuMetric, String> {
        let mut client = self.client.clone();
        let name = metric_name.to_string();
        let rt = tokio::runtime::Handle::try_current().map_err(|e| e.to_string())?;
        rt.block_on(async {
            let resp = client
                .get_runtime_metric(proto::MetricRequest {
                    metric_name: name,
                    skip_node_aggregation: false,
                })
                .await
                .map_err(|e| e.to_string())?;
            resp.into_inner()
                .metric
                .ok_or_else(|| "empty response".to_string())
        })
    }
}

fn is_grpc_available() -> bool {
    std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8431".parse().unwrap(),
        std::time::Duration::from_millis(500),
    )
    .is_ok()
}

// ============================================================
// Metric formatting — SDK path
// ============================================================

fn format_metric(logical_name: &str, data: &SdkMetricData, out: &mut Vec<(String, MetricValue)>) {
    match logical_name {
        "tensorcore_utilization" => {
            indexed_float(out, "tpu.{}.tensorcoreUtilization", &data.values)
        }
        "duty_cycle_pct" => indexed_float(out, "tpu.{}.dutyCycle", &data.values),
        "hbm_capacity_total" => indexed_float(out, "tpu.{}.hbmCapacityTotal", &data.values),
        "hbm_capacity_usage" => indexed_float(out, "tpu.{}.hbmCapacityUsage", &data.values),
        "buffer_transfer_latency" => labeled_dist(
            out,
            "tpu.bufferTransferLatency",
            "Us",
            &data.description,
            &data.values,
        ),
        "inbound_buffer_transfer_latency" => labeled_dist(
            out,
            "tpu.inboundBufferTransferLatency",
            "Us",
            &data.description,
            &data.values,
        ),
        "host_to_device_transfer_latency" => labeled_dist(
            out,
            "tpu.hostToDeviceTransferLatency",
            "Us",
            &data.description,
            &data.values,
        ),
        "device_to_host_transfer_latency" => labeled_dist(
            out,
            "tpu.deviceToHostTransferLatency",
            "Us",
            &data.description,
            &data.values,
        ),
        "collective_e2e_latency" => labeled_dist(
            out,
            "tpu.collectiveE2ELatency",
            "Us",
            &data.description,
            &data.values,
        ),
        "host_compute_latency" => labeled_dist(
            out,
            "tpu.hostComputeLatency",
            "Us",
            &data.description,
            &data.values,
        ),
        "grpc_tcp_min_rtt" => flat_dist(
            out,
            "tpu.grpcTcpMinRtt",
            "Us",
            &data.description,
            &data.values,
        ),
        "grpc_tcp_delivery_rate" => flat_dist(
            out,
            "tpu.grpcTcpDeliveryRate",
            "Mbps",
            &data.description,
            &data.values,
        ),
        "hlo_exec_timing" => labeled_dist(
            out,
            "tpu.hloExecTiming",
            "Us",
            &data.description,
            &data.values,
        ),
        "hlo_queue_size" => colon_values(out, "tpu.hloQueueSize", &data.values),
        _ => {}
    }
}

fn indexed_float(out: &mut Vec<(String, MetricValue)>, pattern: &str, values: &[String]) {
    for (i, raw) in values.iter().enumerate() {
        if let Ok(v) = raw.trim().parse::<f64>() {
            out.push((pattern.replace("{}", &i.to_string()), MetricValue::Float(v)));
        }
    }
}

fn labeled_dist(
    out: &mut Vec<(String, MetricValue)>,
    base: &str,
    unit: &str,
    desc: &str,
    data: &[String],
) {
    for raw in data {
        let parts = split_csv(raw);
        if parts.len() < 2 {
            continue;
        }
        let label = sanitize(&parts[0]);
        let names = stat_names(desc, parts.len() - 1);
        for (i, val) in parts[1..].iter().enumerate() {
            if i >= names.len() {
                break;
            }
            if let Ok(v) = val.trim().parse::<f64>() {
                out.push((
                    format!("{base}.{label}.{}{unit}", names[i]),
                    MetricValue::Float(v),
                ));
            }
        }
    }
}

fn flat_dist(
    out: &mut Vec<(String, MetricValue)>,
    base: &str,
    unit: &str,
    desc: &str,
    data: &[String],
) {
    let vals: Vec<String> = if data.len() == 1 {
        let p = split_csv(&data[0]);
        if p.len() > 1 { p } else { data.to_vec() }
    } else {
        data.to_vec()
    };
    let names = stat_names(desc, vals.len());
    for (i, raw) in vals.iter().enumerate() {
        if i >= names.len() {
            break;
        }
        if let Ok(v) = raw.trim().parse::<f64>() {
            out.push((format!("{base}.{}{unit}", names[i]), MetricValue::Float(v)));
        }
    }
}

fn colon_values(out: &mut Vec<(String, MetricValue)>, base: &str, data: &[String]) {
    for (i, raw) in data.iter().enumerate() {
        let (label, val) = raw
            .split_once(':')
            .map(|(l, r)| (sanitize(l), r.to_string()))
            .unwrap_or_else(|| (format!("item_{i}"), raw.clone()));
        if let Ok(v) = val.trim().parse::<f64>() {
            out.push((format!("{base}.{label}"), MetricValue::Float(v)));
        }
    }
}

// ============================================================
// Metric formatting — gRPC path
// ============================================================

fn format_grpc_metric(
    logical_name: &str,
    tpu_metric: &proto::TpuMetric,
    out: &mut Vec<(String, MetricValue)>,
) {
    let base_key = match logical_name {
        "duty_cycle_pct" | "hbm_capacity_total" | "hbm_capacity_usage" => {
            // Per-device gauge metrics.
            for m in &tpu_metric.metrics {
                let did = grpc_device_id(m);
                if let Some(v) = grpc_gauge_value(m) {
                    let key = match logical_name {
                        "duty_cycle_pct" => format!("tpu.{did}.dutyCycle"),
                        "hbm_capacity_total" => format!("tpu.{did}.hbmCapacityTotal"),
                        "hbm_capacity_usage" => format!("tpu.{did}.hbmCapacityUsage"),
                        _ => continue,
                    };
                    out.push((key, MetricValue::Float(v)));
                }
            }
            return;
        }
        "buffer_transfer_latency" => "tpu.bufferTransferLatency",
        "inbound_buffer_transfer_latency" => "tpu.inboundBufferTransferLatency",
        "host_to_device_transfer_latency" => "tpu.hostToDeviceTransferLatency",
        "device_to_host_transfer_latency" => "tpu.deviceToHostTransferLatency",
        "collective_e2e_latency" => "tpu.collectiveE2ELatency",
        "host_compute_latency" => "tpu.hostComputeLatency",
        "grpc_tcp_min_rtt" => "tpu.grpcTcpMinRtt",
        "grpc_tcp_delivery_rate" => "tpu.grpcTcpDeliveryRate",
        "hlo_exec_timing" => "tpu.hloExecTiming",
        "hlo_queue_size" => "tpu.hloQueueSize",
        _ => return,
    };

    let unit = match logical_name {
        "grpc_tcp_delivery_rate" => "Mbps",
        "hlo_queue_size" => "",
        _ => "Us",
    };

    for (idx, m) in tpu_metric.metrics.iter().enumerate() {
        let label = grpc_label(m).unwrap_or_else(|| format!("item_{idx}"));

        if logical_name == "hlo_queue_size" {
            if let Some(v) = grpc_gauge_value(m) {
                out.push((format!("{base_key}.{label}"), MetricValue::Float(v)));
            }
            continue;
        }

        // Distribution or Summary.
        if let Some(proto::metric::Measure::Summary(ref s)) = m.measure {
            if s.sample_count > 0 {
                out.push((
                    format!("{base_key}.{label}.mean{unit}"),
                    MetricValue::Float(s.sample_sum / s.sample_count as f64),
                ));
            }
            for q in &s.quantile {
                if let Some(name) = quantile_name(q.quantile) {
                    out.push((
                        format!("{base_key}.{label}.{name}{unit}"),
                        MetricValue::Float(q.value),
                    ));
                }
            }
        } else if let Some(proto::metric::Measure::Distribution(ref d)) = m.measure {
            if d.count > 0 {
                out.push((
                    format!("{base_key}.{label}.mean{unit}"),
                    MetricValue::Float(d.mean),
                ));
                for (name, val) in distribution_percentiles(d) {
                    out.push((
                        format!("{base_key}.{label}.{name}{unit}"),
                        MetricValue::Float(val),
                    ));
                }
            }
        }
    }
}

fn grpc_device_id(m: &proto::Metric) -> i64 {
    m.attribute
        .as_ref()
        .and_then(|a| a.value.as_ref())
        .and_then(|v| match &v.attr {
            Some(proto::attr_value::Attr::IntAttr(i)) => Some(*i),
            _ => None,
        })
        .unwrap_or(0)
}

fn grpc_gauge_value(m: &proto::Metric) -> Option<f64> {
    match &m.measure {
        Some(proto::metric::Measure::Gauge(g)) => match &g.value {
            Some(proto::gauge::Value::AsDouble(v)) => Some(*v),
            Some(proto::gauge::Value::AsInt(v)) => Some(*v as f64),
            _ => None,
        },
        _ => None,
    }
}

fn grpc_label(m: &proto::Metric) -> Option<String> {
    m.attribute
        .as_ref()
        .and_then(|a| a.value.as_ref())
        .and_then(|v| match &v.attr {
            Some(proto::attr_value::Attr::StringAttr(s)) if !s.is_empty() => Some(sanitize(s)),
            _ => None,
        })
}

fn quantile_name(q: f64) -> Option<&'static str> {
    const EPS: f64 = 1e-9;
    if (q - 0.50).abs() < EPS {
        Some("p50")
    } else if (q - 0.90).abs() < EPS {
        Some("p90")
    } else if (q - 0.95).abs() < EPS {
        Some("p95")
    } else if (q - 0.99).abs() < EPS {
        Some("p99")
    } else if (q - 0.999).abs() < EPS {
        Some("p999")
    } else {
        None
    }
}

fn distribution_percentiles(d: &proto::Distribution) -> Vec<(&'static str, f64)> {
    let counts = &d.bucket_counts;
    if counts.is_empty() {
        return vec![];
    }
    let total: i64 = counts.iter().sum();
    if total == 0 {
        return vec![];
    }
    let bounds = distribution_boundaries(d);
    [("p50", 0.50), ("p90", 0.90), ("p95", 0.95), ("p999", 0.999)]
        .iter()
        .map(|(name, q)| (*name, interpolate_percentile(counts, &bounds, total, *q)))
        .collect()
}

fn distribution_boundaries(d: &proto::Distribution) -> Vec<f64> {
    let opts = match &d.bucket_options {
        Some(o) => o,
        None => return vec![],
    };
    match &opts.options {
        Some(proto::distribution::bucket_options::Options::ExponentialBuckets(e)) => {
            (0..e.num_finite_buckets as usize)
                .map(|i| e.scale * e.growth_factor.powi(i as i32 + 1))
                .collect()
        }
        Some(proto::distribution::bucket_options::Options::LinearBuckets(l)) => {
            (0..l.num_finite_buckets as usize)
                .map(|i| l.offset + l.width * (i as f64 + 1.0))
                .collect()
        }
        Some(proto::distribution::bucket_options::Options::ExplicitBuckets(e)) => e.bounds.clone(),
        None => vec![],
    }
}

fn interpolate_percentile(counts: &[i64], bounds: &[f64], total: i64, quantile: f64) -> f64 {
    let target = total as f64 * quantile;
    let mut cumulative: i64 = 0;
    for (i, &count) in counts.iter().enumerate() {
        cumulative += count;
        if (cumulative as f64) < target {
            continue;
        }
        let (lo, hi) = bucket_range(bounds, i);
        let prev = cumulative - count;
        let frac = (target - prev as f64) / count as f64;
        return lo + frac * (hi - lo);
    }
    bounds.last().copied().unwrap_or(0.0)
}

fn bucket_range(bounds: &[f64], index: usize) -> (f64, f64) {
    if bounds.is_empty() {
        return (0.0, 0.0);
    }
    match index {
        0 => (0.0, bounds[0]),
        i if i <= bounds.len() => (bounds[i - 1], bounds[i.min(bounds.len() - 1)]),
        _ => {
            let last = *bounds.last().unwrap();
            (last, last)
        }
    }
}

// ============================================================
// Helpers
// ============================================================

fn stat_names(desc: &str, count: usize) -> Vec<String> {
    let d = desc.to_lowercase();
    match count {
        5 if d.contains("p99") && !d.contains("p95") => vec!["mean", "p50", "p90", "p99", "p999"],
        5 => vec!["mean", "p50", "p90", "p95", "p999"],
        4 => vec!["p50", "p90", "p95", "p999"],
        _ => return (0..count).map(|i| format!("stat{i}")).collect(),
    }
    .into_iter()
    .map(String::from)
    .collect()
}

fn split_csv(raw: &str) -> Vec<String> {
    let raw = raw.trim().trim_matches(&['[', ']'][..]);
    if raw.is_empty() {
        return vec![];
    }
    raw.split(',')
        .map(|s| s.trim().trim_matches(&['"', '\''][..]).to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

fn sanitize(label: &str) -> String {
    let label = label
        .trim()
        .to_lowercase()
        .replace('+', "_plus_")
        .replace('%', "pct");
    let mut out = String::with_capacity(label.len());
    let mut last_under = false;
    for c in label.chars() {
        if c.is_ascii_lowercase() || c.is_ascii_digit() {
            out.push(c);
            last_under = false;
        } else if !last_under {
            out.push('_');
            last_under = true;
        }
    }
    let out = out.trim_matches('_').to_string();
    if out.is_empty() {
        "unknown".to_string()
    } else {
        out
    }
}

// ============================================================
// libtpu.so discovery
// ============================================================

fn find_libtpu_path() -> Option<PathBuf> {
    for var in &["WANDB_LIBTPU_PATH", "TPU_LIBRARY_PATH", "LIBTPU_PATH"] {
        if let Ok(val) = std::env::var(var) {
            if let Some(p) = resolve_path(Path::new(val.trim())) {
                return Some(p);
            }
        }
    }
    let mut candidates: Vec<PathBuf> = vec![
        "/lib/libtpu.so".into(),
        "/usr/lib/libtpu.so".into(),
        "/usr/local/lib/libtpu.so".into(),
    ];
    if let Ok(home) = std::env::var("HOME") {
        for pattern in [
            format!("{home}/.local/lib/python*/site-packages/libtpu/libtpu.so"),
            format!("{home}/.venv/lib/python*/site-packages/libtpu/libtpu.so"),
        ] {
            if let Ok(matches) = glob::glob(&pattern) {
                candidates.extend(matches.flatten());
            }
        }
    }
    for pattern in [
        "/usr/local/lib/python*/dist-packages/libtpu/libtpu.so",
        "/usr/local/lib/python*/dist-packages/torch_xla/lib/libtpu.so",
    ] {
        if let Ok(matches) = glob::glob(pattern) {
            candidates.extend(matches.flatten());
        }
    }
    candidates.into_iter().find_map(|p| resolve_path(&p))
}

fn resolve_path(path: &Path) -> Option<PathBuf> {
    if path.is_dir() {
        let j = path.join("libtpu.so");
        if j.is_file() {
            return Some(j);
        }
        return None;
    }
    if path.is_file() {
        Some(path.to_path_buf())
    } else {
        None
    }
}

// ============================================================
// Tests
// ============================================================

#[cfg(test)]
mod tests {
    use super::*;

    // ---- helpers ----

    fn metrics_map(v: &[(String, MetricValue)]) -> HashMap<String, f64> {
        v.iter()
            .filter_map(|(k, v)| match v {
                MetricValue::Float(f) => Some((k.clone(), *f)),
                _ => None,
            })
            .collect()
    }

    // ---- sanitize ----

    #[test]
    fn test_sanitize_simple() {
        assert_eq!(sanitize("tensor_core-0"), "tensor_core_0");
    }

    #[test]
    fn test_sanitize_special_chars() {
        assert_eq!(sanitize("  GPU+Memory 100% "), "gpu_plus_memory_100pct");
    }

    #[test]
    fn test_sanitize_empty() {
        assert_eq!(sanitize("!!!"), "unknown");
    }

    // ---- split_csv ----

    #[test]
    fn test_split_csv_bracketed() {
        let v = split_csv("[1.0, 2.0, 3.0]");
        assert_eq!(v, vec!["1.0", "2.0", "3.0"]);
    }

    #[test]
    fn test_split_csv_quoted() {
        let v = split_csv("'hello', \"world\"");
        assert_eq!(v, vec!["hello", "world"]);
    }

    #[test]
    fn test_split_csv_empty() {
        assert!(split_csv("").is_empty());
        assert!(split_csv("[]").is_empty());
    }

    // ---- stat_names ----

    #[test]
    fn test_stat_names_5_default() {
        let names = stat_names("latency distribution (mean, p50, p90, p95, p999)", 5);
        assert_eq!(names, vec!["mean", "p50", "p90", "p95", "p999"]);
    }

    #[test]
    fn test_stat_names_5_with_p99() {
        // Description must contain "p99" but NOT contain "p95" at all.
        let names = stat_names("some metric (p99 included)", 5);
        assert_eq!(names, vec!["mean", "p50", "p90", "p99", "p999"]);
    }

    #[test]
    fn test_stat_names_4() {
        let names = stat_names("whatever", 4);
        assert_eq!(names, vec!["p50", "p90", "p95", "p999"]);
    }

    #[test]
    fn test_stat_names_fallback() {
        let names = stat_names("unknown format", 3);
        assert_eq!(names, vec!["stat0", "stat1", "stat2"]);
    }

    // ---- indexed_float ----

    #[test]
    fn test_indexed_float() {
        let mut out = Vec::new();
        indexed_float(
            &mut out,
            "tpu.{}.tensorcoreUtilization",
            &["42.5".into(), "bad".into(), "99.1".into()],
        );
        let m = metrics_map(&out);
        assert_eq!(m.get("tpu.0.tensorcoreUtilization"), Some(&42.5));
        assert!(!m.contains_key("tpu.1.tensorcoreUtilization"));
        assert_eq!(m.get("tpu.2.tensorcoreUtilization"), Some(&99.1));
    }

    // ---- labeled_dist ----

    #[test]
    fn test_labeled_dist() {
        let mut out = Vec::new();
        labeled_dist(
            &mut out,
            "tpu.hloExecTiming",
            "Us",
            "mean, p50, p90, p95, p999",
            &["program_main, 100.0, 50.0, 90.0, 95.0, 999.0".into()],
        );
        let m = metrics_map(&out);
        assert_eq!(m.get("tpu.hloExecTiming.program_main.meanUs"), Some(&100.0));
        assert_eq!(m.get("tpu.hloExecTiming.program_main.p50Us"), Some(&50.0));
        assert_eq!(m.get("tpu.hloExecTiming.program_main.p999Us"), Some(&999.0));
    }

    // ---- flat_dist ----

    #[test]
    fn test_flat_dist() {
        let mut out = Vec::new();
        flat_dist(
            &mut out,
            "tpu.grpcTcpMinRtt",
            "Us",
            "mean, p50, p90, p95, p999",
            &["10.0, 20.0, 30.0, 40.0, 50.0".into()],
        );
        let m = metrics_map(&out);
        assert_eq!(m.get("tpu.grpcTcpMinRtt.meanUs"), Some(&10.0));
        assert_eq!(m.get("tpu.grpcTcpMinRtt.p999Us"), Some(&50.0));
    }

    #[test]
    fn test_flat_dist_multiline() {
        let mut out = Vec::new();
        flat_dist(
            &mut out,
            "tpu.grpcTcpDeliveryRate",
            "Mbps",
            "p50, p90, p95, p999",
            &[
                "100.0".into(),
                "200.0".into(),
                "300.0".into(),
                "400.0".into(),
            ],
        );
        let m = metrics_map(&out);
        assert_eq!(m.get("tpu.grpcTcpDeliveryRate.p50Mbps"), Some(&100.0));
        assert_eq!(m.get("tpu.grpcTcpDeliveryRate.p999Mbps"), Some(&400.0));
    }

    // ---- colon_values ----

    #[test]
    fn test_colon_values() {
        let mut out = Vec::new();
        colon_values(
            &mut out,
            "tpu.hloQueueSize",
            &["tensor_core-0: 5".into(), "tensor_core-1: 12".into()],
        );
        let m = metrics_map(&out);
        assert_eq!(m.get("tpu.hloQueueSize.tensor_core_0"), Some(&5.0));
        assert_eq!(m.get("tpu.hloQueueSize.tensor_core_1"), Some(&12.0));
    }

    #[test]
    fn test_colon_values_no_colon() {
        let mut out = Vec::new();
        colon_values(&mut out, "tpu.x", &["42".into()]);
        let m = metrics_map(&out);
        assert_eq!(m.get("tpu.x.item_0"), Some(&42.0));
    }

    // ---- format_metric (SDK path integration) ----

    #[test]
    fn test_format_metric_tensorcore() {
        let data = SdkMetricData {
            description: String::new(),
            values: vec!["75.5".into(), "80.2".into()],
        };
        let mut out = Vec::new();
        format_metric("tensorcore_utilization", &data, &mut out);
        let m = metrics_map(&out);
        assert_eq!(m.get("tpu.0.tensorcoreUtilization"), Some(&75.5));
        assert_eq!(m.get("tpu.1.tensorcoreUtilization"), Some(&80.2));
    }

    #[test]
    fn test_format_metric_duty_cycle() {
        let data = SdkMetricData {
            description: String::new(),
            values: vec!["42.0".into()],
        };
        let mut out = Vec::new();
        format_metric("duty_cycle_pct", &data, &mut out);
        let m = metrics_map(&out);
        assert_eq!(m.get("tpu.0.dutyCycle"), Some(&42.0));
    }

    #[test]
    fn test_format_metric_hlo_queue() {
        let data = SdkMetricData {
            description: String::new(),
            values: vec!["tensor_core-0: 3".into(), "tensor_core-1: 7".into()],
        };
        let mut out = Vec::new();
        format_metric("hlo_queue_size", &data, &mut out);
        let m = metrics_map(&out);
        assert_eq!(m.get("tpu.hloQueueSize.tensor_core_0"), Some(&3.0));
        assert_eq!(m.get("tpu.hloQueueSize.tensor_core_1"), Some(&7.0));
    }

    // ---- distribution percentile calculation ----

    #[test]
    fn test_distribution_percentiles_exponential() {
        // 4 finite buckets, growth=2, scale=10
        // Boundaries: scale*g^1=20, scale*g^2=40, scale*g^3=80, scale*g^4=160
        //   => [20, 40, 80, 160]
        // 6 buckets total (underflow + 4 finite + overflow):
        //   idx 0: [0, 20)    count=0
        //   idx 1: [20, 40)   count=100   cumulative=100
        //   idx 2: [40, 80)   count=300   cumulative=400
        //   idx 3: [80, 160)  count=400   cumulative=800
        //   idx 4: [160,160)  count=150   cumulative=950 (overflow)
        //   idx 5: overflow   count=50    cumulative=1000
        let dist = proto::Distribution {
            count: 1000,
            mean: 50.0,
            min: 10.0,
            max: 200.0,
            sum_of_squared_deviation: 0.0,
            bucket_options: Some(proto::distribution::BucketOptions {
                options: Some(
                    proto::distribution::bucket_options::Options::ExponentialBuckets(
                        proto::distribution::bucket_options::Exponential {
                            num_finite_buckets: 4,
                            growth_factor: 2.0,
                            scale: 10.0,
                        },
                    ),
                ),
            }),
            bucket_counts: vec![0, 100, 300, 400, 150, 50],
        };

        let pcts = distribution_percentiles(&dist);
        let pct_map: HashMap<&str, f64> = pcts.into_iter().collect();

        // p50: target=500. cumulative: 0, 100, 400, 800>=500 at idx 3.
        // bucket 3 = [80, 160). prev=400, count=400, frac=(500-400)/400=0.25
        // value = 80 + 0.25*80 = 100
        assert!(
            (pct_map["p50"] - 100.0).abs() < 0.01,
            "p50={}",
            pct_map["p50"]
        );

        // p90: target=900. cumulative reaches 800 at idx 3, then 950 at idx 4.
        // bucket 4 is overflow [160,160). value=160
        assert!(pct_map["p90"] >= 80.0, "p90={}", pct_map["p90"]);

        for (name, val) in &pct_map {
            assert!(*val > 0.0, "{name} should be positive, got {val}");
        }
    }

    #[test]
    fn test_distribution_percentiles_linear() {
        // 3 finite buckets, width=10, offset=0
        // Boundaries: [10, 20, 30]  (offset + width*1, offset + width*2, offset + width*3)
        // 5 buckets: [0,10) [10,20) [20,30) [30,30) overflow
        //   idx 0: [0, 10)  count=10  cumulative=10
        //   idx 1: [10, 20) count=50  cumulative=60
        //   idx 2: [20, 30) count=30  cumulative=90
        //   idx 3: [30, 30) count=10  cumulative=100
        let dist = proto::Distribution {
            count: 100,
            mean: 15.0,
            min: 0.0,
            max: 35.0,
            sum_of_squared_deviation: 0.0,
            bucket_options: Some(proto::distribution::BucketOptions {
                options: Some(proto::distribution::bucket_options::Options::LinearBuckets(
                    proto::distribution::bucket_options::Linear {
                        num_finite_buckets: 3,
                        width: 10.0,
                        offset: 0.0,
                    },
                )),
            }),
            bucket_counts: vec![10, 50, 30, 10],
        };

        let pcts = distribution_percentiles(&dist);
        let pct_map: HashMap<&str, f64> = pcts.into_iter().collect();
        // p50: target=50. cumulative: 10, 60>=50 at idx 1.
        // bucket 1 = [10, 20). prev=10, count=50, frac=(50-10)/50=0.8
        // value = 10 + 0.8*10 = 18.0
        assert!(
            (pct_map["p50"] - 18.0).abs() < 0.01,
            "p50={}",
            pct_map["p50"]
        );
    }

    #[test]
    fn test_distribution_percentiles_empty() {
        let dist = proto::Distribution {
            count: 0,
            mean: 0.0,
            min: 0.0,
            max: 0.0,
            sum_of_squared_deviation: 0.0,
            bucket_options: None,
            bucket_counts: vec![],
        };
        assert!(distribution_percentiles(&dist).is_empty());
    }

    // ---- quantile_name ----

    #[test]
    fn test_quantile_name() {
        assert_eq!(quantile_name(0.50), Some("p50"));
        assert_eq!(quantile_name(0.90), Some("p90"));
        assert_eq!(quantile_name(0.95), Some("p95"));
        assert_eq!(quantile_name(0.99), Some("p99"));
        assert_eq!(quantile_name(0.999), Some("p999"));
        assert_eq!(quantile_name(0.75), None);
    }

    // ---- bucket_range ----

    #[test]
    fn test_bucket_range() {
        let bounds = vec![10.0, 20.0, 40.0];
        assert_eq!(bucket_range(&bounds, 0), (0.0, 10.0)); // underflow
        assert_eq!(bucket_range(&bounds, 1), (10.0, 20.0)); // first finite
        assert_eq!(bucket_range(&bounds, 2), (20.0, 40.0)); // second finite
        assert_eq!(bucket_range(&bounds, 3), (40.0, 40.0)); // last finite
        assert_eq!(bucket_range(&bounds, 4), (40.0, 40.0)); // overflow

        assert_eq!(bucket_range(&[], 0), (0.0, 0.0));
    }

    // ---- libtpu.so integration test ----
    //
    // Downloads libtpu from PyPI, extracts libtpu.so, loads it, and verifies
    // the vtable is functional. Marked #[ignore] — needs network + pip.
    //
    // To run manually:
    //   cargo test --verbose -- --include-ignored test_libtpu_sdk --nocapture

    #[test]
    #[ignore] // needs network + pip to download libtpu wheel from PyPI
    fn test_libtpu_sdk_load_and_create_client() {
        let libtpu_path = obtain_libtpu_so();
        // Safety: single-threaded test context.
        unsafe { std::env::set_var("WANDB_LIBTPU_PATH", &libtpu_path) };

        // Verify the library loads and GetLibtpuSdkApi works.
        let lib = unsafe { Library::new(&libtpu_path).expect("failed to dlopen libtpu.so") };

        let api_ptr: *const u8 = unsafe {
            let get_api: Symbol<unsafe extern "C" fn() -> *const u8> = lib
                .get(b"GetLibtpuSdkApi")
                .expect("GetLibtpuSdkApi symbol not found");
            get_api()
        };
        assert!(!api_ptr.is_null(), "GetLibtpuSdkApi returned NULL");

        // Verify header: h0=0, h1=1 (version tag).
        let h0 = unsafe { std::ptr::read(api_ptr as *const u32) };
        let h1 = unsafe { std::ptr::read(api_ptr.add(4) as *const u32) };
        assert_eq!(h0, 0, "vtable header h0 should be 0");
        assert_eq!(h1, 1, "vtable header h1 should be 1 (VERS_1.0)");

        // Verify all expected vtable slots are non-null.
        for (name, offset) in [
            ("ErrorMessage", OFF_ERROR_MESSAGE),
            ("DestroyError", OFF_DESTROY_ERROR),
            ("CreateClient", OFF_CREATE_CLIENT),
            ("DestroyClient", OFF_DESTROY_CLIENT),
            ("GetMetric", OFF_GET_METRIC),
            ("GetMetricDescription", OFF_GET_METRIC_DESC),
            ("GetMetricValues", OFF_GET_METRIC_VALS),
        ] {
            let fn_ptr = unsafe { vtable_fn(api_ptr, offset) };
            assert!(
                fn_ptr as usize != 0,
                "vtable slot {name} at offset {offset:#x} is NULL"
            );
        }

        // CreateClient — should succeed even without a TPU.
        #[repr(C)]
        struct CreateClientArgs {
            client: *mut std::ffi::c_void,
        }
        let client = unsafe {
            let mut args = CreateClientArgs {
                client: std::ptr::null_mut(),
            };
            let err =
                vtable_fn(api_ptr, OFF_CREATE_CLIENT)((&raw mut args) as *mut std::ffi::c_void);
            assert!(err.is_null(), "CreateClient returned error");
            assert!(!args.client.is_null(), "CreateClient returned null client");
            args.client
        };

        // GetMetric with a known metric name — should return a handle
        // (description will resolve; values may be empty without a workload).
        let cname = CString::new("duty_cycle_pct").unwrap();

        #[repr(C)]
        struct GetMetricArgs {
            client: *mut std::ffi::c_void,
            metric_name: *const c_char,
            metric: *mut std::ffi::c_void,
        }

        let metric = unsafe {
            let mut args = GetMetricArgs {
                client,
                metric_name: cname.as_ptr(),
                metric: std::ptr::null_mut(),
            };
            let err = vtable_fn(api_ptr, OFF_GET_METRIC)((&raw mut args) as *mut std::ffi::c_void);
            assert!(err.is_null(), "GetMetric(duty_cycle_pct) returned error");
            assert!(
                !args.metric.is_null(),
                "GetMetric(duty_cycle_pct) returned null handle"
            );
            args.metric
        };

        // GetMetricDescription — should return a non-empty description.
        #[repr(C)]
        struct GetDescArgs {
            metric: *mut std::ffi::c_void,
            description: *const c_char,
            description_len: usize,
        }
        unsafe {
            let mut args = GetDescArgs {
                metric,
                description: std::ptr::null(),
                description_len: 0,
            };
            let err =
                vtable_fn(api_ptr, OFF_GET_METRIC_DESC)((&raw mut args) as *mut std::ffi::c_void);
            assert!(err.is_null(), "GetMetricDescription returned error");
            assert!(
                args.description_len > 0,
                "GetMetricDescription returned empty description"
            );
            let desc =
                std::slice::from_raw_parts(args.description as *const u8, args.description_len);
            let desc_str = std::str::from_utf8(desc).unwrap();
            assert!(
                desc_str.contains("duty") || desc_str.contains("active"),
                "unexpected description: {desc_str}"
            );
        }

        // Cleanup.
        #[repr(C)]
        struct DestroyArgs {
            client: *mut std::ffi::c_void,
        }
        unsafe {
            let mut args = DestroyArgs { client };
            vtable_fn(api_ptr, OFF_DESTROY_CLIENT)((&raw mut args) as *mut std::ffi::c_void);
        }
    }

    /// Downloads the libtpu wheel from PyPI, extracts libtpu.so, returns its path.
    fn obtain_libtpu_so() -> PathBuf {
        // Check if already provided via env.
        if let Ok(path) = std::env::var("WANDB_LIBTPU_PATH") {
            let p = PathBuf::from(path.trim());
            if p.is_file() {
                return p;
            }
        }

        let cache_dir = PathBuf::from(
            std::env::var("WANDB_TEST_LIBTPU_CACHE")
                .unwrap_or_else(|_| "/tmp/wandb-libtpu-test".into()),
        );
        let libtpu_path = cache_dir.join("libtpu.so");
        if libtpu_path.is_file() {
            return libtpu_path;
        }

        eprintln!("Downloading libtpu wheel from PyPI...");
        std::fs::create_dir_all(&cache_dir).expect("failed to create cache dir");

        // Use pip download to get the wheel.
        // Try pip3 first, then pip.
        let pip = ["pip3", "pip"]
            .iter()
            .copied()
            .find(|cmd| {
                std::process::Command::new(cmd)
                    .arg("--version")
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .status()
                    .is_ok()
            })
            .expect("neither pip3 nor pip found in PATH — install Python to run this test");
        let status = std::process::Command::new(pip)
            .args([
                "download",
                "--no-deps",
                "--dest",
                cache_dir.to_str().unwrap(),
                "--only-binary=:all:",
                "--platform=manylinux_2_31_x86_64",
                "--python-version=3.12",
                "--implementation=cp",
                "libtpu",
            ])
            .status()
            .expect("failed to run pip download");
        assert!(status.success(), "pip download libtpu failed");

        // Find the wheel.
        let wheel = std::fs::read_dir(&cache_dir)
            .unwrap()
            .filter_map(|e| e.ok())
            .find(|e| {
                e.file_name()
                    .to_str()
                    .is_some_and(|n| n.starts_with("libtpu") && n.ends_with(".whl"))
            })
            .expect("libtpu wheel not found after download");

        // Extract libtpu.so from the wheel (it's a zip file).
        eprintln!(
            "Extracting libtpu.so from {}...",
            wheel.file_name().to_string_lossy()
        );
        let file = std::fs::File::open(wheel.path()).unwrap();
        let mut archive = zip::ZipArchive::new(file).unwrap();
        for i in 0..archive.len() {
            let mut entry = archive.by_index(i).unwrap();
            if entry.name().ends_with("libtpu.so") {
                let mut out = std::fs::File::create(&libtpu_path).unwrap();
                std::io::copy(&mut entry, &mut out).unwrap();
                eprintln!("Extracted to {}", libtpu_path.display());
                return libtpu_path;
            }
        }

        panic!("libtpu.so not found in wheel");
    }
}

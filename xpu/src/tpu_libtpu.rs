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
use crate::wandb_internal::{EnvironmentRecord, TpuInfo};

use async_trait::async_trait;
use libloading::{Library, Symbol};
use log::{debug, warn};
use std::collections::HashMap;
use std::ffi::{CStr, CString, c_void};
use std::fs;
use std::net::{SocketAddr, TcpStream};
use std::os::raw::c_char;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};
use std::time::Duration;
use tonic::transport::{Channel, Endpoint};

// ============================================================
// Public monitor — orchestrates SDK + gRPC
// ============================================================

pub struct TpuMonitor {
    sdk: Option<Mutex<SdkClient>>,
    grpc: Mutex<Option<GrpcClient>>,
    chip: TpuChip,
    chip_count: u32,
}

fn lock_or_recover<'a, T>(mutex: &'a Mutex<T>, name: &str) -> MutexGuard<'a, T> {
    match mutex.lock() {
        Ok(guard) => guard,
        Err(poisoned) => {
            warn!("{name} mutex was poisoned; recovering");
            poisoned.into_inner()
        }
    }
}

impl TpuMonitor {
    pub fn new() -> Option<Self> {
        let (chip, chip_count) = detect_local_tpu_chips();
        if chip_count == 0 {
            debug!("TPU: no TPU chips detected via PCI scan");
            return None;
        }
        debug!(
            "TPU: detected {} x {} ({}GiB HBM, {} devices/chip)",
            chip_count, chip.name, chip.hbm_gib, chip.devices_per_chip
        );

        let sdk = SdkClient::new().map(Mutex::new);
        let grpc_available = is_grpc_available_now();

        if sdk.is_some() {
            debug!("TPU: libtpu SDK client initialized");
        }
        if grpc_available {
            debug!("TPU: gRPC runtime service available on 127.0.0.1:8431");
        }

        Some(Self {
            sdk,
            grpc: Mutex::new(None),
            chip,
            chip_count,
        })
    }

    async fn collect_tpu_metrics(&self) -> Vec<(String, MetricValue)> {
        let mut metrics = Vec::new();
        let mut sdk_failures = Vec::new();

        // Phase 1: collect everything we can from the SDK.
        if let Some(sdk) = &self.sdk {
            let mut sdk = lock_or_recover(sdk, "tpu sdk");
            for desired in DESIRED_METRICS {
                if let Some(actual_name) = sdk.resolve_metric_name(desired) {
                    match sdk.read_metric(&actual_name) {
                        Ok(data) => {
                            let before = metrics.len();
                            format_metric(
                                desired.logical_name,
                                &data,
                                self.chip.devices_per_chip,
                                &mut metrics,
                            );
                            if metrics.len() > before {
                                continue;
                            }
                            // SDK returned data but formatting produced nothing —
                            // fall through to gRPC.
                            debug!(
                                "TPU SDK {}: got {} values but none parsed, falling back to gRPC. \
                                 desc={:?} values={:?}",
                                desired.logical_name,
                                data.values.len(),
                                data.description,
                                data.values,
                            );
                        }
                        Err(e) => {
                            debug!("TPU SDK {}: {e}", desired.logical_name);
                        }
                    }
                }
                sdk_failures.push(desired.logical_name);
            }
        } else {
            sdk_failures.extend(DESIRED_METRICS.iter().map(|d| d.logical_name));
        }

        // Phase 2: fill gaps from gRPC.
        if !sdk_failures.is_empty() && is_grpc_available().await {
            let grpc = self.get_grpc_client();
            for logical_name in sdk_failures {
                let Some(grpc_name) = GRPC_METRIC_MAP.get(logical_name) else {
                    continue;
                };
                match grpc.get_metric(grpc_name).await {
                    Ok(tpu_metric) => {
                        format_grpc_metric(
                            logical_name,
                            &tpu_metric,
                            self.chip.devices_per_chip,
                            &mut metrics,
                        );
                    }
                    Err(e) => {
                        debug!("TPU gRPC {logical_name}: {e}");
                    }
                }
            }
        }

        // Compute HBM memory usage percentage from total and usage.
        compute_hbm_percentage(&mut metrics);

        metrics
    }

    fn get_grpc_client(&self) -> GrpcClient {
        let mut guard = lock_or_recover(&self.grpc, "tpu grpc");
        guard.get_or_insert_with(GrpcClient::new).clone()
    }
}

#[async_trait]
impl GpuMonitor for TpuMonitor {
    async fn collect_metrics(
        &self,
        _pid: i32,
        _gpu_device_ids: Option<Vec<i32>>,
    ) -> Result<Vec<(String, MetricValue)>, Box<dyn std::error::Error>> {
        Ok(self.collect_tpu_metrics().await)
    }

    async fn collect_metadata(
        &self,
        _samples: &HashMap<String, &MetricValue>,
    ) -> EnvironmentRecord {
        EnvironmentRecord {
            tpu: Some(TpuInfo {
                name: self.chip.name.clone(),
                hbm_gib: self.chip.hbm_gib,
                devices_per_chip: self.chip.devices_per_chip,
                count: self.chip_count,
            }),
            ..Default::default()
        }
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
        sdk_aliases: &["tcp_min_rtt", "grpc_tcp_min_rtt", "grpc_tcp_min_round_trip_times"],
    },
    DesiredMetric {
        logical_name: "grpc_tcp_delivery_rate",
        sdk_aliases: &["tcp_delivery_rate", "grpc_tcp_delivery_rate", "grpc_tcp_delivery_rates"],
    },
    DesiredMetric {
        logical_name: "hlo_exec_timing",
        sdk_aliases: &["hlo_execution_timing", "hlo_exec_timing"],
    },
    DesiredMetric {
        logical_name: "hlo_queue_size",
        sdk_aliases: &["hlo_queue_size"],
    },
    DesiredMetric {
        logical_name: "ici_link_health",
        sdk_aliases: &["ici_link_health"],
    },
    DesiredMetric {
        logical_name: "tpu_throttle_score",
        sdk_aliases: &["tpu_throttle_score"],
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
// Verified against libtpu 0.0.38 (VERS_1.0 ABI).
const OFF_ERROR_MESSAGE: usize = 0x08;
const OFF_DESTROY_ERROR: usize = 0x10;
const OFF_CREATE_CLIENT: usize = 0x20;
const OFF_DESTROY_CLIENT: usize = 0x28;
const OFF_GET_METRIC: usize = 0x50;
const OFF_GET_METRIC_DESC: usize = 0x58;
const OFF_GET_METRIC_VALS: usize = 0x60;

const SDK_API_HEADER_0: u32 = 0;
const SDK_API_HEADER_1: u32 = 1;
const MAX_SDK_STRING_LEN: usize = 64 * 1024;
const MAX_SDK_VALUE_COUNT: usize = 4096;
const REQUIRED_VTABLE_SLOTS: &[(&str, usize)] = &[
    ("ErrorMessage", OFF_ERROR_MESSAGE),
    ("DestroyError", OFF_DESTROY_ERROR),
    ("CreateClient", OFF_CREATE_CLIENT),
    ("DestroyClient", OFF_DESTROY_CLIENT),
    ("GetMetric", OFF_GET_METRIC),
    ("GetMetricDescription", OFF_GET_METRIC_DESC),
    ("GetMetricValues", OFF_GET_METRIC_VALS),
];

type RawApiFn = *const ();
type ApiFn = unsafe extern "C" fn(*mut c_void) -> *mut c_void;

unsafe fn read_vtable_slot(api: *const u8, offset: usize) -> RawApiFn {
    unsafe { std::ptr::read_unaligned(api.add(offset) as *const RawApiFn) }
}

unsafe fn validate_api(api: *const u8) -> Result<(), String> {
    if api.is_null() {
        return Err("GetLibtpuSdkApi() returned NULL".to_string());
    }

    let h0 = unsafe { std::ptr::read_unaligned(api as *const u32) };
    let h1 = unsafe { std::ptr::read_unaligned(api.add(4) as *const u32) };
    if h0 != SDK_API_HEADER_0 || h1 != SDK_API_HEADER_1 {
        return Err(format!(
            "unexpected LibtpuSdkApi header: h0={h0}, h1={h1}, expected 0/1"
        ));
    }

    for (name, offset) in REQUIRED_VTABLE_SLOTS {
        if unsafe { read_vtable_slot(api, *offset) }.is_null() {
            return Err(format!(
                "required libtpu slot {name} at offset {offset:#x} was NULL"
            ));
        }
    }

    Ok(())
}

unsafe fn vtable_fn(api: *const u8, offset: usize) -> ApiFn {
    let slot = unsafe { read_vtable_slot(api, offset) };
    debug_assert!(
        !slot.is_null(),
        "validated libtpu slot at {offset:#x} was NULL"
    );
    unsafe { std::mem::transmute::<RawApiFn, ApiFn>(slot) }
}

struct SdkMetricData {
    description: String,
    values: Vec<String>,
}

struct SdkClient {
    _lib: Library,
    api_ptr: *const u8,
    client: *mut c_void,
    resolved: HashMap<String, String>,
}

// SAFETY: `SdkClient` owns a libloading handle and an opaque SDK client pointer.
// Access is serialized by `TpuMonitor`'s outer `Mutex`, so moving it across
// threads is acceptable, but shared unsynchronized access is not.
unsafe impl Send for SdkClient {}

impl SdkClient {
    fn new() -> Option<Self> {
        let Some(path) = find_libtpu_path() else {
            debug!("TPU: libtpu.so not found in standard locations");
            return None;
        };

        match Self::try_new(&path) {
            Ok(client) => Some(client),
            Err(e) => {
                warn!("TPU: {e}");
                None
            }
        }
    }

    fn try_new(path: &Path) -> Result<Self, String> {
        debug!("Loading libtpu from: {}", path.display());

        let lib = unsafe { Library::new(path) }
            .map_err(|e| format!("failed to load {}: {e}", path.display()))?;
        let api_ptr: *const u8 = unsafe {
            let get_api: Symbol<unsafe extern "C" fn() -> *const u8> =
                lib.get(b"GetLibtpuSdkApi").map_err(|e| {
                    format!(
                        "failed to resolve GetLibtpuSdkApi in {}: {e}",
                        path.display()
                    )
                })?;
            get_api()
        };
        unsafe { validate_api(api_ptr) }
            .map_err(|e| format!("invalid libtpu SDK API from {}: {e}", path.display()))?;

        #[repr(C)]
        struct CreateClientArgs {
            client: *mut c_void,
        }

        let client = unsafe {
            let mut args = CreateClientArgs {
                client: std::ptr::null_mut(),
            };
            let err = vtable_fn(api_ptr, OFF_CREATE_CLIENT)((&raw mut args) as *mut c_void);
            if !err.is_null() {
                return Err(format!(
                    "libtpu CreateClient failed: {}",
                    read_error(api_ptr, err)
                ));
            }
            args.client
        };
        if client.is_null() {
            return Err("libtpu CreateClient returned a null client".to_string());
        }

        Ok(Self {
            _lib: lib,
            api_ptr,
            client,
            resolved: HashMap::new(),
        })
    }

    fn resolve_metric_name(&mut self, desired: &DesiredMetric) -> Option<String> {
        if let Some(resolved) = self.resolved.get(desired.logical_name) {
            return Some(resolved.clone());
        }

        for alias in desired.sdk_aliases {
            if self.read_metric(alias).is_ok() {
                let alias = (*alias).to_string();
                self.resolved
                    .insert(desired.logical_name.to_string(), alias.clone());
                return Some(alias);
            }
        }

        None
    }

    fn read_metric(&self, name: &str) -> Result<SdkMetricData, String> {
        let cname = CString::new(name).map_err(|e| e.to_string())?;

        #[repr(C)]
        struct GetMetricArgs {
            client: *mut c_void,
            metric_name: *const c_char,
            metric: *mut c_void,
        }

        let metric = unsafe {
            let mut args = GetMetricArgs {
                client: self.client,
                metric_name: cname.as_ptr(),
                metric: std::ptr::null_mut(),
            };
            let err = vtable_fn(self.api_ptr, OFF_GET_METRIC)((&raw mut args) as *mut c_void);
            if !err.is_null() {
                return Err(read_error(self.api_ptr, err));
            }
            if args.metric.is_null() {
                return Err(format!("GetMetric({name}) returned a null handle"));
            }
            args.metric
        };

        #[repr(C)]
        struct GetDescArgs {
            metric: *mut c_void,
            description: *const c_char,
            description_len: usize,
        }

        let description = unsafe {
            let mut args = GetDescArgs {
                metric,
                description: std::ptr::null(),
                description_len: 0,
            };
            let err = vtable_fn(self.api_ptr, OFF_GET_METRIC_DESC)((&raw mut args) as *mut c_void);
            if !err.is_null() {
                return Err(read_error(self.api_ptr, err));
            }
            if args.description_len > MAX_SDK_STRING_LEN {
                return Err(format!(
                    "GetMetricDescription({name}) returned {} bytes, over the {} byte cap",
                    args.description_len, MAX_SDK_STRING_LEN
                ));
            }
            if args.description_len == 0 {
                String::new()
            } else if args.description.is_null() {
                return Err(format!(
                    "GetMetricDescription({name}) returned a null description with len {}",
                    args.description_len
                ));
            } else {
                let slice =
                    std::slice::from_raw_parts(args.description as *const u8, args.description_len);
                String::from_utf8_lossy(slice).into_owned()
            }
        };

        #[repr(C)]
        struct GetValsArgs {
            metric: *mut c_void,
            values: *const *const c_char,
            value_count: usize,
        }

        let values = unsafe {
            let mut args = GetValsArgs {
                metric,
                values: std::ptr::null(),
                value_count: 0,
            };
            let err = vtable_fn(self.api_ptr, OFF_GET_METRIC_VALS)((&raw mut args) as *mut c_void);
            if !err.is_null() {
                return Err(read_error(self.api_ptr, err));
            }
            if args.value_count > MAX_SDK_VALUE_COUNT {
                return Err(format!(
                    "GetMetricValues({name}) returned {} values, over the {} value cap",
                    args.value_count, MAX_SDK_VALUE_COUNT
                ));
            }
            if args.value_count > 0 && args.values.is_null() {
                return Err(format!(
                    "GetMetricValues({name}) returned a null values pointer with count {}",
                    args.value_count
                ));
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
        if self.client.is_null() {
            return;
        }

        #[repr(C)]
        struct DestroyClientArgs {
            client: *mut c_void,
        }

        let err = unsafe {
            let mut args = DestroyClientArgs {
                client: self.client,
            };
            vtable_fn(self.api_ptr, OFF_DESTROY_CLIENT)((&raw mut args) as *mut c_void)
        };
        if !err.is_null() {
            debug!("libtpu DestroyClient failed: {}", unsafe {
                read_error(self.api_ptr, err)
            });
        }
    }
}

#[repr(C)]
struct ErrorMessageArgs {
    error: *mut c_void,
    message: *const c_char,
    message_len: usize,
}

#[repr(C)]
struct DestroyErrorArgs {
    error: *mut c_void,
}

unsafe fn read_error(api_ptr: *const u8, err: *mut c_void) -> String {
    let mut msg_args = ErrorMessageArgs {
        error: err,
        message: std::ptr::null(),
        message_len: 0,
    };
    unsafe { vtable_fn(api_ptr, OFF_ERROR_MESSAGE)((&raw mut msg_args) as *mut c_void) };
    let msg = if !msg_args.message.is_null() && msg_args.message_len > 0 {
        let len = msg_args.message_len.min(MAX_SDK_STRING_LEN);
        if msg_args.message_len > MAX_SDK_STRING_LEN {
            warn!(
                "libtpu error message was truncated from {} to {} bytes",
                msg_args.message_len, len
            );
        }
        let s = unsafe { std::slice::from_raw_parts(msg_args.message as *const u8, len) };
        String::from_utf8_lossy(s).into_owned()
    } else {
        "unknown error".to_string()
    };
    let mut d = DestroyErrorArgs { error: err };
    unsafe { vtable_fn(api_ptr, OFF_DESTROY_ERROR)((&raw mut d) as *mut c_void) };
    msg
}

// ============================================================
// gRPC client — localhost:8431 fallback
// ============================================================

const GRPC_ADDR: &str = "http://127.0.0.1:8431";
const GRPC_PROBE_TIMEOUT: Duration = Duration::from_millis(100);
const GRPC_CONNECT_TIMEOUT: Duration = Duration::from_millis(250);
const GRPC_REQUEST_TIMEOUT: Duration = Duration::from_millis(500);

fn grpc_socket_addr() -> SocketAddr {
    SocketAddr::from(([127, 0, 0, 1], 8431))
}

#[derive(Clone)]
struct GrpcClient {
    client: proto::runtime_metric_service_client::RuntimeMetricServiceClient<Channel>,
}

impl GrpcClient {
    fn new() -> Self {
        let channel = Endpoint::from_static(GRPC_ADDR)
            .connect_timeout(GRPC_CONNECT_TIMEOUT)
            .timeout(GRPC_REQUEST_TIMEOUT)
            .connect_lazy();
        Self {
            client: proto::runtime_metric_service_client::RuntimeMetricServiceClient::new(channel),
        }
    }

    async fn get_metric(&self, metric_name: &str) -> Result<proto::TpuMetric, String> {
        let mut client = self.client.clone();
        let mut request = tonic::Request::new(proto::MetricRequest {
            metric_name: metric_name.to_string(),
            skip_node_aggregation: false,
        });
        request.set_timeout(GRPC_REQUEST_TIMEOUT);
        let resp = client
            .get_runtime_metric(request)
            .await
            .map_err(|e| e.to_string())?;
        resp.into_inner()
            .metric
            .ok_or_else(|| format!("metric {metric_name} returned an empty response"))
    }
}

fn is_grpc_available_now() -> bool {
    TcpStream::connect_timeout(&grpc_socket_addr(), GRPC_PROBE_TIMEOUT).is_ok()
}

async fn is_grpc_available() -> bool {
    match tokio::time::timeout(
        GRPC_PROBE_TIMEOUT,
        tokio::net::TcpStream::connect(grpc_socket_addr()),
    )
    .await
    {
        Ok(Ok(_)) => true,
        Ok(Err(_)) | Err(_) => false,
    }
}

// ============================================================
// Metric formatting — SDK path
// ============================================================

fn format_metric(
    logical_name: &str,
    data: &SdkMetricData,
    devices_per_chip: u32,
    out: &mut Vec<(String, MetricValue)>,
) {
    match logical_name {
        "tensorcore_utilization" => {
            indexed_float(out, "tpu.{}.tensorcoreUtilization", &data.values)
        }
        "duty_cycle_pct" => {
            indexed_float_fanout(out, "tpu.{}.dutyCycle", &data.values, devices_per_chip)
        }
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
        "ici_link_health" => indexed_float(out, "tpu.{}.iciLinkHealth", &data.values),
        "tpu_throttle_score" => indexed_float(out, "tpu.{}.throttleScore", &data.values),
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

/// Like `indexed_float`, but fans out per-chip values to per-device entries.
/// On v2/v3/v7x (2 devices per chip), chip 0 → devices 0,1; chip 1 → devices 2,3.
/// On v4+ (1 device per chip), this is equivalent to `indexed_float`.
fn indexed_float_fanout(
    out: &mut Vec<(String, MetricValue)>,
    pattern: &str,
    values: &[String],
    devices_per_chip: u32,
) {
    let dpc = devices_per_chip.max(1) as usize;
    for (chip_idx, raw) in values.iter().enumerate() {
        if let Ok(v) = raw.trim().parse::<f64>() {
            for d in 0..dpc {
                let device_idx = chip_idx * dpc + d;
                out.push((
                    pattern.replace("{}", &device_idx.to_string()),
                    MetricValue::Float(v),
                ));
            }
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
    devices_per_chip: u32,
    out: &mut Vec<(String, MetricValue)>,
) {
    let dpc = devices_per_chip.max(1) as i64;
    let base_key = match logical_name {
        "duty_cycle_pct" | "hbm_capacity_total" | "hbm_capacity_usage" => {
            for m in &tpu_metric.metrics {
                let chip_id = grpc_device_id(m);
                if let Some(v) = grpc_gauge_value(m) {
                    let metric_suffix = match logical_name {
                        "duty_cycle_pct" => "dutyCycle",
                        "hbm_capacity_total" => "hbmCapacityTotal",
                        "hbm_capacity_usage" => "hbmCapacityUsage",
                        _ => continue,
                    };
                    // Fan out per-chip values to per-device on v2/v3/v7x.
                    for d in 0..dpc {
                        let device_id = chip_id * dpc + d;
                        out.push((
                            format!("tpu.{device_id}.{metric_suffix}"),
                            MetricValue::Float(v),
                        ));
                    }
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
            let last = bounds.last().copied().unwrap_or(0.0);
            (last, last)
        }
    }
}

// ============================================================
// Derived metrics
// ============================================================

fn compute_hbm_percentage(metrics: &mut Vec<(String, MetricValue)>) {
    // Collect per-device total and usage, keyed by device index.
    let mut totals: HashMap<String, f64> = HashMap::new();
    let mut usages: HashMap<String, f64> = HashMap::new();

    for (key, val) in metrics.iter() {
        let MetricValue::Float(v) = val else { continue };
        if let Some(idx) = key
            .strip_prefix("tpu.")
            .and_then(|s| s.strip_suffix(".hbmCapacityTotal"))
        {
            totals.insert(idx.to_string(), *v);
        } else if let Some(idx) = key
            .strip_prefix("tpu.")
            .and_then(|s| s.strip_suffix(".hbmCapacityUsage"))
        {
            usages.insert(idx.to_string(), *v);
        }
    }

    for (idx, total) in &totals {
        if let Some(usage) = usages.get(idx) {
            if *total > 0.0 {
                metrics.push((
                    format!("tpu.{idx}.hbmMemoryUsage"),
                    MetricValue::Float(usage / total * 100.0),
                ));
            }
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
// TPU chip detection via PCI scan
// ============================================================

/// Google's PCI vendor ID for TPU devices.
const GOOGLE_TPU_VENDOR_ID: &str = "0x1ae0";

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct TpuChip {
    name: String,
    hbm_gib: u32,
    devices_per_chip: u32,
}

impl Default for TpuChip {
    fn default() -> Self {
        Self {
            name: String::new(),
            hbm_gib: 0,
            devices_per_chip: 1,
        }
    }
}

fn tpu_chip_from_pci_ids(device_id: &str, subsystem_id: &str) -> Option<TpuChip> {
    match device_id {
        "0x0027" => match subsystem_id {
            "0x004e" => Some(TpuChip { name: "v2".into(), hbm_gib: 8, devices_per_chip: 2 }),
            "0x004f" => Some(TpuChip { name: "v3".into(), hbm_gib: 16, devices_per_chip: 2 }),
            _ => None,
        },
        "0x005e" => Some(TpuChip { name: "v4".into(), hbm_gib: 32, devices_per_chip: 1 }),
        "0x0063" => Some(TpuChip { name: "v5e".into(), hbm_gib: 16, devices_per_chip: 1 }),
        "0x0062" => Some(TpuChip { name: "v5p".into(), hbm_gib: 95, devices_per_chip: 1 }),
        "0x006f" => Some(TpuChip { name: "v6e".into(), hbm_gib: 32, devices_per_chip: 1 }),
        "0x0076" => Some(TpuChip { name: "7x".into(), hbm_gib: 192, devices_per_chip: 2 }),
        _ => None,
    }
}

/// Scans PCI devices for Google TPU chips. Returns the most common chip type and count.
fn detect_local_tpu_chips() -> (TpuChip, u32) {
    let entries = match fs::read_dir("/sys/bus/pci/devices") {
        Ok(e) => e,
        Err(_) => return (TpuChip::default(), 0),
    };

    let mut counter: HashMap<TpuChip, u32> = HashMap::new();

    for entry in entries.flatten() {
        let pci_path = entry.path();

        let vendor = match read_pci_attr(&pci_path, "vendor") {
            Some(v) => v,
            None => continue,
        };
        if vendor != GOOGLE_TPU_VENDOR_ID {
            continue;
        }

        let device_id = match read_pci_attr(&pci_path, "device") {
            Some(v) => v,
            None => continue,
        };
        let subsystem_id = read_pci_attr(&pci_path, "subsystem_device").unwrap_or_default();

        if let Some(chip) = tpu_chip_from_pci_ids(&device_id, &subsystem_id) {
            *counter.entry(chip).or_insert(0) += 1;
        }
    }

    counter
        .into_iter()
        .max_by_key(|(_, count)| *count)
        .unwrap_or((TpuChip::default(), 0))
}

fn read_pci_attr(pci_path: &Path, attr: &str) -> Option<String> {
    fs::read_to_string(pci_path.join(attr))
        .ok()
        .map(|s| s.trim().to_string())
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

    // ---- TPU chip detection ----

    #[test]
    fn test_tpu_chip_from_pci_ids() {
        let v3 = tpu_chip_from_pci_ids("0x0027", "0x004f").unwrap();
        assert_eq!(v3.name, "v3");
        assert_eq!(v3.hbm_gib, 16);
        assert_eq!(v3.devices_per_chip, 2);

        let v5e = tpu_chip_from_pci_ids("0x0063", "").unwrap();
        assert_eq!(v5e.name, "v5e");
        assert_eq!(v5e.devices_per_chip, 1);

        let v7x = tpu_chip_from_pci_ids("0x0076", "").unwrap();
        assert_eq!(v7x.name, "7x");
        assert_eq!(v7x.devices_per_chip, 2);

        assert!(tpu_chip_from_pci_ids("0xffff", "").is_none());
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
        format_metric("tensorcore_utilization", &data, 1, &mut out);
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
        // v4+ (1 device per chip)
        format_metric("duty_cycle_pct", &data, 1, &mut out);
        let m = metrics_map(&out);
        assert_eq!(m.get("tpu.0.dutyCycle"), Some(&42.0));
    }

    #[test]
    fn test_format_metric_duty_cycle_fanout() {
        let data = SdkMetricData {
            description: String::new(),
            values: vec!["42.0".into(), "80.0".into()],
        };
        let mut out = Vec::new();
        // v3 (2 devices per chip): chip 0 → devices 0,1; chip 1 → devices 2,3
        format_metric("duty_cycle_pct", &data, 2, &mut out);
        let m = metrics_map(&out);
        assert_eq!(m.get("tpu.0.dutyCycle"), Some(&42.0));
        assert_eq!(m.get("tpu.1.dutyCycle"), Some(&42.0));
        assert_eq!(m.get("tpu.2.dutyCycle"), Some(&80.0));
        assert_eq!(m.get("tpu.3.dutyCycle"), Some(&80.0));
    }

    #[test]
    fn test_format_metric_hlo_queue() {
        let data = SdkMetricData {
            description: String::new(),
            values: vec!["tensor_core-0: 3".into(), "tensor_core-1: 7".into()],
        };
        let mut out = Vec::new();
        format_metric("hlo_queue_size", &data, 1, &mut out);
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

    // ---- libtpu.so integration tests ----
    //
    // test_libtpu_sdk_vtable: Downloads libtpu from PyPI, validates the
    // vtable header and slot pointers. Safe to run anywhere (no TPU needed).
    // Needs network + pip.
    //
    // test_libtpu_sdk_create_client: Actually calls CreateClient/GetMetric.
    // Requires TPU hardware — CreateClient segfaults without the GCP
    // metadata service. Only run on TPU VMs.
    //
    // To run:
    //   cargo test -- --include-ignored test_libtpu_sdk_vtable --nocapture
    //   # On a TPU VM only:
    //   cargo test -- --include-ignored test_libtpu_sdk_create_client --nocapture

    #[test]
    #[ignore] // needs network + pip to download libtpu wheel from PyPI
    fn test_libtpu_sdk_vtable() {
        let libtpu_path = obtain_libtpu_so();

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
        for (name, offset) in REQUIRED_VTABLE_SLOTS {
            let slot = unsafe { read_vtable_slot(api_ptr, *offset) };
            assert!(
                !slot.is_null(),
                "vtable slot {name} at offset {offset:#x} is NULL"
            );
        }

        // Full validation should also pass.
        unsafe { validate_api(api_ptr) }.expect("validate_api failed");
    }

    #[test]
    #[ignore] // needs TPU hardware — CreateClient segfaults without GCP metadata service
    fn test_libtpu_sdk_create_client() {
        let libtpu_path = obtain_libtpu_so();
        // Safety: single-threaded test context.
        unsafe { std::env::set_var("WANDB_LIBTPU_PATH", &libtpu_path) };

        let lib = unsafe { Library::new(&libtpu_path).expect("failed to dlopen libtpu.so") };
        let api_ptr: *const u8 = unsafe {
            let get_api: Symbol<unsafe extern "C" fn() -> *const u8> = lib
                .get(b"GetLibtpuSdkApi")
                .expect("GetLibtpuSdkApi symbol not found");
            get_api()
        };
        unsafe { validate_api(api_ptr) }.expect("validate_api failed");

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

        // GetMetric with a known metric name.
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

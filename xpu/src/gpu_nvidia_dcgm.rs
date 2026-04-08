//! DCGM Interaction for NVIDIA GPU Profiling Metrics.
//!
//! This module handles loading the DCGM (NVIDIA Data Center GPU Manager) library,
//! interacting with its C API via FFI, and providing a safe interface
//! (`DcgmClient`) to collect GPU profiling metrics (`DCGM_FI_PROF_*` fields).
//!
//! It spawns a dedicated worker thread to manage the DCGM library handle and
//! perform blocking FFI calls, communicating with the main application via channels.
//!
//! Refer to https://github.com/nvidia/dcgm for the DCGM C API documentation.
use libloading::{Library, Symbol};
use std::{
    collections::HashSet,
    ffi::{c_char, c_int, c_void, CStr, CString},
    ptr,
    sync::mpsc::{self, Receiver as SyncReceiver, SyncSender},
    thread,
};
use tokio::sync::oneshot;

use crate::metrics::MetricValue;

// --- DCGM Constants ---

/// DCGM API ops status codes.
const DCGM_ST_OK: i32 = 0;
const DCGM_ST_NO_DATA: i32 = -35;
const DCGM_ST_NOT_SUPPORTED: i32 = -14;
const DCGM_ST_NOT_CONFIGURED: i32 = -8;

/// Maximum length for various DCGM strings.
const DCGM_MAX_STR_LENGTH: usize = 256;
/// Maximum number of field IDs allowed in a single field group.
const DCGM_MAX_FIELD_IDS_PER_FIELD_GROUP: usize = 128;
/// Maximum number of metric groups returned by `dcgmProfGetSupportedMetricGroups`. See `dcgm_structs.h`.
const DCGM_PROF_MAX_NUM_GROUPS_V2: usize = 10;
/// Maximum number of field IDs within a single profiling metric group.
const DCGM_PROF_MAX_FIELD_IDS_PER_GROUP_V2: usize = 64;

/// DCGM Field Entity types.
/// Represents a physical GPU entity.
const DCGM_FE_GPU: u32 = 0;
/// Represents a virtual GPU (vGPU) entity.
const DCGM_FE_VGPU: u32 = 1;

/// DCGM Field Value types.
const DCGM_FT_DOUBLE: u32 = 0;
const DCGM_FT_INT64: u32 = 1;
const DCGM_FT_STRING: u32 = 2;
const DCGM_FT_TIMESTAMP: u32 = 3;
const DCGM_FT_DOUBLE_BLANK: u32 = 100;

// --- DCGM Profiling Metric Field IDs ---
// See DCGM_FI_PROF_* definitions.

/// (ID: 1002) The ratio of cycles a Streaming Multiprocessor (SM) has at least 1 warp assigned.
/// (computed from the number of cycles and elapsed cycles)
/// High value indicates compute saturation.
const DCGM_FI_PROF_SM_ACTIVE: u16 = 1002;
/// (ID: 1003) Ratio of resident warps on SMs to the theoretical maximum.
/// Indicates how full the SMs are with threads. Useful with `DCGM_FI_PROF_DRAM_ACTIVE`.
const DCGM_FI_PROF_SM_OCCUPANCY: u16 = 1003;
/// (ID: 1004) Ratio of cycles the tensor cores (FP16/BF16 matrix units) were active.
/// Essential for mixed-precision workload monitoring.
const DCGM_FI_PROF_PIPE_TENSOR_ACTIVE: u16 = 1004;
/// (ID: 1005) Ratio of cycles the device memory interface was active (sending/receiving).
/// Helps identify memory bottlenecks.
const DCGM_FI_PROF_DRAM_ACTIVE: u16 = 1005;
/// (ID: 1006) Ratio of cycles the FP64 (double-precision) arithmetic pipeline was active.
const DCGM_FI_PROF_PIPE_FP64_ACTIVE: u16 = 1006;
/// (ID: 1007) Ratio of cycles the FP32 (single-precision) arithmetic pipeline was active.
const DCGM_FI_PROF_PIPE_FP32_ACTIVE: u16 = 1007;
/// (ID: 1008) Ratio of cycles the FP16 arithmetic pipeline (excluding tensor cores) was active.
const DCGM_FI_PROF_PIPE_FP16_ACTIVE: u16 = 1008;
/// (ID: 1014) Ratio of cycles the half-precision tensor core math units (HMMA) were active.
/// More granular than `DCGM_FI_PROF_PIPE_TENSOR_ACTIVE`.
const DCGM_FI_PROF_PIPE_TENSOR_HMMA_ACTIVE: u16 = 1014;
/// (ID: 1009) Bytes transmitted over PCIe (Device-to-Host perspective). Header + Payload.
/// Useful for DtoH copy bottleneck analysis.
const DCGM_FI_PROF_PCIE_TX_BYTES: u16 = 1009;
/// (ID: 1010) Bytes received over PCIe (Host-to-Device perspective). Header + Payload.
/// Useful for HtoD copy bottleneck analysis.
const DCGM_FI_PROF_PCIE_RX_BYTES: u16 = 1010;
/// (ID: 1011) Bytes transmitted over NVLink. Header + Payload.
const DCGM_FI_PROF_NVLINK_TX_BYTES: u16 = 1011;
/// (ID: 1012) Bytes received over NVLink. Header + Payload.
const DCGM_FI_PROF_NVLINK_RX_BYTES: u16 = 1012;

/// DCGM Group IDs.
/// Represents all GPUs discovered on the node.
const DCGM_GROUP_ALL_GPUS: u32 = 0x7fffffff;

// --- Type Aliases for FFI Clarity ---

/// Alias for the `dcgmReturn_t` C type (typically `int`). Represents DCGM API return codes.
type DcgmReturnT = i32;
/// Alias for the `dcgmHandle_t` C type (`void*`). Represents the connection handle to DCGM.
type DcgmHandleT = *mut c_void;
/// Alias for the `dcgmGpuGrp_t` C type (typically `unsigned int`). Represents a DCGM GPU group ID.
type DcgmGpuGrpT = u32;
/// Alias for the `dcgmFieldGrp_t` C type (typically `unsigned int`). Represents a DCGM field group ID.
type DcgmFieldGrpT = u32;
/// Alias for the `dcgmFieldEntityGroup_t` C type (typically `unsigned int`). Represents the entity type (GPU, VGPU, etc.).
type DcgmFieldEntityGroupT = u32;
/// Alias for the `dcgmFieldEid_t` C type (typically `unsigned int`). Represents the entity ID within its group.
type DcgmFieldEidT = u32;

// --- FFI Struct Definitions ---
// These mirror the C structures defined in DCGM headers (like dcgm_structs.h).
// They must match the layout expected by the linked libdcgm.so.4 library.

/// Represents a single field value retrieved from DCGM. Corresponds to `dcgmFieldValue_v1`.
#[repr(C)]
#[derive(Clone)]
struct DcgmFieldValueV1 {
    /// Structure version.
    version: u32,
    /// The DCGM field ID (`DCGM_FI_*`) this value corresponds to.
    field_id: u16,
    /// The type of the value stored (`DCGM_FT_*`).
    field_type: u16,
    /// Status of this specific value (e.g., `DCGM_ST_OK`, `DCGM_ST_NO_DATA`).
    status: i32,
    /// Timestamp of when the value was sampled (microseconds since Unix epoch).
    ts: i64,
    /// The actual value, stored in a union based on `field_type`.
    value: dcgmFieldValue_v1_value,
}

/// Union holding the value for `DcgmFieldValueV1`.
#[repr(C)]
#[derive(Clone, Copy)]
union dcgmFieldValue_v1_value {
    dbl: f64,
    i64: i64,
    str: [c_char; DCGM_MAX_STR_LENGTH],
}

/// C function pointer type definition for the callback used by `dcgmGetLatestValues_v2`.
///
/// This function is implemented in Rust (`field_value_callback`) and passed to DCGM.
/// DCGM calls this function for each entity, providing the latest sampled values.
///
/// # Parameters
/// * `entity_group_id`: The type of entity (`DCGM_FE_GPU`, etc.).
/// * `entity_id`: The specific ID of the entity (e.g., GPU index).
/// * `values`: Pointer to an array of `DcgmFieldValueV1` structs for this entity.
/// * `values_count`: The number of elements in the `values` array.
/// * `user_data`: An opaque pointer passed through from the `dcgmGetLatestValues_v2` call.
///
/// # Returns
/// * `0` for success, non-zero for error (causes DCGM to stop iterating).
type DcgmFieldValueEnumeration = extern "C" fn(
    entity_group_id: DcgmFieldEntityGroupT,
    entity_id: DcgmFieldEidT,
    values: *mut DcgmFieldValueV1,
    values_count: c_int,
    user_data: *mut c_void,
) -> c_int;

/// Creates a DCGM version value from a struct type and version number.
///
/// Replicates the C macro `MAKE_DCGM_VERSION(st, ver)`: `(sizeof(st) | (ver << 24))`.
/// This is crucial for FFI calls that take versioned structs.
#[macro_export]
macro_rules! make_dcgm_version {
    ($struct_type:ty, $version:expr) => {
        (std::mem::size_of::<$struct_type>() as u32) | (($version as u32) << 24)
    };
}

/// Information about a single DCGM profiling metric group. Corresponds to `dcgmProfMetricGroupInfo_v2`.
#[repr(C)]
#[derive(Clone, Copy)]
struct DcgmProfMetricGroupInfoV2 {
    /// Major ID of this group (e.g., groups with the same major ID might be mutually exclusive).
    major_id: u16,
    /// Minor ID distinguishing groups within the same major ID.
    minor_id: u16,
    /// Number of valid field IDs in the `field_ids` array.
    num_field_ids: u32,
    /// Array containing the DCGM field IDs (`DCGM_FI_PROF_*`) in this group.
    field_ids: [u16; DCGM_PROF_MAX_FIELD_IDS_PER_GROUP_V2],
}

/// Version 3 constant for the [`DcgmProfGetMetricGroupsT`] structure.
const DCGM_PROF_GET_METRIC_GROUPS_VERSION3: u32 = make_dcgm_version!(DcgmProfGetMetricGroupsT, 3);

/// Structure passed to `dcgmProfGetSupportedMetricGroups`. Corresponds to `dcgmProfGetMetricGroups_v3`.
/// Note the `typedef dcgmProfGetMetricGroups_v3 dcgmProfGetMetricGroups_t` in C headers.
#[repr(C)]
struct DcgmProfGetMetricGroupsT {
    /// Version of this struct format. Must be set correctly before calling FFI.
    /// Use `DCGM_PROF_GET_METRIC_GROUPS_VERSION3`.
    version: u32,
    /// Reserved field, should be set to 0.
    unused: u32,
    /// Input: GPU ID to query for supported groups (0 for any GPU).
    gpu_id: u32,
    /// Output: Number of valid entries populated in the `metric_groups` array.
    num_metric_groups: u32,
    /// Output: Array populated with information about supported metric groups.
    metric_groups: [DcgmProfMetricGroupInfoV2; DCGM_PROF_MAX_NUM_GROUPS_V2],
}

// --- Trait Definition ---

/// Defines the interface for interacting with the DCGM library.
///
/// This trait allows for mocking the DCGM library during unit testing.
trait DcgmLibrary: Send + Sync + 'static {
    // Methods needed during initialization/setup
    fn get_supported_prof_metric_ids(&self) -> Result<HashSet<u16>, String>;
    fn create_field_group(&self, field_ids: &[u16]) -> Result<DcgmFieldGrpT, String>;
    fn watch_fields(
        &self,
        group_id: DcgmGpuGrpT,
        field_group_id: DcgmFieldGrpT,
        update_freq_us: i64,
        max_keep_age: f64,
        max_keep_samples: i32,
    ) -> Result<(), String>;

    // Methods needed during metric collection by the worker
    fn update_all_fields(&self, wait_for_update: i32) -> Result<(), String>;
    fn get_latest_values(
        &self,
        group_id: DcgmGpuGrpT,
        field_group_id: DcgmFieldGrpT,
        callback: DcgmFieldValueEnumeration,
        user_data: *mut c_void,
    ) -> Result<(), String>;
}

/// Manages the loaded DCGM dynamic library and the connection handle.
///
/// Provides safe wrappers around DCGM C API FFI calls.
struct DcgmLib {
    /// Handle to the loaded dynamic library (e.g., `libdcgm.so.4`).
    lib: Library,
    /// Opaque handle representing the connection to the DCGM host engine.
    handle: DcgmHandleT,
}

/// Drops the DcgmLib wrapper.
/// NOTE: Explicitly *does not* call dcgmDisconnect.
impl Drop for DcgmLib {
    fn drop(&mut self) {
        log::debug!("Dropping DcgmLib wrapper (handle: {:?}).", self.handle);

        // --- DO NOT CALL dcgmDisconnect ---
        // Calling dcgmDisconnect here during worker thread termination was found
        // to cause segmentation faults during application shutdown.
        // The DCGM host engine is expected to handle the client disappearance,
        // and OS cleanup will close the connection upon process exit.
        // ----------------------------------

        // Null the handle conceptually. The Library object (`self.lib`)
        // will be dropped automatically after this, unloading the .so file.
        self.handle = ptr::null_mut();
        log::debug!("DcgmLib drop finished (dcgmDisconnect NOT called).");
    }
}

/// # Safety
/// This `unsafe impl` is justified because the application architecture guarantees
/// that any `DcgmLib` instance is created within the dedicated worker thread closure
/// (or moved into it immediately after creation) and is NEVER shared or accessed
/// concurrently from any other thread. All method calls happen sequentially within
/// the single worker thread managed by `DcgmWorker`. This eliminates the potential
/// data races that normally make raw pointers (`DcgmHandleT`) non-Send.
unsafe impl Send for DcgmLib {}
// We also technically need Sync because the trait object might require it implicitly
// depending on usage, even though we removed it from the trait bound. Let's add it
// with similar justification. If &DcgmLib was ever sent across threads (which it isn't here),
// it would NOT be safe.
/// # Safety
/// See safety justification for `unsafe impl Send for DcgmLib`. As the `DcgmLib` instance
/// is confined to a single thread, immutable references (`&DcgmLib`) cannot be accessed
/// concurrently from multiple threads, making it technically fulfill the Sync contract
/// *within this specific architecture*. This impl is needed primarily to satisfy bounds
/// potentially required by the trait object system, even if `Sync` is removed from the
/// direct trait definition bounds.
unsafe impl Sync for DcgmLib {}

impl DcgmLibrary for DcgmLib {
    /// Queries DCGM for all supported profiling metric field IDs.
    ///
    /// This iterates through the metric groups reported by `dcgmProfGetSupportedMetricGroups`
    /// and collects the unique field IDs found.
    ///
    /// # Returns
    /// * `Ok(HashSet<u16>)` containing the unique IDs of supported profiling fields.
    /// * `Err(String)` if querying the metric groups fails.
    fn get_supported_prof_metric_ids(&self) -> Result<HashSet<u16>, String> {
        log::debug!("Querying DCGM for supported profiling metric field IDs...");
        let mut supported_ids: HashSet<u16> = HashSet::new();
        let mut gmg: DcgmProfGetMetricGroupsT = unsafe { std::mem::zeroed() };

        // Call the FFI wrapper
        self.get_supported_metric_groups(0, &mut gmg)?; // Use gpuId = 0

        log::debug!("Found {} metric groups.", gmg.num_metric_groups);

        // Iterate through groups and field IDs
        for i in 0..gmg.num_metric_groups as usize {
            if i >= DCGM_PROF_MAX_NUM_GROUPS_V2 {
                break;
            } // Bounds check
            let mg_info = &gmg.metric_groups[i];

            for j in 0..mg_info.num_field_ids as usize {
                if j >= DCGM_MAX_FIELD_IDS_PER_FIELD_GROUP {
                    break;
                } // Bounds check
                let field_id = mg_info.field_ids[j];
                supported_ids.insert(field_id);
            }
        }

        log::debug!(
            "Found {} unique supported profiling field IDs.",
            supported_ids.len()
        );
        Ok(supported_ids)
    }

    /// Creates a DCGM field group for monitoring specific metrics.
    /// Wraps `dcgmFieldGroupCreate`.
    ///
    /// # Parameters
    /// * `field_ids`: A slice of DCGM field IDs (`DCGM_FI_*`) to include in the group.
    ///
    /// # Returns
    /// * `Ok(DcgmFieldGrpT)` containing the ID of the newly created field group.
    /// * `Err(String)` if the symbol lookup or FFI call fails.
    ///
    /// # Safety
    /// Calls an `unsafe extern "C"` function. Assumes `self.handle` is valid.
    fn create_field_group(&self, field_ids: &[u16]) -> Result<DcgmFieldGrpT, String> {
        unsafe {
            log::debug!("Creating field group with field_ids: {:?}", field_ids);

            let create_field_group: Symbol<
                unsafe extern "C" fn(
                    DcgmHandleT,
                    c_int,
                    *const u16,
                    *const c_char,
                    *mut DcgmFieldGrpT,
                ) -> DcgmReturnT,
            > = match self.lib.get(b"dcgmFieldGroupCreate") {
                Ok(f) => {
                    log::debug!("Found dcgmFieldGroupCreate symbol");
                    f
                }
                Err(e) => return Err(format!("Failed to get dcgmFieldGroupCreate symbol: {}", e)),
            };

            let group_name = CString::new("rust_dcgm_field_group").unwrap();
            let mut field_group_id: DcgmFieldGrpT = 0;

            log::debug!(
                "Calling dcgmFieldGroupCreate with {} fields",
                field_ids.len()
            );
            let result = create_field_group(
                self.handle,
                field_ids.len() as c_int,
                field_ids.as_ptr(),
                group_name.as_ptr(),
                &mut field_group_id,
            );
            log::debug!(
                "dcgmFieldGroupCreate returned {} with field_group_id={}",
                result,
                field_group_id
            );

            if result != DCGM_ST_OK {
                return Err(format!(
                    "Failed to create field group: {}: {}",
                    result,
                    self.error_string(result)
                ));
            }

            Ok(field_group_id)
        }
    }

    /// Configures DCGM to watch the fields in a specified group.
    /// Wraps `dcgmWatchFields`.
    ///
    /// # Parameters
    /// * `group_id`: The GPU group ID to watch (e.g., [`DCGM_GROUP_ALL_GPUS`]).
    /// * `field_group_id`: The ID of the field group (created by [`DcgmLib::create_field_group`]) containing the metrics to watch.
    /// * `update_freq_us`: How often DCGM should sample the fields, in microseconds.
    /// * `max_keep_age`: How long DCGM should retain samples, in seconds (0.0 = unlimited).
    /// * `max_keep_samples`: The maximum number of samples DCGM should retain per field (0 = unlimited, 1 = latest only).
    ///
    /// # Returns
    /// * `Ok(())` on success.
    /// * `Err(String)` if the symbol lookup or FFI call fails.
    ///
    /// # Safety
    /// Calls an `unsafe extern "C"` function. Assumes `self.handle`, `group_id`, and `field_group_id` are valid.
    fn watch_fields(
        &self,
        group_id: DcgmGpuGrpT,
        field_group_id: DcgmFieldGrpT,
        update_freq_us: i64,
        max_keep_age: f64,
        max_keep_samples: i32,
    ) -> Result<(), String> {
        unsafe {
            log::debug!("Setting up field watches");
            log::debug!("group_id={}, field_group_id={}, update_freq_us={}, max_keep_age={}, max_keep_samples={}",
                     group_id, field_group_id, update_freq_us, max_keep_age, max_keep_samples);

            let watch_fields: Symbol<
                unsafe extern "C" fn(
                    DcgmHandleT,
                    DcgmGpuGrpT,
                    DcgmFieldGrpT,
                    i64,
                    f64,
                    i32,
                ) -> DcgmReturnT,
            > = match self.lib.get(b"dcgmWatchFields") {
                Ok(f) => {
                    log::debug!("Found dcgmWatchFields symbol");
                    f
                }
                Err(e) => return Err(format!("Failed to get dcgmWatchFields symbol: {}", e)),
            };

            log::debug!("Calling dcgmWatchFields");
            let result = watch_fields(
                self.handle,
                group_id,
                field_group_id,
                update_freq_us,
                max_keep_age,
                max_keep_samples,
            );
            log::debug!("dcgmWatchFields returned {}", result);

            if result != DCGM_ST_OK {
                return Err(format!(
                    "Failed to set watches: {}: {}",
                    result,
                    self.error_string(result)
                ));
            }

            Ok(())
        }
    }

    /// Triggers an update cycle for watched fields (optional).
    /// Wraps `dcgmUpdateAllFields`.
    ///
    /// # Parameters
    /// * `wait_for_update`: If `1`, waits for the update cycle to complete. If `0`,
    ///   triggers the cycle but returns immediately.
    ///
    /// # Returns
    /// * `Ok(())` on success.
    /// * `Err(String)` if the symbol lookup or FFI call fails.
    ///
    /// # Safety
    /// Calls an `unsafe extern "C"` function. Assumes `self.handle` is valid.
    fn update_all_fields(&self, wait_for_update: i32) -> Result<(), String> {
        unsafe {
            log::debug!(
                "Updating all fields with wait_for_update={}",
                wait_for_update
            );

            let update_all_fields: Symbol<unsafe extern "C" fn(DcgmHandleT, i32) -> DcgmReturnT> =
                match self.lib.get(b"dcgmUpdateAllFields") {
                    Ok(f) => {
                        log::debug!("Found dcgmUpdateAllFields symbol");
                        f
                    }
                    Err(e) => {
                        return Err(format!("Failed to get dcgmUpdateAllFields symbol: {}", e))
                    }
                };

            log::debug!("Calling dcgmUpdateAllFields");
            let result = update_all_fields(self.handle, wait_for_update);
            log::debug!("dcgmUpdateAllFields returned {}", result);

            if result != DCGM_ST_OK {
                return Err(format!(
                    "Failed to update all fields: {}: {}",
                    result,
                    self.error_string(result)
                ));
            }

            Ok(())
        }
    }

    /// Retrieves the most recent values for watched fields using a callback.
    /// Wraps `dcgmGetLatestValues_v2`.
    ///
    /// # Parameters
    /// * `group_id`: The GPU group ID to query.
    /// * `field_group_id`: The field group ID containing the watched fields.
    /// * `callback`: The Rust function (`extern "C"`) to be called by DCGM with the data.
    /// * `user_data`: An opaque pointer passed unmodified to the `callback`.
    ///
    /// # Returns
    /// * `Ok(())` if the FFI call itself was successful (the callback handles data processing).
    ///   Returns `Ok(())` even on `DCGM_ST_NO_DATA`.
    /// * `Err(String)` if symbol lookup fails or a DCGM error other than `NO_DATA` occurs.
    ///
    /// # Safety
    /// Calls an `unsafe extern "C"` function. Assumes `self.handle`, `group_id`,
    /// `field_group_id` are valid. The `user_data` pointer must be valid for the
    /// lifetime of the call and usable by the `callback`. The `callback` itself must
    /// adhere to `extern "C"` calling conventions and handle potential panics safely.
    fn get_latest_values(
        &self,
        group_id: DcgmGpuGrpT,
        field_group_id: DcgmFieldGrpT,
        callback: DcgmFieldValueEnumeration,
        user_data: *mut c_void,
    ) -> Result<(), String> {
        unsafe {
            log::debug!(
                "Calling get_latest_values with group_id={}, field_group_id={}",
                group_id,
                field_group_id
            );
            log::debug!("user_data pointer: {:?}", user_data);

            let get_latest_values: Symbol<
                unsafe extern "C" fn(
                    DcgmHandleT,
                    DcgmGpuGrpT,
                    DcgmFieldGrpT,
                    DcgmFieldValueEnumeration,
                    *mut c_void,
                ) -> DcgmReturnT,
            > = match self.lib.get(b"dcgmGetLatestValues_v2") {
                Ok(f) => {
                    log::debug!("Found dcgmGetLatestValues_v2 symbol");
                    f
                }
                Err(e) => {
                    return Err(format!(
                        "Failed to get dcgmGetLatestValues_v2 symbol: {}",
                        e
                    ))
                }
            };

            log::debug!("About to call dcgmGetLatestValues_v2");
            let result =
                get_latest_values(self.handle, group_id, field_group_id, callback, user_data);
            log::debug!("dcgmGetLatestValues_v2 returned {}", result);

            // Handle different error cases
            if result == DCGM_ST_NO_DATA {
                log::debug!("No data available yet (DCGM_ST_NO_DATA). The profiling metrics might need time to be collected.");
                return Ok(());
            } else if result == DCGM_ST_NOT_SUPPORTED {
                return Err(format!(
                    "Operation not supported: {}: {}",
                    result,
                    self.error_string(result)
                ));
            } else if result == DCGM_ST_NOT_CONFIGURED {
                return Err(format!(
                    "Group or field group not found: {}: {}",
                    result,
                    self.error_string(result)
                ));
            } else if result != DCGM_ST_OK {
                return Err(format!(
                    "Failed to get latest values: {}: {}",
                    result,
                    self.error_string(result)
                ));
            } else {
                log::debug!("Successfully got latest values");
            }

            Ok(())
        }
    }
}

impl DcgmLib {
    /// Loads the DCGM library, initializes the connection, and connects to the host engine.
    ///
    /// # Parameters
    /// * `lib_path`: Path to the DCGM shared library (e.g., "libdcgm.so.4").
    /// * `host_address`: Address of the DCGM host engine (e.g., "localhost:5555").
    ///
    /// # Returns
    /// * `Ok(DcgmLib)` on success.
    /// * `Err(String)` if library loading, initialization, or connection fails.
    ///
    /// # Safety
    /// This function involves loading a dynamic library and calling C functions via FFI,
    /// which is inherently unsafe. It assumes the provided `lib_path` points to a valid
    /// DCGM library compatible with the FFI definitions used here.
    fn new(lib_path: &str, host_address: &str) -> Result<Self, String> {
        log::debug!("Loading DCGM library from path: {}", lib_path);
        unsafe {
            let lib = match Library::new(lib_path) {
                Ok(lib) => lib,
                Err(e) => return Err(format!("Failed to load DCGM library: {}", e)),
            };

            // Initialize DCGM.
            let init: Symbol<unsafe extern "C" fn() -> DcgmReturnT> = match lib.get(b"dcgmInit") {
                Ok(f) => f,
                Err(e) => return Err(format!("Failed to get dcgmInit symbol: {}", e)),
            };

            let result = init();
            if result != DCGM_ST_OK {
                return Err(format!("Failed to initialize DCGM: {}", result));
            }

            // Connect to DCGM host engine.
            let connect: Symbol<
                unsafe extern "C" fn(*const c_char, *mut DcgmHandleT) -> DcgmReturnT,
            > = match lib.get(b"dcgmConnect") {
                Ok(f) => f,
                Err(e) => return Err(format!("Failed to get dcgmConnect symbol: {}", e)),
            };

            let c_addr = CString::new(host_address).unwrap();
            let mut handle: DcgmHandleT = ptr::null_mut();

            let result = connect(c_addr.as_ptr(), &mut handle);
            if result != DCGM_ST_OK {
                return Err(format!("Failed to connect to DCGM: {}", result));
            }

            log::debug!(
                "Connected to DCGM host engine successfully. Handle: {:?}",
                handle
            );

            Ok(DcgmLib { lib, handle })
        }
    }

    /// Gets the supported profiling metric groups for a given GPU.
    /// Wraps `dcgmProfGetSupportedMetricGroups`.
    ///
    /// # Parameters
    /// * `gpu_id`: The ID of the GPU to query (use 0 for any GPU supporting profiling).
    /// * `gmg`: A mutable reference to a [`DcgmProfGetMetricGroupsT`] struct to be populated.
    ///
    /// # Returns
    /// * `Ok(())` on success.
    /// * `Err(String)` on failure to find the symbol or if the FFI call returns an error.
    ///
    /// # Safety
    /// Calls an `unsafe extern "C"` function. Assumes `self.handle` is valid and `gmg`
    /// points to valid memory for the struct. The caller must ensure `gmg` is initialized
    /// correctly (e.g., zeroed) before calling, although this wrapper sets the version.
    fn get_supported_metric_groups(
        &self,
        gpu_id: u32,
        gmg: &mut DcgmProfGetMetricGroupsT,
    ) -> Result<(), String> {
        unsafe {
            let func: Symbol<
                unsafe extern "C" fn(DcgmHandleT, &mut DcgmProfGetMetricGroupsT) -> DcgmReturnT,
            > = match self.lib.get(b"dcgmProfGetSupportedMetricGroups") {
                Ok(f) => f,
                Err(e) => {
                    return Err(format!(
                        "Failed to get dcgmProfGetSupportedMetricGroups symbol: {}",
                        e
                    ))
                }
            };

            gmg.version = DCGM_PROF_GET_METRIC_GROUPS_VERSION3;
            gmg.gpu_id = gpu_id;
            gmg.num_metric_groups = 0; // Initialize output field

            let result = func(self.handle, gmg);

            if result != DCGM_ST_OK {
                return Err(format!(
                    "dcgmProfGetSupportedMetricGroups failed: {}: {}",
                    result,
                    self.error_string(result)
                ));
            }
            Ok(())
        }
    }

    /// Gets a human-readable error string for a DCGM error code using the instance's library handle.
    ///
    /// # Parameters
    /// * `error_code`: The `DcgmReturnT` error code from a DCGM function call.
    ///
    /// # Returns
    /// * A `String` describing the error. Returns a generic message if the code is unknown
    ///   or the `dcgmErrorString` symbol cannot be found.
    fn error_string(&self, error_code: DcgmReturnT) -> String {
        unsafe {
            let error_string: Symbol<unsafe extern "C" fn(DcgmReturnT) -> *const c_char> =
                match self.lib.get(b"dcgmErrorString") {
                    Ok(f) => f,
                    Err(_) => return format!("Unknown error code: {}", error_code),
                };

            let c_str = error_string(error_code);
            if c_str.is_null() {
                return format!("Unknown error code: {}", error_code);
            }

            CStr::from_ptr(c_str).to_string_lossy().to_string()
        }
    }
}

/// Alias for the result type of getting metrics.
type DcgmMetricsResult = Result<Vec<(String, MetricValue)>, String>;

/// Commands sent from the [`DcgmClient`] to the [`DcgmWorker`] thread.
enum DcgmCommand {
    /// Request the latest collected metrics.
    GetMetrics {
        /// Channel to send the `DcgmMetricsResult` back to the requester.
        responder: oneshot::Sender<DcgmMetricsResult>,
    },
    /// Command to shut down the worker thread gracefully.
    Shutdown,
}

/// Result type for the one-time initialization handshake.
type InitResult = Result<(), String>; // Ok signals success, Err contains error message

/// Thread-safe client for interacting with the DCGM monitoring worker thread.
///
/// Creates and manages a background thread that handles all blocking DCGM FFI calls.
/// Provides an asynchronous interface (`get_metrics`) for requesting GPU metrics.
///
/// On creation (`new`), it initializes DCGM, queries supported fields, filters
/// against a desired list, creates necessary DCGM groups, starts watches,
/// and spawns the worker thread.
///
/// Ensures DCGM is shut down cleanly when the client is dropped.
#[derive(Clone)]
pub struct DcgmClient {
    sender: mpsc::Sender<DcgmCommand>,
}

impl DcgmClient {
    /// Creates a new `DcgmClient` and starts the background worker thread.
    ///
    /// This involves:
    /// 1. Loading the specified DCGM library (`libdcgm.so.4`).
    /// 2. Initializing and connecting to the DCGM host engine.
    /// 3. Querying the engine for supported profiling field IDs.
    /// 4. Filtering a predefined list of desired field IDs against the supported ones.
    /// 5. Creating a DCGM field group containing the actual fields to be monitored.
    /// 6. Setting up DCGM watches to collect data periodically for this group.
    /// 7. Spawning a dedicated OS thread to run the [`DcgmWorker`] loop.
    ///
    /// # Returns
    /// * `Ok(DcgmClient)` on successful initialization and thread spawn.
    /// * `Err(String)` if any step fails (library loading, connection, setup, thread spawn).
    ///
    /// # Errors
    /// Can fail if `libdcgm.so.4` cannot be found or loaded, if connection to the
    /// DCGM host engine fails, if required DCGM functions are missing, or if the
    /// background thread cannot be spawned. Failure during DCGM setup within the
    /// thread (e.g., creating groups, setting watches) will cause the thread to exit
    /// and subsequent calls to `get_metrics` will likely fail.
    pub fn new() -> Result<Self, String> {
        // Path to the DCGM shared library. TODO: Consider making this configurable.
        // This code assumes compatibility with the API level corresponding to .so.4.
        let lib_path = "libdcgm.so.4".to_string();
        // Default address for the DCGM host engine. TODO: Consider making this configurable.
        let host_address = "localhost:5555".to_string();

        // Define the list of profiling metrics we *ideally* want to monitor.
        // The actual monitored list depends on hardware/driver support.
        let desired_field_ids = vec![
            DCGM_FI_PROF_SM_ACTIVE,
            DCGM_FI_PROF_SM_OCCUPANCY,
            DCGM_FI_PROF_PIPE_TENSOR_ACTIVE,
            DCGM_FI_PROF_DRAM_ACTIVE,
            DCGM_FI_PROF_PIPE_FP64_ACTIVE,
            DCGM_FI_PROF_PIPE_FP32_ACTIVE,
            DCGM_FI_PROF_PIPE_FP16_ACTIVE,
            DCGM_FI_PROF_PIPE_TENSOR_HMMA_ACTIVE,
            DCGM_FI_PROF_PCIE_TX_BYTES,
            DCGM_FI_PROF_PCIE_RX_BYTES,
            DCGM_FI_PROF_NVLINK_TX_BYTES,
            DCGM_FI_PROF_NVLINK_RX_BYTES,
        ];

        // Use a standard MPSC channel for commands to the synchronous worker thread.
        let (cmd_sender, cmd_receiver) = mpsc::channel();

        // sync_channel(0) creates a rendezvous channel for the handshake.
        let (init_sender, init_receiver): (SyncSender<InitResult>, SyncReceiver<InitResult>) =
            mpsc::sync_channel(0);

        let thread_desired_field_ids = desired_field_ids.clone();

        // Spawn a dedicated OS thread to handle blocking DCGM interactions.
        // This avoids blocking the async runtime of the main application.
        let spawn_result = thread::Builder::new()
            .name("dcgm-worker-sync".to_string())
            .spawn(move || { // Closure takes ownership
                // --- Worker Thread Initialization ---
                log::info!("DCGM worker: Initializing DCGM library...");
                let dcgm_result = DcgmLib::new(&lib_path, &host_address);

                let dcgm = match dcgm_result {
                    Ok(lib) => lib,
                    Err(e) => {
                        log::debug!("DCGM worker: Failed to initialize DCGM library: {}. Thread exiting.", e);
                        // --- Send failure back via handshake ---
                        let _ = init_sender.send(Err(e)); // Ignore send error if main thread already gave up
                        return; // Exit thread
                    }
                };
                log::info!("DCGM worker: Library initialized.");

                let supported_ids_result = dcgm.get_supported_prof_metric_ids();
                let actual_field_ids = match supported_ids_result {
                     Ok(supported_set) => {
                         // Filter logic...
                         let filtered: Vec<u16> = thread_desired_field_ids
                             .into_iter()
                             .filter(|id| supported_set.contains(id))
                             .collect();
                         if filtered.is_empty() {
                                log::warn!("DCGM worker: No supported fields found after filtering. Exiting thread.");
                                // Send success as DCGM init itself worked, but monitoring won't start.
                                let _ = init_sender.send(Ok(()));
                                return;
                         }
                         filtered
                     }
                     Err(e) => {
                         log::error!("DCGM worker: Failed to get supported fields: {}. Treating as non-critical init state.", e);
                         // Or potentially send Err if this *is* critical:
                         // let _ = init_sender.send(Err(format!("Failed to get supported DCGM fields: {}", e)));
                         // return;
                         thread_desired_field_ids // Fallback
                     }
                 };

                 // If filtering resulted in no fields, maybe exit? (depends on requirements)
                 if actual_field_ids.is_empty() {
                    log::warn!("DCGM worker: No supported fields found after filtering. Exiting thread.");
                    // Send success as DCGM init itself worked, but monitoring won't start.
                    let _ = init_sender.send(Ok(()));
                    return;
                 }

                 // --- Continue with setup ONLY if dcgm init succeeded ---
                 log::debug!("DCGM worker: Creating field group...");
                 let group_id = DCGM_GROUP_ALL_GPUS;
                 let field_group_result = dcgm.create_field_group(&actual_field_ids);
                 let field_group_id = match field_group_result {
                      Ok(id) => id,
                      Err(e) => {
                           log::error!("DCGM worker: Failed to create field group: {}. Thread exiting.", e);
                           let _ = init_sender.send(Err(format!("Failed to create field group: {}", e)));
                           return;
                      }
                 };

                 log::debug!("DCGM worker: Setting watches...");
                 let update_freq_us = 5_000_000; // 5 seconds
                 let max_keep_age = 0.0; // Unlimited
                 let max_keep_samples = 2; // Keep the latest 2 samples
                 let watch_result = dcgm.watch_fields(
                    group_id,
                    field_group_id,
                    update_freq_us,
                    max_keep_age,
                    max_keep_samples,
                );
                 if let Err(e) = watch_result {
                     log::error!("DCGM worker: Failed to set watches: {}. Thread exiting.", e);
                      let _ = init_sender.send(Err(format!("Failed to set watches: {}", e)));
                     return;
                 }

                // --- Initialization successful - Send confirmation ---
                log::info!("DCGM worker: Initial setup successful.");
                if init_sender.send(Ok(())).is_err() {
                    log::warn!("DCGM worker: Failed to send init success signal; main thread may have exited.");
                     // Don't start the worker loop if we couldn't confirm with main thread
                     return;
                 }

                // --- Create and Run Worker Loop ---
                log::debug!("DCGM worker: Starting command loop.");
                let mut worker = DcgmWorker::new(
                    Box::new(dcgm),
                    group_id,
                    field_group_id,
                    cmd_receiver, // Use the command receiver
                );
                worker.run();

                log::info!("DCGM worker: Command loop finished.");
            }); // End of thread closure

        // --- Check thread spawn result ---
        if let Err(e) = spawn_result {
            return Err(format!("Failed to spawn DCGM worker OS thread: {}", e));
        }
        log::info!("DCGM worker OS thread spawned. Waiting for init confirmation...");

        // --- Wait for Handshake Result ---
        match init_receiver.recv() {
            Ok(Ok(())) => {
                // Worker signaled successful initialization
                log::info!("DCGM worker thread initialized successfully.");
                Ok(Self { sender: cmd_sender }) // Return the command sender
            }
            Ok(Err(e)) => {
                // Worker signaled failure during initialization
                Err(format!("DCGM worker thread failed initialization: {}", e))
            }
            Err(_) => {
                // Channel disconnected - worker thread likely panicked or exited before sending handshake
                log::error!("DCGM worker thread disconnected unexpectedly during initialization.");
                Err("DCGM worker thread exited prematurely during initialization".to_string())
            }
        }
    }

    /// Asynchronously requests the latest collected DCGM metrics.
    ///
    /// Sends a [`DcgmCommand::GetMetrics`] message to the worker thread and awaits the response.
    ///
    /// # Returns
    /// * `Ok(Vec<(String, MetricValue)>)` containing the latest metrics on success.
    /// * `Err(String)` if the worker thread has shut down or communication fails.
    pub async fn get_metrics(&self) -> DcgmMetricsResult {
        let (tx, rx) = oneshot::channel();
        let command = DcgmCommand::GetMetrics { responder: tx };

        // Use blocking send (sender.send(...)) - should be okay if worker is responsive
        // Use try_send or send_timeout if blocking is a concern, but usually fine here.
        if self.sender.send(command).is_err() {
            // Error means the receiving end (worker thread) has hung up (likely panicked or shut down).
            return Err("DCGM worker task has shutdown".to_string());
        }

        // Await the response from the worker
        match rx.await {
            Ok(result) => result,
            Err(_) => Err("Failed to receive response from DCGM worker".to_string()),
        }
    }

    pub fn shutdown(&self) {
        log::debug!("Sending Shutdown command to DCGM worker thread.");
        // Ignore error if receiver has already dropped (thread already exited).
        let _ = self.sender.send(DcgmCommand::Shutdown);
    }
}

/// `extern "C"` callback function passed to `dcgmGetLatestValues_v2`.
///
/// DCGM calls this function from its own context (within the worker thread in this setup)
/// for each entity (GPU) that has updated values for the watched field group.
///
/// # Parameters
/// * `_entity_group_id`: Type of the entity (`DCGM_FE_GPU`, etc.).
/// * `entity_id`: Index of the specific GPU.
/// * `values`: Pointer to an array of `DcgmFieldValueV1` containing metrics for this GPU.
/// * `values_count`: Number of valid entries in the `values` array.
/// * `user_data`: Opaque pointer passed from `get_latest_values`, cast back to `&mut Vec<(String, MetricValue)>`.
///
/// # Returns
/// * `0` to indicate success and continue processing. Non-zero would stop DCGM's iteration.
///
/// # Safety
/// - This function is marked `extern "C"` and must not panic.
/// - It dereferences the raw `user_data` pointer, assuming it's a valid pointer to the expected `Vec`.
/// - It dereferences the raw `values` pointer, trusting DCGM provides valid data and count.
/// - It accesses fields of a C `union` (`dcgmFieldValue_v1_value`), which requires careful handling
///   based on the `field_type` (though Rust's access rules make this safer than C).
extern "C" fn field_value_callback(
    entity_group_id: DcgmFieldEntityGroupT,
    entity_id: DcgmFieldEidT,
    values: *mut DcgmFieldValueV1,
    values_count: c_int,
    user_data: *mut c_void, // This will point to a `&mut Vec<(String, MetricValue)>`
) -> c_int {
    // Wrap the entire body to catch potential panics
    let result = std::panic::catch_unwind(|| {
        // Basic safety checks.
        if user_data.is_null() || values.is_null() || values_count <= 0 {
            // Maybe log an error here if possible, but avoid panicking in C callback
            return if user_data.is_null() { 1 } else { 0 }; // Indicate error if user_data is null
        }

        // Cast user_data back to the mutable vector reference.
        // This is unsafe, relying on the caller (`collect_metrics`) providing the correct pointer
        let metrics_vec: &mut Vec<(String, MetricValue)> =
            unsafe { &mut *(user_data as *mut Vec<(String, MetricValue)>) };

        let entity_type = match entity_group_id {
            DCGM_FE_GPU => "gpu",
            DCGM_FE_VGPU => "gpu", // TODO: Handle the distinction if needed.
            _ => "unknown",
        };

        unsafe {
            let values_slice = std::slice::from_raw_parts(values, values_count as usize);

            for value in values_slice {
                if value.status != DCGM_ST_OK {
                    // Skip unavailable/error values.
                    continue;
                }

                let field_id = value.field_id;
                let field_type = value.field_type;

                let metric_value_opt: Option<MetricValue> = match field_type as u32 {
                    DCGM_FT_DOUBLE | DCGM_FT_DOUBLE_BLANK => {
                        let dbl = value.value.dbl;
                        // DCGM often uses large negative numbers or specific patterns for N/A.
                        // Adjust this condition based on observed DCGM behavior for blank values.
                        if value.status == DCGM_ST_OK && !dbl.is_nan() && dbl.abs() < 1e19 {
                            // Check status and avoid huge numbers.
                            Some(MetricValue::Float(dbl))
                        } else {
                            None // Treat as unavailable.
                        }
                    }
                    DCGM_FT_INT64 | DCGM_FT_TIMESTAMP => {
                        let i64_val = value.value.i64;
                        // DCGM often uses large negative numbers or specific patterns for N/A.
                        if value.status == DCGM_ST_OK && i64_val > -1_000_000_000_000 {
                            // Check status and avoid specific large negative numbers.
                            Some(MetricValue::Int(i64_val))
                        } else {
                            None // Treat as unavailable.
                        }
                    }
                    DCGM_FT_STRING => {
                        if value.status == DCGM_ST_OK && value.value.str[0] != 0 {
                            let c_str = CStr::from_ptr(value.value.str.as_ptr());
                            Some(MetricValue::String(c_str.to_string_lossy().into_owned()))
                        } else {
                            None
                        }
                    }
                    _ => None, // Unknown type.
                };

                if let Some(metric_value) = metric_value_opt {
                    let base_name = match field_id {
                        DCGM_FI_PROF_SM_ACTIVE => "smActive",
                        DCGM_FI_PROF_SM_OCCUPANCY => "smOccupancy",
                        DCGM_FI_PROF_PIPE_TENSOR_ACTIVE => "pipeTensorActive",
                        DCGM_FI_PROF_DRAM_ACTIVE => "dramActive",
                        DCGM_FI_PROF_PIPE_FP64_ACTIVE => "pipeFp64Active",
                        DCGM_FI_PROF_PIPE_FP32_ACTIVE => "pipeFp32Active",
                        DCGM_FI_PROF_PIPE_FP16_ACTIVE => "pipeFp16Active",
                        DCGM_FI_PROF_PIPE_TENSOR_HMMA_ACTIVE => "pipeTensorHmmaActive",
                        DCGM_FI_PROF_PCIE_TX_BYTES => "pcieTxBytes",
                        DCGM_FI_PROF_PCIE_RX_BYTES => "pcieRxBytes",
                        DCGM_FI_PROF_NVLINK_TX_BYTES => "nvlinkTxBytes",
                        DCGM_FI_PROF_NVLINK_RX_BYTES => "nvlinkRxBytes",
                        _ => &format!("dcgm_field_{}", field_id),
                    };
                    // Create a unique key per GPU per metric: e.g., "gpu.0.smActive".
                    let metric_key = format!("{}.{}.{}", entity_type, entity_id, base_name);
                    // Convert values from ratios [0, 1] to percentage [0, 100%].
                    let metric_value = if base_name.ends_with("Bytes") {
                        metric_value
                    } else {
                        match metric_value {
                            MetricValue::Float(f) => MetricValue::Float(f * 100.0),
                            MetricValue::Int(i) => MetricValue::Int(i * 100),
                            _ => metric_value,
                        }
                    };
                    metrics_vec.push((metric_key, metric_value));
                }
            }
        }
        0 // Indicate success.
    }); // End catch_unwind closure

    // Check the result of catch_unwind
    match result {
        Ok(return_code) => return_code, // Return 0 if Ok, or 1 if user_data was null
        Err(_) => {
            // A panic occurred within the closure
            log::error!("Panic caught within DCGM field_value_callback! Returning error to DCGM.");
            // Return a non-zero value to signal an error to DCGM
            1 // Or another distinct error code if needed
        }
    }
}

/// Owns the [`DcgmLib`] instance and processes commands received over MPSC channel.
///
/// Runs in a dedicated synchronous OS thread (`dcgm-worker-sync`). Listens for
/// [`DcgmCommand`] messages and performs the requested DCGM operations (e.g.,
/// collecting metrics).
struct DcgmWorker {
    dcgm: Box<dyn DcgmLibrary>,
    group_id: u32,
    field_group_id: u32,
    receiver: mpsc::Receiver<DcgmCommand>,
}

impl DcgmWorker {
    /// Creates a new `DcgmWorker`.
    ///
    /// Typically called only within the dedicated worker thread spawned by [`DcgmClient::new`].
    /// Takes ownership of the [`DcgmLib`] instance and the MPSC receiver.
    fn new(
        dcgm: Box<dyn DcgmLibrary>,
        group_id: u32,
        field_group_id: u32,
        receiver: mpsc::Receiver<DcgmCommand>,
    ) -> Self {
        DcgmWorker {
            dcgm,
            group_id,
            field_group_id,
            receiver,
        }
    }

    /// Runs the main command processing loop for the worker thread.
    ///
    /// This function blocks indefinitely, waiting for commands on the MPSC `receiver`.
    /// It processes [`DcgmCommand::GetMetrics`] by calling [`DcgmWorker::collect_metrics`]
    /// and sending the result back via the provided `oneshot` channel.
    /// It exits the loop upon receiving [`DcgmCommand::Shutdown`] or if the channel closes.
    fn run(&mut self) {
        log::debug!("DCGM worker SYNC run loop started.");

        // Loop over the blocking receiver.
        for command in &self.receiver {
            // Iterating blocks until a message or channel closes.
            match command {
                DcgmCommand::GetMetrics { responder } => {
                    // collect_metrics is already synchronous
                    let result = self.collect_metrics();
                    // Send the result back via the oneshot channel
                    // Ignore error if responder doesn't care anymore
                    let _ = responder.send(result);
                }
                DcgmCommand::Shutdown => {
                    log::debug!("DCGM worker received shutdown command.");
                    break; // Exit the loop
                }
            }
        }
        // Receiver iterator ends when the channel is closed OR after a break.
        log::debug!("DCGM worker SYNC run loop finished.");
        // DcgmLib's Drop implementation will handle cleanup here when worker goes out of scope
    }

    /// Collects the latest metrics by calling `dcgmGetLatestValues_v2`.
    ///
    /// This function calls the DCGM FFI function, which in turn invokes the
    /// [`field_value_callback`] function to populate a vector with metric data.
    ///
    /// It handles the `DCGM_ST_NO_DATA` case by returning an empty vector, as this
    /// can occur normally before the first watch interval completes.
    ///
    /// # Returns
    /// * `Ok(Vec<(String, MetricValue)>)` containing the collected metrics.
    /// * `Err(String)` if the `dcgmGetLatestValues_v2` call fails with an error
    ///   other than `DCGM_ST_NO_DATA`.
    fn collect_metrics(&self) -> DcgmMetricsResult {
        // Call update_all_fields to refresh the metrics using FFI
        // This is a blocking call, so it should be done in the worker thread.
        if let Err(e) = self.dcgm.update_all_fields(0) {
            log::warn!("DCGM update_all_fields failed: {}", e);
        }

        let mut metrics: Vec<(String, MetricValue)> = Vec::new();
        let result = self.dcgm.get_latest_values(
            self.group_id,
            self.field_group_id,
            field_value_callback,
            &mut metrics as *mut _ as *mut c_void,
        );

        match result {
            Ok(_) => Ok(metrics),
            Err(e) => {
                log::error!("DCGM get_latest_values failed: {}", e);
                Err(format!("DCGM get_latest_values failed: {}", e))
            }
        }
    }
}

// --- Unit Tests ---

#[cfg(test)]
mod tests {
    use super::*; // Import items from outer module
    use std::collections::HashSet;
    use std::sync::{Arc, Mutex}; // Use Mutex for interior mutability in mock

    // --- MockDcgmLib Implementation ---

    #[derive(Default, Clone)] // Add Clone
    struct MockDcgmLib {
        // Store expected results or behaviors using Mutex for thread safety if tests parallelize
        supported_ids: Option<Result<HashSet<u16>, String>>,
        latest_values_result: Option<Result<(), String>>,
        // Store captured values if needed, e.g., metrics passed to callback
        collected_metrics_output: Arc<Mutex<Vec<(String, MetricValue)>>>,
        update_all_fields_result: Option<Result<(), String>>,
        // Add fields for other trait methods if needed for specific tests
        create_field_group_result: Option<Result<DcgmFieldGrpT, String>>,
        watch_fields_result: Option<Result<(), String>>,
    }

    impl MockDcgmLib {
        // Helper methods to configure the mock
        fn expect_get_latest_values(&mut self, result: Result<(), String>) {
            self.latest_values_result = Some(result);
        }

        // Simulate callback populating the vector
        fn set_collected_metrics_output(&mut self, metrics: Vec<(String, MetricValue)>) {
            let mut lock = self.collected_metrics_output.lock().unwrap();
            *lock = metrics;
        }

        fn expect_update_all_fields(&mut self, result: Result<(), String>) {
            self.update_all_fields_result = Some(result);
        }
    }

    impl DcgmLibrary for MockDcgmLib {
        fn get_supported_prof_metric_ids(&self) -> Result<HashSet<u16>, String> {
            // Clone the result to return ownership
            self.supported_ids.clone().unwrap_or_else(|| {
                // Default behavior if not set
                Ok(HashSet::new())
            })
        }

        fn create_field_group(&self, _field_ids: &[u16]) -> Result<DcgmFieldGrpT, String> {
            self.create_field_group_result.clone().unwrap_or_else(|| {
                // Default success with dummy ID
                Ok(123)
            })
        }

        fn watch_fields(
            &self,
            _group_id: DcgmGpuGrpT, // Added actual params from trait, prefixed with _
            _field_group_id: DcgmFieldGrpT,
            _update_freq_us: i64,
            _max_keep_age: f64,
            _max_keep_samples: i32,
        ) -> Result<(), String> {
            // The body remains the same
            self.watch_fields_result.clone().unwrap_or(Ok(())) // Default Ok
        }

        fn update_all_fields(&self, _wait_for_update: i32) -> Result<(), String> {
            self.update_all_fields_result.clone().unwrap_or(Ok(())) // Default Ok
        }

        // Simulate calling the callback
        fn get_latest_values(
            &self,
            _group_id: DcgmGpuGrpT,
            _field_group_id: DcgmFieldGrpT,
            _callback: DcgmFieldValueEnumeration,
            user_data: *mut c_void,
        ) -> Result<(), String> {
            // Return the pre-programmed result for the FFI call itself
            match self.latest_values_result.clone() {
                Some(Ok(())) | None => {
                    // Default to Ok or if Ok(()) was programmed
                    // Simulate the callback populating the user_data vector
                    if !user_data.is_null() {
                        let expected_output = self.collected_metrics_output.lock().unwrap();
                        let metrics_vec: &mut Vec<(String, MetricValue)> =
                            unsafe { &mut *(user_data as *mut Vec<(String, MetricValue)>) };
                        metrics_vec.extend(expected_output.clone()); // Populate with mock data
                    }
                    Ok(())
                }
                Some(Err(e)) => Err(e), // Return programmed error
            }
        }
    }

    // --- Test Cases ---

    #[test]
    fn test_worker_collect_metrics_success() {
        // Arrange
        let mut mock_lib = MockDcgmLib::default();
        let expected_metrics = vec![
            ("gpu.0.smActive".to_string(), MetricValue::Float(55.5)),
            ("gpu.0.dramActive".to_string(), MetricValue::Float(30.1)),
        ];
        mock_lib.expect_update_all_fields(Ok(())); // Assume update_all_fields is called and succeeds
        mock_lib.expect_get_latest_values(Ok(())); // Simulate get_latest_values succeeding
        mock_lib.set_collected_metrics_output(expected_metrics.clone()); // Set what callback "produces"

        let (_tx, rx) = mpsc::channel(); // Mock receiver, won't be used directly here
        let worker = DcgmWorker::new(
            Box::new(mock_lib),
            DCGM_GROUP_ALL_GPUS, // Dummy group ID
            123,                 // Dummy field group ID
            rx,                  // Pass the receiver
        );

        // Act
        let result = worker.collect_metrics();

        // Assert
        assert!(result.is_ok());
        let collected = result.unwrap();
        assert_eq!(collected.len(), 2);
        assert_eq!(collected, expected_metrics);
    }

    #[test]
    fn test_worker_collect_metrics_no_data() {
        // Arrange
        let mut mock_lib = MockDcgmLib::default();
        mock_lib.expect_update_all_fields(Ok(()));
        // Simulate get_latest_values returning DCGM_ST_NO_DATA (which wrapper turns into Ok)
        mock_lib.expect_get_latest_values(Ok(()));
        mock_lib.set_collected_metrics_output(vec![]); // Ensure callback produces nothing

        let (_tx, rx) = mpsc::channel();
        let worker = DcgmWorker::new(Box::new(mock_lib), DCGM_GROUP_ALL_GPUS, 123, rx);

        // Act
        let result = worker.collect_metrics();

        // Assert
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty()); // Expect empty vector on NO_DATA
    }

    #[test]
    fn test_worker_collect_metrics_ffi_error() {
        // Arrange
        let mut mock_lib = MockDcgmLib::default();
        // This is the error the *mock* is programmed to return
        let base_error_msg = "DCGM FFI call failed".to_string();
        mock_lib.expect_update_all_fields(Ok(())); // Assume update succeeds
                                                   // Program the mock to return the base error
        mock_lib.expect_get_latest_values(Err(base_error_msg.clone()));

        let (_tx, rx) = mpsc::channel();
        let worker = DcgmWorker::new(Box::new(mock_lib), DCGM_GROUP_ALL_GPUS, 123, rx);

        // Act
        let result = worker.collect_metrics();

        // Assert
        assert!(result.is_err());
        // Construct the error message we expect `collect_metrics` to actually return
        let expected_error_message = format!("DCGM get_latest_values failed: {}", base_error_msg);
        // Compare against the fully formatted error message
        assert_eq!(result.unwrap_err(), expected_error_message);
    }

    #[test]
    fn test_worker_collect_metrics_update_error() {
        // Arrange
        let mut mock_lib = MockDcgmLib::default();
        let error_msg = "Update Failed".to_string();
        // Simulate update_all_fields failing
        mock_lib.expect_update_all_fields(Err(error_msg.clone()));
        // We likely wouldn't even call get_latest_values if update failed, but let's mock it anyway
        mock_lib.expect_get_latest_values(Ok(()));
        mock_lib.set_collected_metrics_output(vec![]);

        let (_tx, rx) = mpsc::channel();
        let worker = DcgmWorker::new(Box::new(mock_lib), DCGM_GROUP_ALL_GPUS, 123, rx);

        // Act
        let result = worker.collect_metrics();

        // Assert - Current implementation only WARNS on update failure, so it should still proceed
        // If we changed collect_metrics to return Err on update failure, this assert would change.
        assert!(result.is_ok()); // Currently, update failure doesn't stop collection
        assert!(result.unwrap().is_empty());
    }
}

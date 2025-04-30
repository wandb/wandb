use libloading::{Library, Symbol};
use std::{
    collections::HashSet,
    ffi::{c_char, c_int, c_uint, c_void, CStr, CString},
    ptr,
    sync::mpsc,
    thread,
};
use tokio::sync::oneshot;

use crate::metrics::MetricValue;

// Define DCGM constants, types and structures needed
const DCGM_ST_OK: i32 = 0;
const DCGM_ST_NO_DATA: i32 = -35;
const DCGM_ST_NOT_SUPPORTED: i32 = -14;
const DCGM_ST_NOT_CONFIGURED: i32 = -8;
const DCGM_GROUP_EMPTY: u32 = 0;
const DCGM_MAX_NUM_DEVICES: usize = 32;
const DCGM_MAX_STR_LENGTH: usize = 256;
const DCGM_MAX_FIELD_IDS_PER_FIELD_GROUP: usize = 128;

const DCGM_PROF_MAX_NUM_GROUPS_V2: usize = 10;
const DCGM_PROF_MAX_FIELD_IDS_PER_GROUP_V2: usize = 64;

// Constants for entity group types
const DCGM_FE_GPU: u32 = 0;
const DCGM_FE_VGPU: u32 = 1;
const DCGM_GROUP_DEFAULT: u32 = 0; // All GPUs on the node

// Field type constants
const DCGM_FT_DOUBLE: u32 = 0;
const DCGM_FT_INT64: u32 = 1;
const DCGM_FT_STRING: u32 = 2;
const DCGM_FT_TIMESTAMP: u32 = 3;
const DCGM_FT_BINARY: u32 = 4;
const DCGM_FT_DOUBLE_BLANK: u32 = 100;

// Profiling metrics field IDs

// Percentage of time at least one warp was active on an SM.
//
// A much better indicator of GPU compute saturation than raw utilization.
const DCGM_FI_PROF_SM_ACTIVE: u16 = 1002;

// Ratio of resident warps on SMs to max possible.
//
// It reflects how many threads are loaded on the SM relative to capacity.
// Very useful in conjunction with DRAM Active in determining memory bottlenecks.
const DCGM_FI_PROF_SM_OCCUPANCY: u16 = 1003;

// Ratio of cycles tensor cores are active (FP16/BF16 matrix ops).
//
// Essential for monitoring tensor core utilization in mixed-precision workloads.
const DCGM_FI_PROF_PIPE_TENSOR_ACTIVE: u16 = 1004;

// Ratio of cycles the device memory interface is active sending or receiving data.
//
// Values are useful in context with others in determining causes of bottlenecks or idling.
const DCGM_FI_PROF_DRAM_ACTIVE: u16 = 1005;

// Ratio of cycles the fp64 (double-precision) arithmetic pipeline is active.
const DCGM_FI_PROF_PIPE_FP64_ACTIVE: u16 = 1006;

// Ratio of cycles the FP32 arithmetic pipeline is active.
//
// Indicates how much standard precision floating-point math is being used.
const DCGM_FI_PROF_PIPE_FP32_ACTIVE: u16 = 1007;

// Ratio of cycles the fp16 arithmetic pipeline is active (excluding tensor cores).
//
// Helps determine if mixed precision (without tensor cores) is being utilized.
const DCGM_FI_PROF_PIPE_FP16_ACTIVE: u16 = 1008;

// More granular metrics separating integer matrix ops vs. half-precision matrix ops.
//
// It measures the utilization of half-precision tensor core math units.
const DCGM_FI_PROF_PIPE_TENSOR_HMMA_ACTIVE: u16 = 1014;

// The number of bytes of active PCIe tx (transmit) data including both header and payload.
//
// Note that this is from the perspective of the GPU, so copying data from device to host (DtoH)
// would be reflected in this metric.
// Helps identify bottlenecks in CPU-GPU data movement for non NVLink configurations.
const DCGM_FI_PROF_PCIE_TX_BYTES: u16 = 1009;

// The number of bytes of active PCIe rx (read) data including both header and payload.
//
// Note that this is from the perspective of the GPU, so copying data from host to device (HtoD)
// would be reflected in this metric.
// Helps identify bottlenecks in CPU-GPU data movement for non NVLink configurations.
const DCGM_FI_PROF_PCIE_RX_BYTES: u16 = 1010;

// The total number of bytes of active NvLink tx (transmit) data including both header and payload.
const DCGM_FI_PROF_NVLINK_TX_BYTES: u16 = 1011;

// The total number of bytes of active NvLink rx (read) data including both header and payload.
const DCGM_FI_PROF_NVLINK_RX_BYTES: u16 = 1012;

// Constants for special DCGM groups
const DCGM_GROUP_ALL_GPUS: u32 = 0x7fffffff;
const DCGM_GROUP_ALL_NVSWITCHES: u32 = 0x7ffffffe;
const DCGM_GROUP_ALL_INSTANCES: u32 = 0x7ffffffd;
const DCGM_GROUP_ALL_COMPUTE_INSTANCES: u32 = 0x7ffffffc;
const DCGM_GROUP_ALL_ENTITIES: u32 = 0x7ffffffb;
const DCGM_GROUP_NULL: u32 = 0x7ffffffa;

type dcgmReturn_t = i32;
type dcgmHandle_t = *mut c_void;
type dcgmGpuGrp_t = u32;
type dcgmFieldGrp_t = u32;
type dcgm_field_entity_group_t = u32;
type dcgm_field_eid_t = u32;

/// FFI types for DCGM

#[repr(C)]
struct dcgmGroupInfo_t {
    version: u32,
    count: u32,
    name: [c_char; DCGM_MAX_STR_LENGTH],
    entity_list: [dcgmGroupEntityPair_t; DCGM_MAX_NUM_DEVICES],
}

#[repr(C)]
struct dcgmGroupEntityPair_t {
    entity_group_id: dcgm_field_entity_group_t,
    entity_id: dcgm_field_eid_t,
}

#[repr(C)]
#[derive(Clone)]
struct dcgmFieldValue_v1 {
    version: u32,
    field_id: u16,
    field_type: u16,
    status: i32,
    ts: i64,
    value: dcgmFieldValue_v1_value,
}

#[repr(C)]
#[derive(Clone, Copy)]
union dcgmFieldValue_v1_value {
    dbl: f64,
    i64: i64,
    str: [c_char; DCGM_MAX_STR_LENGTH],
}

// Callback function type for dcgmGetLatestValues_v2
type DcgmFieldValueEnumeration = extern "C" fn(
    entity_group_id: dcgm_field_entity_group_t,
    entity_id: dcgm_field_eid_t,
    values: *mut dcgmFieldValue_v1,
    values_count: c_int,
    user_data: *mut c_void,
) -> c_int;

#[macro_export]
macro_rules! make_dcgm_version {
    ($struct_type:ty, $version:expr) => {
        (std::mem::size_of::<$struct_type>() as u32) | (($version as u32) << 24)
    };
}

#[repr(C)]
#[derive(Clone, Copy)] // Added Debug/Default for convenience
struct dcgmProfMetricGroupInfo_v2 {
    majorId: u16,
    minorId: u16,
    numFieldIds: u32,
    fieldIds: [u16; DCGM_PROF_MAX_FIELD_IDS_PER_GROUP_V2],
}

// Define the version constant using the CORRECTED struct definition below
// Note: The name dcgmProfGetMetricGroups_v3 matches the C struct name
const dcgmProfGetMetricGroups_version3: u32 = make_dcgm_version!(dcgmProfGetMetricGroups_t, 3);

#[repr(C)]
struct dcgmProfGetMetricGroups_t {
    // Matches the final typedef dcgmProfGetMetricGroups_t
    version: u32, // Should be dcgmProfGetMetricGroups_version3
    unused: u32,  // --- ADDED MISSING FIELD ---
    gpuId: u32,
    numMetricGroups: u32,
    metricGroups: [dcgmProfMetricGroupInfo_v2; DCGM_PROF_MAX_NUM_GROUPS_V2],
}

// DCGM library wrapper
struct DcgmLib {
    lib: Library,
    handle: dcgmHandle_t,
}

impl Drop for DcgmLib {
    fn drop(&mut self) {
        unsafe {
            if !self.handle.is_null() {
                let disconnect: Symbol<unsafe extern "C" fn(dcgmHandle_t) -> dcgmReturn_t> =
                    self.lib.get(b"dcgmDisconnect").unwrap();
                disconnect(self.handle);
            }
        }
    }
}

impl DcgmLib {
    fn new(lib_path: &str, host_address: &str) -> Result<Self, String> {
        unsafe {
            let lib = match Library::new(lib_path) {
                Ok(lib) => lib,
                Err(e) => return Err(format!("Failed to load DCGM library: {}", e)),
            };

            // Initialize DCGM
            let init: Symbol<unsafe extern "C" fn() -> dcgmReturn_t> = match lib.get(b"dcgmInit") {
                Ok(f) => f,
                Err(e) => return Err(format!("Failed to get dcgmInit symbol: {}", e)),
            };

            let result = init();
            if result != DCGM_ST_OK {
                return Err(format!("Failed to initialize DCGM: {}", result));
            }

            // Connect to DCGM
            let connect: Symbol<
                unsafe extern "C" fn(*const c_char, *mut dcgmHandle_t) -> dcgmReturn_t,
            > = match lib.get(b"dcgmConnect") {
                Ok(f) => f,
                Err(e) => return Err(format!("Failed to get dcgmConnect symbol: {}", e)),
            };

            let c_addr = CString::new(host_address).unwrap();
            let mut handle: dcgmHandle_t = ptr::null_mut();

            let result = connect(c_addr.as_ptr(), &mut handle);
            if result != DCGM_ST_OK {
                return Err(format!("Failed to connect to DCGM: {}", result));
            }

            Ok(DcgmLib { lib, handle })
        }
    }

    // Helper function to get error string
    fn error_string(&self, error_code: dcgmReturn_t) -> String {
        unsafe {
            let error_string: Symbol<unsafe extern "C" fn(dcgmReturn_t) -> *const c_char> =
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

    // Get specific GPU group information
    fn get_device_info(&self) -> Result<(), String> {
        unsafe {
            println!("DEBUG: Getting GPU device information");

            let get_all_devices: Symbol<
                unsafe extern "C" fn(
                    dcgmHandle_t,
                    *mut c_uint,
                    *mut c_uint,
                    c_uint,
                ) -> dcgmReturn_t,
            > = match self.lib.get(b"dcgmGetAllDevices") {
                Ok(f) => f,
                Err(e) => return Err(format!("Failed to get dcgmGetAllDevices symbol: {}", e)),
            };

            let mut gpu_ids: Vec<c_uint> = vec![0; DCGM_MAX_NUM_DEVICES as usize];
            let mut count: c_uint = 0;

            let result = get_all_devices(
                self.handle,
                &mut count,
                gpu_ids.as_mut_ptr(),
                DCGM_MAX_NUM_DEVICES as c_uint,
            );

            if result != DCGM_ST_OK {
                return Err(format!(
                    "Failed to get all devices: {}: {}",
                    result,
                    self.error_string(result)
                ));
            }

            println!("Found {} GPUs:", count);
            for i in 0..count as usize {
                println!("  GPU {}: ID {}", i, gpu_ids[i]);
            }

            Ok(())
        }
    }

    fn get_supported_metric_groups(
        &self,
        gpu_id: u32,
        gmg: &mut dcgmProfGetMetricGroups_t,
    ) -> Result<(), String> {
        unsafe {
            let func: Symbol<
                unsafe extern "C" fn(dcgmHandle_t, &mut dcgmProfGetMetricGroups_t) -> dcgmReturn_t,
            > = match self.lib.get(b"dcgmProfGetSupportedMetricGroups") {
                Ok(f) => f,
                Err(e) => {
                    return Err(format!(
                        "Failed to get dcgmProfGetSupportedMetricGroups symbol: {}",
                        e
                    ))
                }
            };

            gmg.version = dcgmProfGetMetricGroups_version3; // Set version before calling
            gmg.gpuId = gpu_id;
            gmg.numMetricGroups = 0; // Initialize output field

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

    pub fn get_supported_prof_metric_ids(&self) -> Result<HashSet<u16>, String> {
        log::info!("Querying DCGM for supported profiling metric field IDs...");
        let mut supported_ids: HashSet<u16> = HashSet::new();
        let mut gmg: dcgmProfGetMetricGroups_t = unsafe { std::mem::zeroed() };

        // Call the FFI wrapper
        self.get_supported_metric_groups(0, &mut gmg)?; // Use gpuId = 0

        log::debug!("Found {} metric groups.", gmg.numMetricGroups);

        // Iterate through groups and field IDs
        for i in 0..gmg.numMetricGroups as usize {
            if i >= DCGM_PROF_MAX_NUM_GROUPS_V2 {
                break;
            } // Bounds check
            let mg_info = &gmg.metricGroups[i];

            for j in 0..mg_info.numFieldIds as usize {
                if j >= DCGM_MAX_FIELD_IDS_PER_FIELD_GROUP {
                    break;
                } // Bounds check
                let field_id = mg_info.fieldIds[j];
                supported_ids.insert(field_id);
            }
        }

        log::info!(
            "Found {} unique supported profiling field IDs.",
            supported_ids.len()
        );
        Ok(supported_ids)
    }

    fn create_field_group(&self, field_ids: &[u16]) -> Result<dcgmFieldGrp_t, String> {
        unsafe {
            println!(
                "DEBUG: Creating field group with field_ids: {:?}",
                field_ids
            );

            let create_field_group: Symbol<
                unsafe extern "C" fn(
                    dcgmHandle_t,
                    c_int,
                    *const u16,
                    *const c_char,
                    *mut dcgmFieldGrp_t,
                ) -> dcgmReturn_t,
            > = match self.lib.get(b"dcgmFieldGroupCreate") {
                Ok(f) => {
                    println!("DEBUG: Found dcgmFieldGroupCreate symbol");
                    f
                }
                Err(e) => return Err(format!("Failed to get dcgmFieldGroupCreate symbol: {}", e)),
            };

            let group_name = CString::new("rust_dcgm_field_group").unwrap();
            let mut field_group_id: dcgmFieldGrp_t = 0;

            println!(
                "DEBUG: Calling dcgmFieldGroupCreate with {} fields",
                field_ids.len()
            );
            let result = create_field_group(
                self.handle,
                field_ids.len() as c_int,
                field_ids.as_ptr(),
                group_name.as_ptr(),
                &mut field_group_id,
            );
            println!(
                "DEBUG: dcgmFieldGroupCreate returned {} with field_group_id={}",
                result, field_group_id
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

    fn watch_fields(
        &self,
        group_id: dcgmGpuGrp_t,
        field_group_id: dcgmFieldGrp_t,
        update_freq_us: i64,
        max_keep_age: f64,
        max_keep_samples: i32,
    ) -> Result<(), String> {
        unsafe {
            println!("DEBUG: Setting up field watches");
            println!("DEBUG: group_id={}, field_group_id={}, update_freq_us={}, max_keep_age={}, max_keep_samples={}",
                     group_id, field_group_id, update_freq_us, max_keep_age, max_keep_samples);

            let watch_fields: Symbol<
                unsafe extern "C" fn(
                    dcgmHandle_t,
                    dcgmGpuGrp_t,
                    dcgmFieldGrp_t,
                    i64,
                    f64,
                    i32,
                ) -> dcgmReturn_t,
            > = match self.lib.get(b"dcgmWatchFields") {
                Ok(f) => {
                    println!("DEBUG: Found dcgmWatchFields symbol");
                    f
                }
                Err(e) => return Err(format!("Failed to get dcgmWatchFields symbol: {}", e)),
            };

            println!("DEBUG: Calling dcgmWatchFields");
            let result = watch_fields(
                self.handle,
                group_id,
                field_group_id,
                update_freq_us,
                max_keep_age,
                max_keep_samples,
            );
            println!("DEBUG: dcgmWatchFields returned {}", result);

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

    fn update_all_fields(&self, wait_for_update: i32) -> Result<(), String> {
        unsafe {
            println!(
                "DEBUG: Updating all fields with wait_for_update={}",
                wait_for_update
            );

            let update_all_fields: Symbol<unsafe extern "C" fn(dcgmHandle_t, i32) -> dcgmReturn_t> =
                match self.lib.get(b"dcgmUpdateAllFields") {
                    Ok(f) => {
                        println!("DEBUG: Found dcgmUpdateAllFields symbol");
                        f
                    }
                    Err(e) => {
                        return Err(format!("Failed to get dcgmUpdateAllFields symbol: {}", e))
                    }
                };

            println!("DEBUG: Calling dcgmUpdateAllFields");
            let result = update_all_fields(self.handle, wait_for_update);
            println!("DEBUG: dcgmUpdateAllFields returned {}", result);

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

    fn get_latest_values(
        &self,
        group_id: dcgmGpuGrp_t,
        field_group_id: dcgmFieldGrp_t,
        callback: DcgmFieldValueEnumeration,
        user_data: *mut c_void,
    ) -> Result<(), String> {
        unsafe {
            println!(
                "DEBUG: Calling get_latest_values with group_id={}, field_group_id={}",
                group_id, field_group_id
            );
            println!("DEBUG: user_data pointer: {:?}", user_data);

            let get_latest_values: Symbol<
                unsafe extern "C" fn(
                    dcgmHandle_t,
                    dcgmGpuGrp_t,
                    dcgmFieldGrp_t,
                    DcgmFieldValueEnumeration,
                    *mut c_void,
                ) -> dcgmReturn_t,
            > = match self.lib.get(b"dcgmGetLatestValues_v2") {
                Ok(f) => {
                    println!("DEBUG: Found dcgmGetLatestValues_v2 symbol");
                    f
                }
                Err(e) => {
                    return Err(format!(
                        "Failed to get dcgmGetLatestValues_v2 symbol: {}",
                        e
                    ))
                }
            };

            println!("DEBUG: About to call dcgmGetLatestValues_v2");
            let result =
                get_latest_values(self.handle, group_id, field_group_id, callback, user_data);
            println!("DEBUG: dcgmGetLatestValues_v2 returned {}", result);

            // Handle different error cases
            if result == DCGM_ST_NO_DATA {
                println!("No data available yet (DCGM_ST_NO_DATA). The profiling metrics might need time to be collected.");
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
                println!("DEBUG: Successfully got latest values");
            }

            Ok(())
        }
    }
}

// --- Define messages for communication ---
type DcgmMetricsResult = Result<Vec<(String, MetricValue)>, String>;

enum DcgmCommand {
    GetMetrics {
        responder: oneshot::Sender<DcgmMetricsResult>,
    },
    Shutdown,
}

// --- The client struct (thread-safe) ---
#[derive(Clone)]
pub struct DcgmClient {
    sender: mpsc::Sender<DcgmCommand>,
}

impl DcgmClient {
    pub fn new() -> Result<Self, String> {
        let lib_path = "libdcgm.so.4".to_string();
        let host_address = "localhost:5555".to_string();

        // Define the list of metrics we *want* to monitor
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

        let (sender, receiver) = mpsc::channel();

        let thread_desired_field_ids = desired_field_ids.clone();

        // --- Spawn Dedicated OS Thread ---
        thread::Builder::new()
            .name("dcgm-worker-sync".to_string())
            .spawn(move || {
                // --- STEP 1: Initialize DCGM *Inside* the Thread (same as before) ---
                log::info!("Initializing DCGM library in dedicated sync worker thread...");
                let dcgm = match DcgmLib::new(&lib_path, &host_address) {
                    /* ... error handling ... */
                    Ok(lib) => lib,
                    Err(e) => {
                        log::debug!(
                            "Failed to initialize DCGM library: {}. Worker thread exiting.",
                            e
                        );
                        return;
                    }
                };

                // Get supported metric IDs
                // --- Get Supported IDs and Filter ---
                let actual_field_ids = match dcgm.get_supported_prof_metric_ids() {
                    Ok(supported_set) => {
                        // Filter desired IDs against the supported set
                        let filtered: Vec<u16> = thread_desired_field_ids
                            .into_iter()
                            .filter(|id| supported_set.contains(id))
                            .collect();
                        if filtered.is_empty() {
                            log::warn!("No desired DCGM profiling metrics are supported by the hardware/driver. DCGM profiling inactive.");
                        } else {
                            log::debug!("Filtered DCGM fields. Will monitor: {:?}", filtered);
                        }
                        filtered
                    }
                    Err(e) => {
                        log::error!("Failed to get supported DCGM fields: {}. Monitoring requested fields without filtering.", e);
                        // Fallback: Monitor all desired fields, hoping they work or fail gracefully later
                        thread_desired_field_ids
                    }
                };
                // --- End Filtering ---


                // Proceed only if we have fields to monitor
                if actual_field_ids.is_empty() {
                    log::warn!("No DCGM profiling fields to monitor after filtering. DCGM worker thread exiting.");
                    return; // Exit the thread if no fields can be monitored
                }

                let group_id = DCGM_GROUP_ALL_GPUS;
                let field_group_id = match dcgm.create_field_group(&actual_field_ids) {
                    /* ... error handling ... */
                    Ok(id) => id,
                    Err(e) => {
                        log::error!(
                            "Failed to create DCGM field group: {}. Worker thread exiting.",
                            e
                        );
                        return;
                    }
                };

                // Continuously watch the fields.
                if let Err(e) = dcgm.watch_fields(group_id, field_group_id, 5_000_000, 0.0, 2) {
                    /* ... error handling ... */
                    log::error!("Failed to set DCGM watches: {}. Worker thread exiting.", e);
                    return;
                }
                log::debug!("DCGM setup complete in sync worker thread.");

                // --- STEP 2: Create the Worker Struct ---
                // Takes ownership of the thread-local dcgm instance and sync receiver
                let mut worker = DcgmWorker::new(
                    dcgm,
                    actual_field_ids,
                    group_id,
                    field_group_id,
                    receiver, // Move the sync receiver
                );

                // --- STEP 3: Run the SYNC worker loop directly ---
                worker.run();

                log::info!("DCGM sync worker thread shutting down.");
                // Drop(dcgm) happens here
            })
            .map_err(|e| format!("Failed to spawn DCGM worker OS thread: {}", e))?;

        log::info!("DCGM sync worker OS thread spawned successfully.");

        // Return the client (sender end of the sync channel)
        Ok(Self { sender })
    }

    pub async fn get_metrics(&self) -> DcgmMetricsResult {
        let (tx, rx) = oneshot::channel();
        let command = DcgmCommand::GetMetrics { responder: tx };

        // Use blocking send (sender.send(...)) - should be okay if worker is responsive
        // Use try_send or send_timeout if blocking is a concern, but usually fine here.
        if self.sender.send(command).is_err() {
            // Error means the receiving end (worker thread) has hung up (likely panicked or shut down)
            return Err("DCGM worker task has shutdown".to_string());
        }

        // Await the response from the worker
        match rx.await {
            Ok(result) => result,
            Err(_) => Err("Failed to receive response from DCGM worker".to_string()),
        }
    }
}

impl Drop for DcgmClient {
    fn drop(&mut self) {
        // Send shutdown command to the worker thread
        // Ignore error if receiver already dropped
        let _ = self.sender.send(DcgmCommand::Shutdown);
    }
}

// Callback function that will be called for each value received from DCGM.
// It needs access to a place to store results *within the worker's context*
extern "C" fn field_value_callback(
    entity_group_id: dcgm_field_entity_group_t,
    entity_id: dcgm_field_eid_t,
    values: *mut dcgmFieldValue_v1,
    values_count: c_int,
    user_data: *mut c_void, // This will point to a `&mut Vec<(String, MetricValue)>`
) -> c_int {
    // Basic safety checks
    if user_data.is_null() || values.is_null() || values_count <= 0 {
        // Maybe log an error here if possible, but avoid panicking in C callback
        return if user_data.is_null() { 1 } else { 0 }; // Indicate error if user_data is null
    }

    // Cast user_data back to the mutable vector reference
    // This is unsafe, relying on the caller (`collect_metrics`) providing the correct pointer
    let metrics_vec: &mut Vec<(String, MetricValue)> =
        unsafe { &mut *(user_data as *mut Vec<(String, MetricValue)>) };

    let entity_type = match entity_group_id {
        DCGM_FE_GPU => "gpu",
        DCGM_FE_VGPU => "gpu", // TODO: Handle VGPU differently if needed.
        _ => "unknown",
    };

    unsafe {
        let values_slice = std::slice::from_raw_parts(values, values_count as usize);

        for value in values_slice {
            if value.status != DCGM_ST_OK {
                // Skip unavailable/error values, or handle differently
                continue;
            }

            let field_id = value.field_id;
            let field_type = value.field_type;

            let metric_value_opt: Option<MetricValue> = match field_type as u32 {
                DCGM_FT_DOUBLE | DCGM_FT_DOUBLE_BLANK => {
                    let dbl = value.value.dbl;
                    // DCGM often uses large negative numbers or specific patterns for N/A
                    // Adjust this condition based on observed DCGM behavior for blank values
                    if value.status == DCGM_ST_OK && !dbl.is_nan() && dbl.abs() < 1e19 {
                        // Check status and avoid huge numbers
                        Some(MetricValue::Float(dbl))
                    } else {
                        None // Treat as unavailable
                    }
                }
                DCGM_FT_INT64 | DCGM_FT_TIMESTAMP => {
                    let i64_val = value.value.i64;
                    // DCGM often uses large negative numbers or specific patterns for N/A
                    if value.status == DCGM_ST_OK && i64_val > -1_000_000_000_000 {
                        // Check status and avoid specific large negative numbers
                        Some(MetricValue::Int(i64_val))
                    } else {
                        None // Treat as unavailable
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
                // DCGM_FT_BINARY => None, // TODO: Decide how to handle binary if needed
                _ => None, // Unknown type
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
                // Create unique key per GPU: e.g., "gpu.0.smActive"
                let metric_key = format!("{}.{}.{}", entity_type, entity_id, base_name);
                metrics_vec.push((metric_key, metric_value));
            }
        }
    }
    0 // Indicate success
}

// --- The worker task logic ---
struct DcgmWorker {
    dcgm: DcgmLib,
    field_ids: Vec<u16>,
    group_id: u32,
    field_group_id: u32,
    receiver: mpsc::Receiver<DcgmCommand>,
}

impl DcgmWorker {
    fn new(
        dcgm: DcgmLib,
        field_ids: Vec<u16>,
        group_id: u32,
        field_group_id: u32,
        receiver: mpsc::Receiver<DcgmCommand>,
    ) -> Self {
        DcgmWorker {
            dcgm,
            field_ids,
            group_id,
            field_group_id,
            receiver,
        }
    }

    fn run(&mut self) {
        log::info!("DCGM worker SYNC run loop started.");

        // Loop over the blocking receiver
        for command in &self.receiver {
            // Iterating blocks until a message or channel closes
            match command {
                DcgmCommand::GetMetrics { responder } => {
                    // collect_metrics is already synchronous
                    let result = self.collect_metrics();
                    // Send the result back via the oneshot channel
                    // Ignore error if responder doesn't care anymore
                    let _ = responder.send(result);
                }
                DcgmCommand::Shutdown => {
                    log::info!("DCGM worker received shutdown command.");
                    break; // Exit the loop
                }
            }
        }
        // Receiver iterator ends when the channel is closed OR after a break.
        log::info!("DCGM worker SYNC run loop finished.");
        // DcgmLib's Drop implementation will handle cleanup here when worker goes out of scope
    }

    // This performs the actual DCGM interaction
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

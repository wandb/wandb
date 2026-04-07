//! Probes libtpu SDK and dumps raw metric data for debugging.
//!
//! Usage: cargo run --example probe_tpu_sdk [-- /path/to/libtpu.so]

use libloading::{Library, Symbol};
use std::ffi::{CStr, CString, c_void};
use std::os::raw::c_char;

const OFF_ERROR_MESSAGE: usize = 0x08;
const OFF_DESTROY_ERROR: usize = 0x10;
const OFF_CREATE_CLIENT: usize = 0x20;
const OFF_DESTROY_CLIENT: usize = 0x28;
const OFF_GET_METRIC: usize = 0x50;
const OFF_GET_METRIC_DESC: usize = 0x58;
const OFF_GET_METRIC_VALS: usize = 0x60;

type ApiFn = unsafe extern "C" fn(*mut c_void) -> *mut c_void;

unsafe fn vtable_fn(api: *const u8, offset: usize) -> ApiFn {
    let slot = std::ptr::read_unaligned(api.add(offset) as *const *const ());
    std::mem::transmute::<*const (), ApiFn>(slot)
}

unsafe fn read_error(api: *const u8, err: *mut c_void) -> String {
    #[repr(C)]
    struct Args {
        error: *mut c_void,
        message: *const c_char,
        message_len: usize,
    }
    let mut args = Args { error: err, message: std::ptr::null(), message_len: 0 };
    vtable_fn(api, OFF_ERROR_MESSAGE)((&raw mut args) as *mut c_void);
    let msg = if !args.message.is_null() && args.message_len > 0 {
        let s = std::slice::from_raw_parts(args.message as *const u8, args.message_len);
        String::from_utf8_lossy(s).into_owned()
    } else {
        "unknown".into()
    };
    #[repr(C)]
    struct D { error: *mut c_void }
    let mut d = D { error: err };
    vtable_fn(api, OFF_DESTROY_ERROR)((&raw mut d) as *mut c_void);
    msg
}

const METRICS: &[&str] = &[
    "tensorcore_utilization",
    "tensorcore_util",
    "duty_cycle_pct",
    "hbm_capacity_total",
    "hbm_capacity_usage",
    "buffer_transfer_latency",
    "inbound_buffer_transfer_latency",
    "host_to_device_transfer_latency",
    "device_to_host_transfer_latency",
    "collective_e2e_latency",
    "host_compute_latency",
    "grpc_tcp_min_round_trip_times",
    "grpc_tcp_min_rtt",
    "grpc_tcp_delivery_rates",
    "grpc_tcp_delivery_rate",
    "hlo_exec_timing",
    "hlo_queue_size",
];

fn main() {
    let path = std::env::args().nth(1).unwrap_or_else(|| {
        // Try common locations
        for p in &[
            "/lib/libtpu.so",
            "/usr/lib/libtpu.so",
        ] {
            if std::path::Path::new(p).exists() {
                return p.to_string();
            }
        }
        // Try glob for venv
        if let Ok(home) = std::env::var("HOME") {
            for pattern in &[
                format!("{home}/.venv/lib/python*/site-packages/libtpu/libtpu.so"),
                format!("{home}/.local/lib/python*/site-packages/libtpu/libtpu.so"),
            ] {
                if let Ok(matches) = glob::glob(pattern) {
                    for m in matches.flatten() {
                        return m.to_string_lossy().into_owned();
                    }
                }
            }
        }
        eprintln!("libtpu.so not found; pass path as argument");
        std::process::exit(1);
    });

    println!("Loading: {path}");
    let lib = unsafe { Library::new(&path).expect("dlopen failed") };
    let api: *const u8 = unsafe {
        let get: Symbol<unsafe extern "C" fn() -> *const u8> =
            lib.get(b"GetLibtpuSdkApi").expect("symbol not found");
        get()
    };
    assert!(!api.is_null(), "GetLibtpuSdkApi returned NULL");

    let h0 = unsafe { std::ptr::read(api as *const u32) };
    let h1 = unsafe { std::ptr::read(api.add(4) as *const u32) };
    println!("Header: h0={h0}, h1={h1}");

    // Create client
    #[repr(C)]
    struct CreateArgs { client: *mut c_void }
    let client = unsafe {
        let mut a = CreateArgs { client: std::ptr::null_mut() };
        let err = vtable_fn(api, OFF_CREATE_CLIENT)((&raw mut a) as *mut c_void);
        if !err.is_null() {
            eprintln!("CreateClient error: {}", read_error(api, err));
            std::process::exit(1);
        }
        a.client
    };
    println!("Client: {:?}\n", client);

    for name in METRICS {
        print_metric(api, client, name);
    }

    // Cleanup
    #[repr(C)]
    struct DestroyArgs { client: *mut c_void }
    unsafe {
        let mut a = DestroyArgs { client };
        vtable_fn(api, OFF_DESTROY_CLIENT)((&raw mut a) as *mut c_void);
    }
}

fn print_metric(api: *const u8, client: *mut c_void, name: &str) {
    let cname = CString::new(name).unwrap();

    #[repr(C)]
    struct GetMetricArgs {
        client: *mut c_void,
        name: *const c_char,
        metric: *mut c_void,
    }

    let metric = unsafe {
        let mut a = GetMetricArgs {
            client,
            name: cname.as_ptr(),
            metric: std::ptr::null_mut(),
        };
        let err = vtable_fn(api, OFF_GET_METRIC)((&raw mut a) as *mut c_void);
        if !err.is_null() {
            let msg = read_error(api, err);
            println!("--- {name}: ERROR: {msg}");
            return;
        }
        if a.metric.is_null() {
            println!("--- {name}: null handle");
            return;
        }
        a.metric
    };

    // Description
    #[repr(C)]
    struct DescArgs {
        metric: *mut c_void,
        desc: *const c_char,
        desc_len: usize,
    }
    let desc = unsafe {
        let mut a = DescArgs { metric, desc: std::ptr::null(), desc_len: 0 };
        let err = vtable_fn(api, OFF_GET_METRIC_DESC)((&raw mut a) as *mut c_void);
        if !err.is_null() {
            format!("desc error: {}", read_error(api, err))
        } else if a.desc.is_null() || a.desc_len == 0 {
            "(empty)".into()
        } else {
            let s = std::slice::from_raw_parts(a.desc as *const u8, a.desc_len);
            String::from_utf8_lossy(s).into_owned()
        }
    };

    // Values
    #[repr(C)]
    struct ValsArgs {
        metric: *mut c_void,
        values: *const *const c_char,
        count: usize,
    }
    let values: Vec<String> = unsafe {
        let mut a = ValsArgs { metric, values: std::ptr::null(), count: 0 };
        let err = vtable_fn(api, OFF_GET_METRIC_VALS)((&raw mut a) as *mut c_void);
        if !err.is_null() {
            println!("--- {name}: values error: {}", read_error(api, err));
            return;
        }
        if a.count == 0 || a.values.is_null() {
            vec![]
        } else {
            (0..a.count).map(|i| {
                let p = *a.values.add(i);
                if p.is_null() { "(null)".into() }
                else { CStr::from_ptr(p).to_string_lossy().into_owned() }
            }).collect()
        }
    };

    println!("--- {name}");
    println!("    desc:   {desc}");
    println!("    count:  {}", values.len());
    for (i, v) in values.iter().enumerate() {
        println!("    [{i}]: {v:?}");
    }
    println!();
}

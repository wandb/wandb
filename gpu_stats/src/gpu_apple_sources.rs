/*
https://github.com/vladkens/macmon

MIT License

Copyright (c) 2024 vladkens

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
#![allow(non_upper_case_globals)]
#![allow(dead_code)]

use std::{
    collections::HashMap,
    marker::{PhantomData, PhantomPinned},
    mem::{size_of, MaybeUninit},
    os::raw::c_void,
    ptr::null,
};

use core_foundation::{
    array::{CFArrayGetCount, CFArrayGetValueAtIndex, CFArrayRef},
    base::{kCFAllocatorDefault, kCFAllocatorNull, CFAllocatorRef, CFRange, CFRelease, CFTypeRef},
    data::{CFDataGetBytes, CFDataGetLength, CFDataRef},
    dictionary::{
        kCFTypeDictionaryKeyCallBacks, kCFTypeDictionaryValueCallBacks, CFDictionaryCreate,
        CFDictionaryCreateMutableCopy, CFDictionaryGetCount, CFDictionaryGetKeysAndValues,
        CFDictionaryGetValue, CFDictionaryRef, CFMutableDictionaryRef,
    },
    number::{kCFNumberSInt32Type, CFNumberCreate, CFNumberRef},
    string::{
        kCFStringEncodingUTF8, CFStringCreateWithBytesNoCopy, CFStringGetCString, CFStringRef,
    },
};

pub type WithError<T> = Result<T, Box<dyn std::error::Error>>;
pub type CVoidRef = *const std::ffi::c_void;

// MARK: CFUtils

pub fn cfnum(val: i32) -> CFNumberRef {
    unsafe {
        CFNumberCreate(
            kCFAllocatorDefault,
            kCFNumberSInt32Type,
            &val as *const i32 as _,
        )
    }
}

pub fn cfstr(val: &str) -> CFStringRef {
    // this creates broken objects if string len > 9
    // CFString::from_static_string(val).as_concrete_TypeRef()
    // CFString::new(val).as_concrete_TypeRef()

    unsafe {
        CFStringCreateWithBytesNoCopy(
            kCFAllocatorDefault,
            val.as_ptr(),
            val.len() as isize,
            kCFStringEncodingUTF8,
            0,
            kCFAllocatorNull,
        )
    }
}

pub fn from_cfstr(val: CFStringRef) -> String {
    unsafe {
        let mut buf = Vec::with_capacity(128);
        if CFStringGetCString(val, buf.as_mut_ptr(), 128, kCFStringEncodingUTF8) == 0 {
            panic!("Failed to convert CFString to CString");
        }
        std::ffi::CStr::from_ptr(buf.as_ptr())
            .to_string_lossy()
            .to_string()
    }
}

pub fn cfdict_keys(dict: CFDictionaryRef) -> Vec<String> {
    unsafe {
        let count = CFDictionaryGetCount(dict) as usize;
        let mut keys: Vec<CFStringRef> = Vec::with_capacity(count);
        let mut vals: Vec<CFTypeRef> = Vec::with_capacity(count);
        CFDictionaryGetKeysAndValues(dict, keys.as_mut_ptr() as _, vals.as_mut_ptr());
        keys.set_len(count);
        vals.set_len(count);

        keys.iter().map(|k| from_cfstr(*k as _)).collect()
    }
}

pub fn cfdict_get_val(dict: CFDictionaryRef, key: &str) -> Option<CFTypeRef> {
    unsafe {
        let key = cfstr(key);
        let val = CFDictionaryGetValue(dict, key as _);
        CFRelease(key as _);

        match val {
            _ if val.is_null() => None,
            _ => Some(val),
        }
    }
}

// MARK: IOReport Bindings

#[link(name = "IOKit", kind = "framework")]
#[rustfmt::skip]
extern "C" {
  fn IOServiceMatching(name: *const i8) -> CFMutableDictionaryRef;
  fn IOServiceGetMatchingServices(mainPort: u32, matching: CFDictionaryRef, existing: *mut u32) -> i32;
  fn IOIteratorNext(iterator: u32) -> u32;
  fn IORegistryEntryGetName(entry: u32, name: *mut i8) -> i32;
  fn IORegistryEntryCreateCFProperties(entry: u32, properties: *mut CFMutableDictionaryRef, allocator: CFAllocatorRef, options: u32) -> i32;
  fn IOObjectRelease(obj: u32) -> u32;
}

#[repr(C)]
struct IOReportSubscription {
    _data: [u8; 0],
    _phantom: PhantomData<(*mut u8, PhantomPinned)>,
}

type IOReportSubscriptionRef = *const IOReportSubscription;

#[link(name = "IOReport", kind = "dylib")]
#[rustfmt::skip]
extern "C" {
  fn IOReportCopyAllChannels(a: u64, b: u64) -> CFDictionaryRef;
  fn IOReportCopyChannelsInGroup(a: CFStringRef, b: CFStringRef, c: u64, d: u64, e: u64) -> CFDictionaryRef;
  fn IOReportMergeChannels(a: CFDictionaryRef, b: CFDictionaryRef, nil: CFTypeRef);
  fn IOReportCreateSubscription(a: CVoidRef, b: CFMutableDictionaryRef, c: *mut CFMutableDictionaryRef, d: u64, b: CFTypeRef) -> IOReportSubscriptionRef;
  fn IOReportCreateSamples(a: IOReportSubscriptionRef, b: CFMutableDictionaryRef, c: CFTypeRef) -> CFDictionaryRef;
  fn IOReportCreateSamplesDelta(a: CFDictionaryRef, b: CFDictionaryRef, c: CFTypeRef) -> CFDictionaryRef;
  fn IOReportChannelGetGroup(a: CFDictionaryRef) -> CFStringRef;
  fn IOReportChannelGetSubGroup(a: CFDictionaryRef) -> CFStringRef;
  fn IOReportChannelGetChannelName(a: CFDictionaryRef) -> CFStringRef;
  fn IOReportSimpleGetIntegerValue(a: CFDictionaryRef, b: i32) -> i64;
  fn IOReportChannelGetUnitLabel(a: CFDictionaryRef) -> CFStringRef;
  fn IOReportStateGetCount(a: CFDictionaryRef) -> i32;
  fn IOReportStateGetNameForIndex(a: CFDictionaryRef, b: i32) -> CFStringRef;
  fn IOReportStateGetResidency(a: CFDictionaryRef, b: i32) -> i64;
}

// MARK: IOReport helpers

fn cfio_get_group(item: CFDictionaryRef) -> String {
    match unsafe { IOReportChannelGetGroup(item) } {
        x if x.is_null() => String::new(),
        x => from_cfstr(x),
    }
}

fn cfio_get_subgroup(item: CFDictionaryRef) -> String {
    match unsafe { IOReportChannelGetSubGroup(item) } {
        x if x.is_null() => String::new(),
        x => from_cfstr(x),
    }
}

fn cfio_get_channel(item: CFDictionaryRef) -> String {
    match unsafe { IOReportChannelGetChannelName(item) } {
        x if x.is_null() => String::new(),
        x => from_cfstr(x),
    }
}

pub fn cfio_get_props(entry: u32, name: String) -> WithError<CFDictionaryRef> {
    unsafe {
        let mut props: MaybeUninit<CFMutableDictionaryRef> = MaybeUninit::uninit();
        if IORegistryEntryCreateCFProperties(entry, props.as_mut_ptr(), kCFAllocatorDefault, 0) != 0
        {
            return Err(format!("Failed to get properties for {}", name).into());
        }

        Ok(props.assume_init())
    }
}

pub fn cfio_get_residencies(item: CFDictionaryRef) -> Vec<(String, i64)> {
    let count = unsafe { IOReportStateGetCount(item) };
    let mut res = vec![];

    for i in 0..count {
        let name = unsafe { IOReportStateGetNameForIndex(item, i) };
        let val = unsafe { IOReportStateGetResidency(item, i) };
        res.push((from_cfstr(name), val));
    }

    res
}

pub fn cfio_watts(item: CFDictionaryRef, unit: &String, duration: u64) -> WithError<f32> {
    let val = unsafe { IOReportSimpleGetIntegerValue(item, 0) } as f32;
    let val = val / (duration as f32 / 1000.0);
    match unit.as_str() {
        "mJ" => Ok(val / 1e3f32),
        "uJ" => Ok(val / 1e6f32),
        "nJ" => Ok(val / 1e9f32),
        _ => Err(format!("Invalid energy unit: {}", unit).into()),
    }
}

// MARK: IOServiceIterator

pub struct IOServiceIterator {
    existing: u32,
}

impl IOServiceIterator {
    pub fn new(service_name: &str) -> WithError<Self> {
        let service_name = std::ffi::CString::new(service_name).unwrap();
        let existing = unsafe {
            let service = IOServiceMatching(service_name.as_ptr() as _);
            let mut existing = 0;
            if IOServiceGetMatchingServices(0, service, &mut existing) != 0 {
                return Err(format!("{} not found", service_name.to_string_lossy()).into());
            }
            existing
        };

        Ok(Self { existing })
    }
}

impl Drop for IOServiceIterator {
    fn drop(&mut self) {
        unsafe {
            IOObjectRelease(self.existing);
        }
    }
}

impl Iterator for IOServiceIterator {
    type Item = (u32, String);

    fn next(&mut self) -> Option<Self::Item> {
        let next = unsafe { IOIteratorNext(self.existing) };
        if next == 0 {
            return None;
        }

        let mut name = [0; 128]; // 128 defined in apple docs
        if unsafe { IORegistryEntryGetName(next, name.as_mut_ptr()) } != 0 {
            return None;
        }

        let name = unsafe { std::ffi::CStr::from_ptr(name.as_ptr()) };
        let name = name.to_string_lossy().to_string();
        Some((next, name))
    }
}

// MARK: IOReportIterator

pub struct IOReportIterator {
    sample: CFDictionaryRef,
    index: isize,
    items: CFArrayRef,
    items_size: isize,
}

impl IOReportIterator {
    pub fn new(data: CFDictionaryRef) -> Self {
        let items = cfdict_get_val(data, "IOReportChannels").unwrap() as CFArrayRef;
        let items_size = unsafe { CFArrayGetCount(items) } as isize;
        Self {
            sample: data,
            items,
            items_size,
            index: 0,
        }
    }
}

impl Drop for IOReportIterator {
    fn drop(&mut self) {
        unsafe {
            CFRelease(self.sample as _);
        }
    }
}

#[derive(Debug)]
pub struct IOReportIteratorItem {
    pub group: String,
    pub subgroup: String,
    pub channel: String,
    pub unit: String,
    pub item: CFDictionaryRef,
}

impl Iterator for IOReportIterator {
    type Item = IOReportIteratorItem;

    fn next(&mut self) -> Option<Self::Item> {
        if self.index >= self.items_size {
            return None;
        }

        let item = unsafe { CFArrayGetValueAtIndex(self.items, self.index) } as CFDictionaryRef;

        let group = cfio_get_group(item);
        let subgroup = cfio_get_subgroup(item);
        let channel = cfio_get_channel(item);
        let unit = from_cfstr(unsafe { IOReportChannelGetUnitLabel(item) })
            .trim()
            .to_string();

        self.index += 1;
        Some(IOReportIteratorItem {
            group,
            subgroup,
            channel,
            unit,
            item,
        })
    }
}

// MARK: RAM

pub fn libc_ram() -> WithError<(u64, u64)> {
    let (mut usage, mut total) = (0u64, 0u64);

    unsafe {
        let mut name = [libc::CTL_HW, libc::HW_MEMSIZE];
        let mut size = std::mem::size_of::<u64>();
        let ret_code = libc::sysctl(
            name.as_mut_ptr(),
            name.len() as _,
            &mut total as *mut _ as *mut _,
            &mut size,
            std::ptr::null_mut(),
            0,
        );

        if ret_code != 0 {
            return Err("Failed to get total memory".into());
        }
    }

    unsafe {
        let mut count: u32 = libc::HOST_VM_INFO64_COUNT as _;
        let mut stats = std::mem::zeroed::<libc::vm_statistics64>();

        let ret_code = libc::host_statistics64(
            libc::mach_host_self(),
            libc::HOST_VM_INFO64,
            &mut stats as *mut _ as *mut _,
            &mut count,
        );

        if ret_code != 0 {
            return Err("Failed to get memory stats".into());
        }

        let page_size_kb = libc::sysconf(libc::_SC_PAGESIZE) as u64;

        usage = (0
            + stats.active_count as u64
            + stats.inactive_count as u64
            + stats.wire_count as u64
            + stats.speculative_count as u64
            + stats.compressor_page_count as u64
            - stats.purgeable_count as u64
            - stats.external_page_count as u64
            + 0)
            * page_size_kb;
    }

    Ok((usage, total))
}

pub fn libc_swap() -> WithError<(u64, u64)> {
    let (mut usage, mut total) = (0u64, 0u64);

    unsafe {
        let mut name = [libc::CTL_VM, libc::VM_SWAPUSAGE];
        let mut size = std::mem::size_of::<libc::xsw_usage>();
        let mut xsw: libc::xsw_usage = std::mem::zeroed::<libc::xsw_usage>();

        let ret_code = libc::sysctl(
            name.as_mut_ptr(),
            name.len() as _,
            &mut xsw as *mut _ as *mut _,
            &mut size,
            std::ptr::null_mut(),
            0,
        );

        if ret_code != 0 {
            return Err("Failed to get swap usage".into());
        }

        usage = xsw.xsu_used;
        total = xsw.xsu_total;
    }

    Ok((usage, total))
}

// MARK: SockInfo

#[derive(Debug, Default, Clone)]
pub struct SocInfo {
    pub mac_model: String,
    pub chip_name: String,
    pub memory_gb: u8,
    pub ecpu_cores: u8,
    pub pcpu_cores: u8,
    pub ecpu_freqs: Vec<u32>,
    pub pcpu_freqs: Vec<u32>,
    pub gpu_cores: u8,
    pub gpu_freqs: Vec<u32>,
}

impl SocInfo {
    pub fn new() -> WithError<Self> {
        get_soc_info()
    }
}

// dynamic voltage and frequency scaling
pub fn get_dvfs_mhz(dict: CFDictionaryRef, key: &str) -> (Vec<u32>, Vec<u32>) {
    unsafe {
        let obj = cfdict_get_val(dict, key).unwrap() as CFDataRef;
        let obj_len = CFDataGetLength(obj);
        let obj_val = vec![0u8; obj_len as usize];
        CFDataGetBytes(obj, CFRange::init(0, obj_len), obj_val.as_ptr() as *mut u8);

        // obj_val is pairs of (freq, voltage) 4 bytes each
        let items_count = (obj_len / 8) as usize;
        let [mut freqs, mut volts] = [vec![0u32; items_count], vec![0u32; items_count]];
        for (i, x) in obj_val.chunks_exact(8).enumerate() {
            volts[i] = u32::from_le_bytes([x[4], x[5], x[6], x[7]]);
            freqs[i] = u32::from_le_bytes([x[0], x[1], x[2], x[3]]);
            freqs[i] = freqs[i] / 1000 / 1000; // as MHz
        }

        (volts, freqs)
    }
}

pub fn run_system_profiler() -> WithError<serde_json::Value> {
    // system_profiler -listDataTypes
    let out = std::process::Command::new("system_profiler")
        .args(&[
            "SPHardwareDataType",
            "SPDisplaysDataType",
            "SPSoftwareDataType",
            "-json",
        ])
        .output()?;

    let out = std::str::from_utf8(&out.stdout)?;
    let out = serde_json::from_str::<serde_json::Value>(out)?;
    Ok(out)
}

pub fn get_soc_info() -> WithError<SocInfo> {
    let out = run_system_profiler()?;
    let mut info = SocInfo::default();

    // SPHardwareDataType.0.chip_type
    let chip_name = out["SPHardwareDataType"][0]["chip_type"]
        .as_str()
        .unwrap()
        .to_string();

    // SPHardwareDataType.0.machine_model
    let mac_model = out["SPHardwareDataType"][0]["machine_model"]
        .as_str()
        .unwrap()
        .to_string();

    // SPHardwareDataType.0.physical_memory -> "x GB"
    let mem_gb = out["SPHardwareDataType"][0]["physical_memory"].as_str();
    let mem_gb = mem_gb
        .expect("No memory found")
        .strip_suffix(" GB")
        .unwrap();
    let mem_gb = mem_gb.parse::<u64>().unwrap();

    // SPHardwareDataType.0.number_processors -> "proc x:y:z"
    let cpu_cores = out["SPHardwareDataType"][0]["number_processors"].as_str();
    let cpu_cores = cpu_cores
        .expect("No CPU cores found")
        .strip_prefix("proc ")
        .unwrap();
    let cpu_cores = cpu_cores
        .split(':')
        .map(|x| x.parse::<u64>().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(cpu_cores.len(), 3, "Invalid number of CPU cores");
    let (ecpu_cores, pcpu_cores, _) = (cpu_cores[2], cpu_cores[1], cpu_cores[0]);

    let gpu_cores = match out["SPDisplaysDataType"][0]["sppci_cores"].as_str() {
        Some(x) => x.parse::<u64>().unwrap(),
        None => 0,
    };

    info.chip_name = chip_name;
    info.mac_model = mac_model;
    info.memory_gb = mem_gb as u8;
    info.gpu_cores = gpu_cores as u8;
    info.ecpu_cores = ecpu_cores as u8;
    info.pcpu_cores = pcpu_cores as u8;

    // cpu frequencies
    for (entry, name) in IOServiceIterator::new("AppleARMIODevice")? {
        if name == "pmgr" {
            let item = cfio_get_props(entry, name)?;
            // `strings /usr/bin/powermetrics | grep voltage-states` uses non sram keys
            // but their values are zero, so sram used here, its looks valid
            info.ecpu_freqs = get_dvfs_mhz(item, "voltage-states1-sram").1;
            info.pcpu_freqs = get_dvfs_mhz(item, "voltage-states5-sram").1;
            info.gpu_freqs = get_dvfs_mhz(item, "voltage-states9").1;
            unsafe { CFRelease(item as _) }
        }
    }

    if info.ecpu_freqs.len() == 0 || info.pcpu_freqs.len() == 0 {
        return Err("No CPU cores found".into());
    }

    Ok(info)
}

// MARK: IOReport

unsafe fn cfio_get_chan(items: Vec<(&str, Option<&str>)>) -> WithError<CFMutableDictionaryRef> {
    // if no items are provided, return all channels
    if items.len() == 0 {
        let c = IOReportCopyAllChannels(0, 0);
        let r = CFDictionaryCreateMutableCopy(kCFAllocatorDefault, CFDictionaryGetCount(c), c);
        CFRelease(c as _);
        return Ok(r);
    }

    let mut channels = vec![];
    for (group, subgroup) in items {
        let gname = cfstr(group);
        let sname = subgroup.map_or(null(), |x| cfstr(x));
        let chan = IOReportCopyChannelsInGroup(gname, sname, 0, 0, 0);
        channels.push(chan);

        CFRelease(gname as _);
        if subgroup.is_some() {
            CFRelease(sname as _);
        }
    }

    let chan = channels[0];
    for i in 1..channels.len() {
        IOReportMergeChannels(chan, channels[i], null());
    }

    let size = CFDictionaryGetCount(chan);
    let chan = CFDictionaryCreateMutableCopy(kCFAllocatorDefault, size, chan);

    for i in 0..channels.len() {
        CFRelease(channels[i] as _);
    }

    if cfdict_get_val(chan, "IOReportChannels").is_none() {
        return Err("Failed to get channels".into());
    }

    Ok(chan)
}

unsafe fn cfio_get_subs(chan: CFMutableDictionaryRef) -> WithError<IOReportSubscriptionRef> {
    let mut s: MaybeUninit<CFMutableDictionaryRef> = MaybeUninit::uninit();
    let rs =
        IOReportCreateSubscription(std::ptr::null(), chan, s.as_mut_ptr(), 0, std::ptr::null());
    if rs == std::ptr::null() {
        return Err("Failed to create subscription".into());
    }

    s.assume_init();
    Ok(rs)
}

pub struct IOReport {
    subs: IOReportSubscriptionRef,
    chan: CFMutableDictionaryRef,
}

impl IOReport {
    pub fn new(channels: Vec<(&str, Option<&str>)>) -> WithError<Self> {
        let chan = unsafe { cfio_get_chan(channels)? };
        let subs = unsafe { cfio_get_subs(chan)? };

        Ok(Self { subs, chan })
    }

    pub fn get_sample(&self, duration: u64) -> IOReportIterator {
        unsafe {
            let sample1 = IOReportCreateSamples(self.subs, self.chan, null());
            std::thread::sleep(std::time::Duration::from_millis(duration));
            let sample2 = IOReportCreateSamples(self.subs, self.chan, null());

            let sample3 = IOReportCreateSamplesDelta(sample1, sample2, null());
            CFRelease(sample1 as _);
            CFRelease(sample2 as _);
            IOReportIterator::new(sample3)
        }
    }
}

impl Drop for IOReport {
    fn drop(&mut self) {
        unsafe {
            CFRelease(self.chan as _);
            CFRelease(self.subs as _);
        }
    }
}

// MARK: IOHID Bindings
// referenced from: https://github.com/freedomtan/sensors/blob/master/sensors/sensors.m

#[repr(C)]
struct IOHIDServiceClient(libc::c_void);

#[repr(C)]
struct IOHIDEventSystemClient(libc::c_void);

#[repr(C)]
struct IOHIDEvent(libc::c_void);

type IOHIDServiceClientRef = *const IOHIDServiceClient;
type IOHIDEventSystemClientRef = *const IOHIDEventSystemClient;
type IOHIDEventRef = *const IOHIDEvent;

const kHIDPage_AppleVendor: i32 = 0xff00;
const kHIDUsage_AppleVendor_TemperatureSensor: i32 = 0x0005;

const kIOHIDEventTypeTemperature: i64 = 15;
const kIOHIDEventTypePower: i64 = 25;

#[link(name = "IOKit", kind = "framework")]
#[rustfmt::skip]
extern "C" {
  fn IOHIDEventSystemClientCreate(allocator: CFAllocatorRef) -> IOHIDEventSystemClientRef;
  fn IOHIDEventSystemClientSetMatching(a: IOHIDEventSystemClientRef, b: CFDictionaryRef) -> i32;
  fn IOHIDEventSystemClientCopyServices(a: IOHIDEventSystemClientRef) -> CFArrayRef;
  fn IOHIDServiceClientCopyProperty(a: IOHIDServiceClientRef, b: CFStringRef) -> CFStringRef;
  fn IOHIDServiceClientCopyEvent(a: IOHIDServiceClientRef, v0: i64, v1: i32, v2: i64) -> IOHIDEventRef;
  fn IOHIDEventGetFloatValue(event: IOHIDEventRef, field: i64) -> f64;
}

// MARK: IOHIDSensors

pub struct IOHIDSensors {
    sensors: CFDictionaryRef,
}

impl IOHIDSensors {
    pub fn new() -> WithError<Self> {
        let keys = vec![cfstr("PrimaryUsagePage"), cfstr("PrimaryUsage")];
        let nums = vec![
            cfnum(kHIDPage_AppleVendor),
            cfnum(kHIDUsage_AppleVendor_TemperatureSensor),
        ];

        let dict = unsafe {
            CFDictionaryCreate(
                kCFAllocatorDefault,
                keys.as_ptr() as _,
                nums.as_ptr() as _,
                2,
                &kCFTypeDictionaryKeyCallBacks,
                &kCFTypeDictionaryValueCallBacks,
            )
        };

        Ok(Self { sensors: dict })
    }

    pub fn get_metrics(&self) -> Vec<(String, f32)> {
        unsafe {
            let system = match IOHIDEventSystemClientCreate(kCFAllocatorDefault) {
                x if x.is_null() => return vec![],
                x => x,
            };

            IOHIDEventSystemClientSetMatching(system, self.sensors);

            let services = match IOHIDEventSystemClientCopyServices(system) {
                x if x.is_null() => return vec![],
                x => x,
            };

            let mut items = vec![] as Vec<(String, f32)>;
            for i in 0..CFArrayGetCount(services) {
                let sc = match CFArrayGetValueAtIndex(services, i) as IOHIDServiceClientRef {
                    x if x.is_null() => continue,
                    x => x,
                };

                let name = match IOHIDServiceClientCopyProperty(sc, cfstr("Product")) {
                    x if x.is_null() => continue,
                    x => from_cfstr(x),
                };

                let event = match IOHIDServiceClientCopyEvent(sc, kIOHIDEventTypeTemperature, 0, 0)
                {
                    x if x.is_null() => continue,
                    x => x,
                };

                let temp = IOHIDEventGetFloatValue(event, kIOHIDEventTypeTemperature << 16);
                CFRelease(event as _);
                items.push((name, temp as f32));
            }

            CFRelease(services as _);
            CFRelease(system as _);

            items.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
            items
        }
    }
}

impl Drop for IOHIDSensors {
    fn drop(&mut self) {
        unsafe {
            CFRelease(self.sensors as _);
        }
    }
}

// MARK: SMC Bindings

#[link(name = "IOKit", kind = "framework")]
extern "C" {
    fn mach_task_self() -> u32;
    fn IOServiceOpen(device: u32, a: u32, b: u32, c: *mut u32) -> i32;
    fn IOServiceClose(conn: u32) -> i32;
    fn IOConnectCallStructMethod(
        conn: u32,
        selector: u32,
        ival: *const c_void,
        isize: usize,
        oval: *mut c_void,
        osize: *mut usize,
    ) -> i32;
}

#[repr(C)]
#[derive(Debug, Default)]
pub struct KeyDataVer {
    pub major: u8,
    pub minor: u8,
    pub build: u8,
    pub reserved: u8,
    pub release: u16,
}

#[repr(C)]
#[derive(Debug, Default)]
pub struct PLimitData {
    pub version: u16,
    pub length: u16,
    pub cpu_p_limit: u32,
    pub gpu_p_limit: u32,
    pub mem_p_limit: u32,
}

#[repr(C)]
#[derive(Debug, Default, Clone, Copy)]
pub struct KeyInfo {
    pub data_size: u32,
    pub data_type: u32,
    pub data_attributes: u8,
}

#[repr(C)]
#[derive(Debug, Default)]
pub struct KeyData {
    pub key: u32,
    pub vers: KeyDataVer,
    pub p_limit_data: PLimitData,
    pub key_info: KeyInfo,
    pub result: u8,
    pub status: u8,
    pub data8: u8,
    pub data32: u32,
    pub bytes: [u8; 32],
}

#[derive(Debug, Clone)]
pub struct SensorVal {
    pub name: String,
    pub unit: String,
    pub data: Vec<u8>,
}

// MARK: SMC

pub struct SMC {
    conn: u32,
    keys: HashMap<u32, KeyInfo>,
}

impl SMC {
    pub fn new() -> WithError<Self> {
        let mut conn = 0;

        for (device, name) in IOServiceIterator::new("AppleSMC")? {
            if name == "AppleSMCKeysEndpoint" {
                let rs = unsafe { IOServiceOpen(device, mach_task_self(), 0, &mut conn) };
                if rs != 0 {
                    return Err(format!("IOServiceOpen: {}", rs).into());
                }
            }
        }

        Ok(Self {
            conn,
            keys: HashMap::new(),
        })
    }

    fn read(&self, input: &KeyData) -> WithError<KeyData> {
        let ival = input as *const _ as _;
        let ilen = size_of::<KeyData>();
        let mut oval = KeyData::default();
        let mut olen = size_of::<KeyData>();

        let rs = unsafe {
            IOConnectCallStructMethod(
                self.conn,
                2,
                ival,
                ilen,
                &mut oval as *mut _ as _,
                &mut olen,
            )
        };

        if rs != 0 {
            // println!("{:?}", input);
            return Err(format!("IOConnectCallStructMethod: {}", rs).into());
        }

        if oval.result == 132 {
            return Err("SMC key not found".into());
        }

        if oval.result != 0 {
            return Err(format!("SMC error: {}", oval.result).into());
        }

        Ok(oval)
    }

    pub fn key_by_index(&self, index: u32) -> WithError<String> {
        let ival = KeyData {
            data8: 8,
            data32: index,
            ..Default::default()
        };
        let oval = self.read(&ival)?;
        Ok(std::str::from_utf8(&oval.key.to_be_bytes())
            .unwrap()
            .to_string())
    }

    pub fn read_key_info(&mut self, key: &str) -> WithError<KeyInfo> {
        if key.len() != 4 {
            return Err("SMC key must be 4 bytes long".into());
        }

        // key is FourCC
        let key = key.bytes().fold(0, |acc, x| (acc << 8) + x as u32);
        if let Some(ki) = self.keys.get(&key) {
            // println!("cache hit for {}", key);
            return Ok(ki.clone());
        }

        let ival = KeyData {
            data8: 9,
            key,
            ..Default::default()
        };
        let oval = self.read(&ival)?;
        self.keys.insert(key, oval.key_info);
        Ok(oval.key_info)
    }

    pub fn read_val(&mut self, key: &str) -> WithError<SensorVal> {
        let name = key.to_string();

        let key_info = self.read_key_info(key)?;
        let key = key.bytes().fold(0, |acc, x| (acc << 8) + x as u32);
        // println!("{:?}", key_info);

        let ival = KeyData {
            data8: 5,
            key,
            key_info,
            ..Default::default()
        };
        let oval = self.read(&ival)?;
        // println!("{:?}", oval.bytes);

        Ok(SensorVal {
            name,
            unit: std::str::from_utf8(&key_info.data_type.to_be_bytes())
                .unwrap()
                .to_string(),
            data: oval.bytes[0..key_info.data_size as usize].to_vec(),
        })
    }

    pub fn read_all_keys(&mut self) -> WithError<Vec<String>> {
        let val = self.read_val("#KEY")?;
        let val = u32::from_be_bytes(val.data[0..4].try_into().unwrap());

        let mut keys = Vec::new();
        for i in 0..val {
            let key = self.key_by_index(i)?;
            let val = self.read_val(&key);
            if val.is_err() {
                continue;
            }

            let val = val.unwrap();
            keys.push(val.name);
        }

        Ok(keys)
    }
}

impl Drop for SMC {
    fn drop(&mut self) {
        unsafe {
            IOServiceClose(self.conn);
        }
    }
}

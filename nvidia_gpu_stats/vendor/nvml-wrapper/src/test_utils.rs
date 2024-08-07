use crate::Device;
use crate::NvLink;
use crate::Nvml;
use crate::Unit;

use crate::bitmasks::{device::*, event::*};

use crate::enum_wrappers::device::*;
use crate::enums::device::BusType;
use crate::enums::device::DeviceArchitecture;
use crate::enums::device::PcieLinkMaxSpeed;
use crate::enums::device::PowerSource;
use crate::enums::unit::*;
use crate::error::NvmlError;
use crate::event::EventSet;
use std::fmt::Debug;

use crate::struct_wrappers::nv_link::*;
use crate::struct_wrappers::{device::*, event::*, unit::*, *};

use crate::structs::device::*;
use crate::structs::nv_link::*;

#[cfg(target_os = "windows")]
use crate::structs::device::DriverModelState;

pub trait ShouldPrint: Debug {
    fn should_print(&self) -> bool {
        true
    }
}

impl ShouldPrint for () {
    fn should_print(&self) -> bool {
        false
    }
}

impl<'nvml> ShouldPrint for Device<'nvml> {
    fn should_print(&self) -> bool {
        false
    }
}

impl<'nvml> ShouldPrint for Unit<'nvml> {
    fn should_print(&self) -> bool {
        false
    }
}

impl<'nvml> ShouldPrint for EventSet<'nvml> {
    fn should_print(&self) -> bool {
        false
    }
}

impl ShouldPrint for bool {}
impl ShouldPrint for u32 {}
impl ShouldPrint for i32 {}
impl ShouldPrint for (u32, u32) {}
impl ShouldPrint for u64 {}
impl ShouldPrint for String {}
impl ShouldPrint for Brand {}
impl ShouldPrint for [i8; 16] {}
impl ShouldPrint for Vec<ProcessInfo> {}
impl ShouldPrint for Vec<ProcessUtilizationSample> {}
impl<'nvml> ShouldPrint for Vec<Device<'nvml>> {}
impl ShouldPrint for Vec<u32> {}
impl ShouldPrint for Vec<u64> {}
impl ShouldPrint for Vec<Sample> {}
impl ShouldPrint for Vec<Result<FieldValueSample, NvmlError>> {}
impl ShouldPrint for Vec<HwbcEntry> {}
impl ShouldPrint for Utilization {}
impl ShouldPrint for EncoderStats {}
impl ShouldPrint for FbcStats {}
impl ShouldPrint for Vec<FbcSessionInfo> {}
impl ShouldPrint for Vec<EncoderSessionInfo> {}
impl ShouldPrint for AutoBoostClocksEnabledInfo {}
impl ShouldPrint for BAR1MemoryInfo {}
impl ShouldPrint for BridgeChipHierarchy {}
impl ShouldPrint for ComputeMode {}
impl ShouldPrint for UtilizationInfo {}
impl ShouldPrint for EccModeState {}
impl ShouldPrint for OperationModeState {}
impl ShouldPrint for InfoRom {}
impl ShouldPrint for Vec<RetiredPage> {}
impl ShouldPrint for ExcludedDeviceInfo {}
impl ShouldPrint for MemoryInfo {}
impl ShouldPrint for PciInfo {}
impl ShouldPrint for PerformanceState {}
impl ShouldPrint for PowerManagementConstraints {}
impl ShouldPrint for ThrottleReasons {}
impl ShouldPrint for ViolationTime {}
impl ShouldPrint for AccountingStats {}
impl ShouldPrint for EventTypes {}
impl<'nvml> ShouldPrint for EventData<'nvml> {}
impl ShouldPrint for FansInfo {}
impl ShouldPrint for LedState {}
impl ShouldPrint for PsuInfo {}
impl ShouldPrint for UnitInfo {}
impl ShouldPrint for UtilizationControl {}
impl ShouldPrint for UtilizationCounter {}
impl ShouldPrint for BusType {}
impl ShouldPrint for PowerSource {}
impl ShouldPrint for DeviceArchitecture {}
impl ShouldPrint for PcieLinkMaxSpeed {}

#[cfg(target_os = "windows")]
impl ShouldPrint for DriverModelState {}

pub fn nvml() -> Nvml {
    Nvml::init().expect("initialized library")
}

pub fn device(nvml: &Nvml) -> Device<'_> {
    nvml.device_by_index(0).expect("device")
}

pub fn unit(nvml: &Nvml) -> Unit<'_> {
    nvml.unit_by_index(0).expect("unit")
}

/// Run all testing methods for the given test.
pub fn test<T, R>(reps: usize, test: T)
where
    T: Fn() -> Result<R, NvmlError>,
    R: ShouldPrint,
{
    single(|| test());

    multi(reps, || test());
}

pub fn test_with_device<T, R>(reps: usize, nvml: &Nvml, test: T)
where
    T: Fn(&Device) -> Result<R, NvmlError>,
    R: ShouldPrint,
{
    let device = device(nvml);

    single(|| test(&device));

    multi(reps, || test(&device));
}

pub fn test_with_unit<T, R>(reps: usize, nvml: &Nvml, test: T)
where
    T: Fn(&Unit) -> Result<R, NvmlError>,
    R: ShouldPrint,
{
    let unit = unit(nvml);

    single(|| test(&unit));

    multi(reps, || test(&unit));
}

pub fn test_with_link<T, R>(reps: usize, nvml: &Nvml, test: T)
where
    T: Fn(&NvLink) -> Result<R, NvmlError>,
    R: ShouldPrint,
{
    // Is 0 a good default???
    let device = device(nvml);
    let link = device.link_wrapper_for(0);

    single(|| test(&link));

    multi(reps, || test(&link));
}

/// Run the given test once.
pub fn single<T, R>(test: T)
where
    T: Fn() -> Result<R, NvmlError>,
    R: ShouldPrint,
{
    let res = test().expect("successful single test");

    if res.should_print() {
        print!("{:?} ... ", res);
    }
}

/// Run the given test multiple times.
pub fn multi<T, R>(count: usize, test: T)
where
    T: Fn() -> Result<R, NvmlError>,
    R: ShouldPrint,
{
    for i in 0..count {
        test().unwrap_or_else(|_| panic!("successful multi call #{}", i));
    }
}

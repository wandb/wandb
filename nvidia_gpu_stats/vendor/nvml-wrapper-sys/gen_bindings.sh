#!/bin/bash

bindgen --ctypes-prefix raw --no-doc-comments --no-layout-tests --raw-line '#![allow(non_upper_case_globals)]' \
    --raw-line '#![allow(non_camel_case_types)]' --raw-line '#![allow(non_snake_case)]' \
    --raw-line '#![allow(dead_code)]'  --raw-line 'use std::os::raw;' --formatter rustfmt \
    --dynamic-loading NvmlLib -o genned_bindings.rs nvml.h \
    -- -DNVML_NO_UNVERSIONED_FUNC_DEFS # Define `NVML_NO_UNVERSIONED_FUNC_DEFS` so we get generated bindings for legacy functions

# list of legacy function names to hide behind `#[cfg(feature = "legacy-functions")]`
declare -a arr=(
    "nvmlInit"
    "nvmlDeviceGetCount"
    "nvmlDeviceGetHandleByIndex"
    "nvmlDeviceGetHandleByPciBusId"
    "nvmlDeviceGetPciInfo"
    "nvmlDeviceGetPciInfo_v2"
    "nvmlDeviceGetNvLinkRemotePciInfo"
    "nvmlDeviceGetGridLicensableFeatures"
    "nvmlDeviceGetGridLicensableFeatures_v2"
    "nvmlDeviceGetGridLicensableFeatures_v3"
    "nvmlDeviceRemoveGpu"
    "nvmlEventSetWait"
    "nvmlDeviceGetAttributes"
    "nvmlComputeInstanceGetInfo"
    "nvmlDeviceGetComputeRunningProcesses_v2"
    "nvmlDeviceGetComputeRunningProcesses"
    "nvmlDeviceGetGraphicsRunningProcesses"
    "nvmlDeviceGetGraphicsRunningProcesses_v2"
    "nvmlDeviceGetMPSComputeRunningProcesses"
    "nvmlDeviceGetMPSComputeRunningProcesses_v2"
    "nvmlDeviceGetGpuInstancePossiblePlacements"
    "nvmlVgpuInstanceGetLicenseInfo"
)

sed_regex="("

# match struct field definitions
for i in "${arr[@]}"
do
    sed_regex+="pub ${i}:|"
done

# match code to get symbols in constructor
for i in "${arr[@]}"
do
    sed_regex+="let ${i} =|"
done

# match struct fields in constructor
for i in "${arr[@]}"
do
    sed_regex+="${i},|"
done

# match method definitions
for i in "${arr[@]}"
do
    sed_regex+="pub unsafe fn ${i}\(|"
done

# remove the trailing |
sed_regex=${sed_regex%?}
sed_regex+=").*"

# Place `#[cfg(feature = "legacy-functions")]` in front of all lines related to legacy function support
sed -E -i '/('\
"$sed_regex"\
').*/i #[cfg(feature = "legacy-functions")]' genned_bindings.rs

# create the field_id module to improve structure of the bindings
sed -i '/pub const NVML_FI_DEV_ECC_CURRENT:.*/i pub mod field_id {' genned_bindings.rs
sed -i '/pub const NVML_FI_MAX:.*/a }' genned_bindings.rs

# make the __library field public so we can access it from the wrapper
sed -i 's/__library: ::libloading::Library,/pub __library: ::libloading::Library,/' genned_bindings.rs

# final format after using sed on the bindings
rustfmt genned_bindings.rs

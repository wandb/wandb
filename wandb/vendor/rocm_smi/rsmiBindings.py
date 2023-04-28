#!/usr/bin/env python3
"""
ROCm_SMI_LIB CLI Tool Python Bindings.

The University of Illinois/NCSA
Open Source License (NCSA)

Copyright (c) 2014-2018, Advanced Micro Devices, Inc. All rights reserved.

Developed by:

                AMD Research and AMD HSA Software Development

                Advanced Micro Devices, Inc.

                www.amd.com

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to
deal with the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

 - Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimers.
 - Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimers in
   the documentation and/or other materials provided with the distribution.
 - Neither the names of Advanced Micro Devices, Inc,
   nor the names of its contributors may be used to endorse or promote
   products derived from this Software without specific prior written
   permission.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE CONTRIBUTORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS WITH THE SOFTWARE.
"""
# TODO: Get most (or all) of these from rocm_smi.h to avoid mismatches and redundancy

from __future__ import print_function
import ctypes.util
from ctypes import *
from enum import Enum

import os

# Use ROCm installation path if running from standard installation
# With File Reorg rsmiBindings.py will be installed in  /opt/rocm/libexec/rocm_smi.
# relative path changed accordingly
path_librocm = (
    os.path.dirname(os.path.realpath(__file__)) + "/../../lib/librocm_smi64.so"
)
if not os.path.isfile(path_librocm):
    print("Unable to find %s . Trying /opt/rocm*" % path_librocm)
    for root, dirs, files in os.walk("/opt", followlinks=True):
        if "librocm_smi64.so" in files:
            path_librocm = os.path.join(os.path.realpath(root), "librocm_smi64.so")
    if os.path.isfile(path_librocm):
        print("Using lib from %s" % path_librocm)
    else:
        print("Unable to find librocm_smi64.so")

# ----------> TODO: Support static libs as well as SO

try:
    cdll.LoadLibrary(path_librocm)
    rocmsmi = CDLL(path_librocm)
except OSError:
    print(
        "Unable to load the rocm_smi library.\n"
        "Set LD_LIBRARY_PATH to the folder containing librocm_smi64.\n"
        "{0}Please refer to https://github.com/"
        "RadeonOpenCompute/rocm_smi_lib for the installation guide.{1}".format(
            "\33[33m", "\033[0m"
        )
    )
    exit()


# Device ID
dv_id = c_uint64()
# GPU ID
gpu_id = c_uint32(0)


# Policy enums
RSMI_MAX_NUM_FREQUENCIES = 32
RSMI_MAX_FAN_SPEED = 255
RSMI_NUM_VOLTAGE_CURVE_POINTS = 3


class rsmi_status_t(c_int):
    RSMI_STATUS_SUCCESS = 0x0
    RSMI_STATUS_INVALID_ARGS = 0x1
    RSMI_STATUS_NOT_SUPPORTED = 0x2
    RSMI_STATUS_FILE_ERROR = 0x3
    RSMI_STATUS_PERMISSION = 0x4
    RSMI_STATUS_OUT_OF_RESOURCES = 0x5
    RSMI_STATUS_INTERNAL_EXCEPTION = 0x6
    RSMI_STATUS_INPUT_OUT_OF_BOUNDS = 0x7
    RSMI_STATUS_INIT_ERROR = 0x8
    RSMI_INITIALIZATION_ERROR = RSMI_STATUS_INIT_ERROR
    RSMI_STATUS_NOT_YET_IMPLEMENTED = 0x9
    RSMI_STATUS_NOT_FOUND = 0xA
    RSMI_STATUS_INSUFFICIENT_SIZE = 0xB
    RSMI_STATUS_INTERRUPT = 0xC
    RSMI_STATUS_UNEXPECTED_SIZE = 0xD
    RSMI_STATUS_NO_DATA = 0xE
    RSMI_STATUS_UNKNOWN_ERROR = 0xFFFFFFFF


# Dictionary of rsmi ret codes and it's verbose output
rsmi_status_verbose_err_out = {
    rsmi_status_t.RSMI_STATUS_SUCCESS: "Operation was successful",
    rsmi_status_t.RSMI_STATUS_INVALID_ARGS: "Invalid arguments provided",
    rsmi_status_t.RSMI_STATUS_NOT_SUPPORTED: "Not supported on the given system",
    rsmi_status_t.RSMI_STATUS_FILE_ERROR: "Problem accessing a file",
    rsmi_status_t.RSMI_STATUS_PERMISSION: "Permission denied",
    rsmi_status_t.RSMI_STATUS_OUT_OF_RESOURCES: "Unable to acquire memory or other resource",
    rsmi_status_t.RSMI_STATUS_INTERNAL_EXCEPTION: "An internal exception was caught",
    rsmi_status_t.RSMI_STATUS_INPUT_OUT_OF_BOUNDS: "Provided input is out of allowable or safe range",
    rsmi_status_t.RSMI_INITIALIZATION_ERROR: "Error occured during rsmi initialization",
    rsmi_status_t.RSMI_STATUS_NOT_YET_IMPLEMENTED: "Requested function is not implemented on this setup",
    rsmi_status_t.RSMI_STATUS_NOT_FOUND: "Item searched for but not found",
    rsmi_status_t.RSMI_STATUS_INSUFFICIENT_SIZE: "Insufficient resources available",
    rsmi_status_t.RSMI_STATUS_INTERRUPT: "Interrupt occured during execution",
    rsmi_status_t.RSMI_STATUS_UNEXPECTED_SIZE: "Unexpected amount of data read",
    rsmi_status_t.RSMI_STATUS_NO_DATA: "No data found for the given input",
    rsmi_status_t.RSMI_STATUS_UNKNOWN_ERROR: "Unknown error occured",
}


class rsmi_init_flags_t(c_int):
    RSMI_INIT_FLAG_ALL_GPUS = 0x1


class rsmi_dev_perf_level_t(c_int):
    RSMI_DEV_PERF_LEVEL_AUTO = 0
    RSMI_DEV_PERF_LEVEL_FIRST = RSMI_DEV_PERF_LEVEL_AUTO
    RSMI_DEV_PERF_LEVEL_LOW = 1
    RSMI_DEV_PERF_LEVEL_HIGH = 2
    RSMI_DEV_PERF_LEVEL_MANUAL = 3
    RSMI_DEV_PERF_LEVEL_STABLE_STD = 4
    RSMI_DEV_PERF_LEVEL_STABLE_PEAK = 5
    RSMI_DEV_PERF_LEVEL_STABLE_MIN_MCLK = 6
    RSMI_DEV_PERF_LEVEL_STABLE_MIN_SCLK = 7
    RSMI_DEV_PERF_LEVEL_DETERMINISM = 8
    RSMI_DEV_PERF_LEVEL_LAST = RSMI_DEV_PERF_LEVEL_DETERMINISM
    RSMI_DEV_PERF_LEVEL_UNKNOWN = 0x100


notification_type_names = ["VM_FAULT", "THERMAL_THROTTLE", "GPU_RESET"]


class rsmi_evt_notification_type_t(c_int):
    RSMI_EVT_NOTIF_VMFAULT = 0
    RSMI_EVT_NOTIF_FIRST = RSMI_EVT_NOTIF_VMFAULT
    RSMI_EVT_NOTIF_THERMAL_THROTTLE = 1
    RSMI_EVT_NOTIF_GPU_PRE_RESET = 2
    RSMI_EVT_NOTIF_GPU_POST_RESET = 3
    RSMI_EVT_NOTIF_LAST = RSMI_EVT_NOTIF_GPU_POST_RESET


class rsmi_voltage_metric_t(c_int):
    RSMI_VOLT_CURRENT = 0
    RSMI_VOLT_FIRST = RSMI_VOLT_CURRENT
    RSMI_VOLT_MAX = 1
    RSMI_VOLT_MIN_CRIT = 2
    RSMI_VOLT_MIN = 3
    RSMI_VOLT_MAX_CRIT = 4
    RSMI_VOLT_AVERAGE = 5
    RSMI_VOLT_LOWEST = 6
    RSMI_VOLT_HIGHEST = 7
    RSMI_VOLT_LAST = RSMI_VOLT_HIGHEST
    RSMI_VOLT_UNKNOWN = 0x100


class rsmi_voltage_type_t(c_int):
    RSMI_VOLT_TYPE_FIRST = 0
    RSMI_VOLT_TYPE_VDDGFX = RSMI_VOLT_TYPE_FIRST
    RSMI_VOLT_TYPE_LAST = RSMI_VOLT_TYPE_VDDGFX
    RSMI_VOLT_TYPE_INVALID = 0xFFFFFFFF


# The perf_level_string is correlated to rsmi_dev_perf_level_t
def perf_level_string(i):
    switcher = {
        0: "AUTO",
        1: "LOW",
        2: "HIGH",
        3: "MANUAL",
        4: "STABLE_STD",
        5: "STABLE_PEAK",
        6: "STABLE_MIN_MCLK",
        7: "STABLE_MIN_SCLK",
        8: "PERF_DETERMINISM",
    }
    return switcher.get(i, "UNKNOWN")


rsmi_dev_perf_level = rsmi_dev_perf_level_t


class rsmi_sw_component_t(c_int):
    RSMI_SW_COMP_FIRST = 0x0
    RSMI_SW_COMP_DRIVER = RSMI_SW_COMP_FIRST
    RSMI_SW_COMP_LAST = RSMI_SW_COMP_DRIVER


rsmi_event_handle_t = POINTER(c_uint)


class rsmi_event_group_t(Enum):
    RSMI_EVNT_GRP_XGMI = 0
    RSMI_EVNT_GRP_XGMI_DATA_OUT = 10
    RSMI_EVNT_GRP_INVALID = 0xFFFFFFFF


class rsmi_event_type_t(c_int):
    RSMI_EVNT_FIRST = rsmi_event_group_t.RSMI_EVNT_GRP_XGMI
    RSMI_EVNT_XGMI_FIRST = rsmi_event_group_t.RSMI_EVNT_GRP_XGMI
    RSMI_EVNT_XGMI_0_NOP_TX = RSMI_EVNT_XGMI_FIRST
    RSMI_EVNT_XGMI_0_REQUEST_TX = 1
    RSMI_EVNT_XGMI_0_RESPONSE_TX = 2
    RSMI_EVNT_XGMI_0_BEATS_TX = 3
    RSMI_EVNT_XGMI_1_NOP_TX = 4
    RSMI_EVNT_XGMI_1_REQUEST_TX = 5
    RSMI_EVNT_XGMI_1_RESPONSE_TX = 6
    RSMI_EVNT_XGMI_1_BEATS_TX = 7
    RSMI_EVNT_XGMI_LAST = RSMI_EVNT_XGMI_1_BEATS_TX

    RSMI_EVNT_XGMI_DATA_OUT_FIRST = rsmi_event_group_t.RSMI_EVNT_GRP_XGMI_DATA_OUT
    RSMI_EVNT_XGMI_DATA_OUT_0 = RSMI_EVNT_XGMI_DATA_OUT_FIRST
    RSMI_EVNT_XGMI_DATA_OUT_1 = 11
    RSMI_EVNT_XGMI_DATA_OUT_2 = 12
    RSMI_EVNT_XGMI_DATA_OUT_3 = 13
    RSMI_EVNT_XGMI_DATA_OUT_4 = 14
    RSMI_EVNT_XGMI_DATA_OUT_5 = 15
    RSMI_EVNT_XGMI_DATA_OUT_LAST = RSMI_EVNT_XGMI_DATA_OUT_5

    RSMI_EVNT_LAST = (RSMI_EVNT_XGMI_DATA_OUT_LAST,)


class rsmi_counter_command_t(c_int):
    RSMI_CNTR_CMD_START = 0
    RSMI_CNTR_CMD_STOP = 1


class rsmi_counter_value_t(Structure):
    _fields_ = [
        ("value", c_uint64),
        ("time_enabled", c_uint64),
        ("time_running", c_uint64),
    ]


class rsmi_clk_type_t(c_int):
    RSMI_CLK_TYPE_SYS = 0x0
    RSMI_CLK_TYPE_FIRST = RSMI_CLK_TYPE_SYS
    RSMI_CLK_TYPE_DF = 0x1
    RSMI_CLK_TYPE_DCEF = 0x2
    RSMI_CLK_TYPE_SOC = 0x3
    RSMI_CLK_TYPE_MEM = 0x4
    RSMI_CLK_TYPE_LAST = RSMI_CLK_TYPE_MEM
    RSMI_CLK_INVALID = 0xFFFFFFFF


# Clock names here are correlated to the rsmi_clk_type_t values above
clk_type_names = [
    "sclk",
    "sclk",
    "fclk",
    "dcefclk",
    "socclk",
    "mclk",
    "mclk",
    "invalid",
]
rsmi_clk_type_dict = {
    "RSMI_CLK_TYPE_SYS": 0x0,
    "RSMI_CLK_TYPE_FIRST": 0x0,
    "RSMI_CLK_TYPE_DF": 0x1,
    "RSMI_CLK_TYPE_DCEF": 0x2,
    "RSMI_CLK_TYPE_SOC": 0x3,
    "RSMI_CLK_TYPE_MEM": 0x4,
    "RSMI_CLK_TYPE_LAST": 0x4,
    "RSMI_CLK_INVALID": 0xFFFFFFFF,
}
rsmi_clk_names_dict = {
    "sclk": 0x0,
    "fclk": 0x1,
    "dcefclk": 0x2,
    "socclk": 0x3,
    "mclk": 0x4,
}
rsmi_clk_type = rsmi_clk_type_t


class rsmi_temperature_metric_t(c_int):
    RSMI_TEMP_CURRENT = 0x0
    RSMI_TEMP_FIRST = RSMI_TEMP_CURRENT
    RSMI_TEMP_MAX = 0x1
    RSMI_TEMP_MIN = 0x2
    RSMI_TEMP_MAX_HYST = 0x3
    RSMI_TEMP_MIN_HYST = 0x4
    RSMI_TEMP_CRITICAL = 0x5
    RSMI_TEMP_CRITICAL_HYST = 0x6
    RSMI_TEMP_EMERGENCY = 0x7
    RSMI_TEMP_EMERGENCY_HYST = 0x8
    RSMI_TEMP_CRIT_MIN = 0x9
    RSMI_TEMP_CRIT_MIN_HYST = 0xA
    RSMI_TEMP_OFFSET = 0xB
    RSMI_TEMP_LOWEST = 0xC
    RSMI_TEMP_HIGHEST = 0xD
    RSMI_TEMP_LAST = RSMI_TEMP_HIGHEST


rsmi_temperature_metric = rsmi_temperature_metric_t


class rsmi_temperature_type_t(c_int):
    RSMI_TEMP_TYPE_FIRST = 0
    RSMI_TEMP_TYPE_EDGE = RSMI_TEMP_TYPE_FIRST
    RSMI_TEMP_TYPE_JUNCTION = 1
    RSMI_TEMP_TYPE_MEMORY = 2
    RSMI_TEMP_TYPE_HBM_0 = 3
    RSMI_TEMP_TYPE_HBM_1 = 4
    RSMI_TEMP_TYPE_HBM_2 = 5
    RSMI_TEMP_TYPE_HBM_3 = 6
    RSMI_TEMP_TYPE_LAST = RSMI_TEMP_TYPE_HBM_3


# temp_type_lst list correlates to rsmi_temperature_type_t
temp_type_lst = ["edge", "junction", "memory", "HBM 0", "HBM 1", "HBM 2", "HBM 3"]


class rsmi_power_profile_preset_masks_t(c_uint64):
    RSMI_PWR_PROF_PRST_CUSTOM_MASK = 0x1
    RSMI_PWR_PROF_PRST_VIDEO_MASK = 0x2
    RSMI_PWR_PROF_PRST_POWER_SAVING_MASK = 0x4
    RSMI_PWR_PROF_PRST_COMPUTE_MASK = 0x8
    RSMI_PWR_PROF_PRST_VR_MASK = 0x10
    RSMI_PWR_PROF_PRST_3D_FULL_SCR_MASK = 0x20
    RSMI_PWR_PROF_PRST_BOOTUP_DEFAULT = 0x40
    RSMI_PWR_PROF_PRST_LAST = RSMI_PWR_PROF_PRST_BOOTUP_DEFAULT
    RSMI_PWR_PROF_PRST_INVALID = 0xFFFFFFFFFFFFFFFF


rsmi_power_profile_preset_masks = rsmi_power_profile_preset_masks_t


class rsmi_gpu_block_t(c_int):
    RSMI_GPU_BLOCK_INVALID = 0x0000000000000000
    RSMI_GPU_BLOCK_FIRST = 0x0000000000000001
    RSMI_GPU_BLOCK_UMC = RSMI_GPU_BLOCK_FIRST
    RSMI_GPU_BLOCK_SDMA = 0x0000000000000002
    RSMI_GPU_BLOCK_GFX = 0x0000000000000004
    RSMI_GPU_BLOCK_MMHUB = 0x0000000000000008
    RSMI_GPU_BLOCK_ATHUB = 0x0000000000000010
    RSMI_GPU_BLOCK_PCIE_BIF = 0x0000000000000020
    RSMI_GPU_BLOCK_HDP = 0x0000000000000040
    RSMI_GPU_BLOCK_XGMI_WAFL = 0x0000000000000080
    RSMI_GPU_BLOCK_DF = 0x0000000000000100
    RSMI_GPU_BLOCK_SMN = 0x0000000000000200
    RSMI_GPU_BLOCK_SEM = 0x0000000000000400
    RSMI_GPU_BLOCK_MP0 = 0x0000000000000800
    RSMI_GPU_BLOCK_MP1 = 0x0000000000001000
    RSMI_GPU_BLOCK_FUSE = 0x0000000000002000
    RSMI_GPU_BLOCK_LAST = RSMI_GPU_BLOCK_FUSE
    RSMI_GPU_BLOCK_RESERVED = 0x8000000000000000


rsmi_gpu_block = rsmi_gpu_block_t


# The following dictionary correlates with rsmi_gpu_block_t enum
rsmi_gpu_block_d = {
    "UMC": 0x0000000000000001,
    "SDMA": 0x0000000000000002,
    "GFX": 0x0000000000000004,
    "MMHUB": 0x0000000000000008,
    "ATHUB": 0x0000000000000010,
    "PCIE_BIF": 0x0000000000000020,
    "HDP": 0x0000000000000040,
    "XGMI_WAFL": 0x0000000000000080,
    "DF": 0x0000000000000100,
    "SMN": 0x0000000000000200,
    "SEM": 0x0000000000000400,
    "MP0": 0x0000000000000800,
    "MP1": 0x0000000000001000,
    "FUSE": 0x0000000000002000,
}


class rsmi_ras_err_state_t(c_int):
    RSMI_RAS_ERR_STATE_NONE = 0
    RSMI_RAS_ERR_STATE_DISABLED = 1
    RSMI_RAS_ERR_STATE_PARITY = 2
    RSMI_RAS_ERR_STATE_SING_C = 3
    RSMI_RAS_ERR_STATE_MULT_UC = 4
    RSMI_RAS_ERR_STATE_POISON = 5
    RSMI_RAS_ERR_STATE_ENABLED = 6
    RSMI_RAS_ERR_STATE_LAST = RSMI_RAS_ERR_STATE_ENABLED
    RSMI_RAS_ERR_STATE_INVALID = 0xFFFFFFFF


# Error type list correlates to rsmi_ras_err_state_t
rsmi_ras_err_stale_readable = [
    "no errors",
    "ECC disabled",
    "unknown type err",
    "single correctable err",
    "multiple uncorrectable err",
    "page isolated, treat as uncorrectable err",
    "ECC enabled",
    "status invalid",
]
rsmi_ras_err_stale_machine = [
    "none",
    "disabled",
    "unknown error",
    "sing",
    "mult",
    "position",
    "enabled",
]

validRasTypes = ["ue", "ce"]

validRasActions = ["disable", "enable", "inject"]

validRasBlocks = [
    "fuse",
    "mp1",
    "mp0",
    "sem",
    "smn",
    "df",
    "xgmi_wafl",
    "hdp",
    "pcie_bif",
    "athub",
    "mmhub",
    "gfx",
    "sdma",
    "umc",
]


class rsmi_memory_type_t(c_int):
    RSMI_MEM_TYPE_FIRST = 0
    RSMI_MEM_TYPE_VRAM = RSMI_MEM_TYPE_FIRST
    RSMI_MEM_TYPE_VIS_VRAM = 1
    RSMI_MEM_TYPE_GTT = 2
    RSMI_MEM_TYPE_LAST = RSMI_MEM_TYPE_GTT


# memory_type_l includes names for with rsmi_memory_type_t
# Usage example to get corresponding names:
# memory_type_l[rsmi_memory_type_t.RSMI_MEM_TYPE_VRAM] will return string 'vram'
memory_type_l = ["VRAM", "VIS_VRAM", "GTT"]


class rsmi_freq_ind_t(c_int):
    RSMI_FREQ_IND_MIN = 0
    RSMI_FREQ_IND_MAX = 1
    RSMI_FREQ_IND_INVALID = 0xFFFFFFFF


rsmi_freq_ind = rsmi_freq_ind_t


class rsmi_fw_block_t(c_int):
    RSMI_FW_BLOCK_FIRST = 0
    RSMI_FW_BLOCK_ASD = RSMI_FW_BLOCK_FIRST
    RSMI_FW_BLOCK_CE = 1
    RSMI_FW_BLOCK_DMCU = 2
    RSMI_FW_BLOCK_MC = 3
    RSMI_FW_BLOCK_ME = 4
    RSMI_FW_BLOCK_MEC = 5
    RSMI_FW_BLOCK_MEC2 = 6
    RSMI_FW_BLOCK_PFP = 7
    RSMI_FW_BLOCK_RLC = 8
    RSMI_FW_BLOCK_RLC_SRLC = 9
    RSMI_FW_BLOCK_RLC_SRLG = 10
    RSMI_FW_BLOCK_RLC_SRLS = 11
    RSMI_FW_BLOCK_SDMA = 12
    RSMI_FW_BLOCK_SDMA2 = 13
    RSMI_FW_BLOCK_SMC = 14
    RSMI_FW_BLOCK_SOS = 15
    RSMI_FW_BLOCK_TA_RAS = 16
    RSMI_FW_BLOCK_TA_XGMI = 17
    RSMI_FW_BLOCK_UVD = 18
    RSMI_FW_BLOCK_VCE = 19
    RSMI_FW_BLOCK_VCN = 20
    RSMI_FW_BLOCK_LAST = RSMI_FW_BLOCK_VCN


# The following list correlated to the rsmi_fw_block_t
fw_block_names_l = [
    "ASD",
    "CE",
    "DMCU",
    "MC",
    "ME",
    "MEC",
    "MEC2",
    "PFP",
    "RLC",
    "RLC SRLC",
    "RLC SRLG",
    "RLC SRLS",
    "SDMA",
    "SDMA2",
    "SMC",
    "SOS",
    "TA RAS",
    "TA XGMI",
    "UVD",
    "VCE",
    "VCN",
]


rsmi_bit_field_t = c_uint64()
rsmi_bit_field = rsmi_bit_field_t


class rsmi_utilization_counter_type(c_int):
    RSMI_UTILIZATION_COUNTER_FIRST = 0
    RSMI_COARSE_GRAIN_GFX_ACTIVITY = RSMI_UTILIZATION_COUNTER_FIRST
    RSMI_COARSE_GRAIN_MEM_ACTIVITY = 1
    RSMI_UTILIZATION_COUNTER_LAST = RSMI_COARSE_GRAIN_MEM_ACTIVITY


utilization_counter_name = ["GFX Activity", "Memory Activity"]


class rsmi_utilization_counter_t(Structure):
    _fields_ = [("type", c_int), ("val", c_uint64)]


class rsmi_xgmi_status_t(c_int):
    RSMI_XGMI_STATUS_NO_ERRORS = 0
    RSMI_XGMI_STATUS_ERROR = 1
    RSMI_XGMI_STATUS_MULTIPLE_ERRORS = 2


class rsmi_memory_page_status_t(c_int):
    RSMI_MEM_PAGE_STATUS_RESERVED = 0
    RSMI_MEM_PAGE_STATUS_PENDING = 1
    RSMI_MEM_PAGE_STATUS_UNRESERVABLE = 2


memory_page_status_l = ["reserved", "pending", "unreservable"]


class rsmi_retired_page_record_t(Structure):
    _fields_ = [("page_address", c_uint64), ("page_size", c_uint64), ("status", c_int)]


RSMI_MAX_NUM_POWER_PROFILES = sizeof(rsmi_bit_field_t) * 8


class rsmi_power_profile_status_t(Structure):
    _fields_ = [
        ("available_profiles", c_uint32),
        ("current", c_uint64),
        ("num_profiles", c_uint32),
    ]


rsmi_power_profile_status = rsmi_power_profile_status_t


class rsmi_frequencies_t(Structure):
    _fields_ = [
        ("num_supported", c_int32),
        ("current", c_uint32),
        ("frequency", c_uint64 * RSMI_MAX_NUM_FREQUENCIES),
    ]


rsmi_frequencies = rsmi_frequencies_t


class rsmi_pcie_bandwidth_t(Structure):
    _fields_ = [
        ("transfer_rate", rsmi_frequencies_t),
        ("lanes", c_uint32 * RSMI_MAX_NUM_FREQUENCIES),
    ]


rsmi_pcie_bandwidth = rsmi_pcie_bandwidth_t


class rsmi_version_t(Structure):
    _fields_ = [
        ("major", c_uint32),
        ("minor", c_uint32),
        ("patch", c_uint32),
        ("build", c_char_p),
    ]


rsmi_version = rsmi_version_t


class rsmi_range_t(Structure):
    _fields_ = [("lower_bound", c_uint64), ("upper_bound", c_uint64)]


rsmi_range = rsmi_range_t


class rsmi_od_vddc_point_t(Structure):
    _fields_ = [("frequency", c_uint64), ("voltage", c_uint64)]


rsmi_od_vddc_point = rsmi_od_vddc_point_t


class rsmi_freq_volt_region_t(Structure):
    _fields_ = [("freq_range", rsmi_range_t), ("volt_range", rsmi_range_t)]


rsmi_freq_volt_region = rsmi_freq_volt_region_t


class rsmi_od_volt_curve_t(Structure):
    _fields_ = [("vc_points", rsmi_od_vddc_point_t * RSMI_NUM_VOLTAGE_CURVE_POINTS)]


rsmi_od_volt_curve = rsmi_od_volt_curve_t


class rsmi_od_volt_freq_data_t(Structure):
    _fields_ = [
        ("curr_sclk_range", rsmi_range_t),
        ("curr_mclk_range", rsmi_range_t),
        ("sclk_freq_limits", rsmi_range_t),
        ("mclk_freq_limits", rsmi_range_t),
        ("curve", rsmi_od_volt_curve_t),
        ("num_regions", c_uint32),
    ]


rsmi_od_volt_freq_data = rsmi_od_volt_freq_data_t


class rsmi_error_count_t(Structure):
    _fields_ = [("correctable_err", c_uint64), ("uncorrectable_err", c_uint64)]


class rsmi_evt_notification_data_t(Structure):
    _fields_ = [
        ("dv_ind", c_uint32),
        ("event", rsmi_evt_notification_type_t),
        ("message", c_char * 64),
    ]


class rsmi_process_info_t(Structure):
    _fields_ = [
        ("process_id", c_uint32),
        ("pasid", c_uint32),
        ("vram_usage", c_uint64),
        ("sdma_usage", c_uint64),
        ("cu_occupancy", c_uint32),
    ]


class rsmi_func_id_iter_handle(Structure):
    _fields_ = [
        ("func_id_iter", POINTER(c_uint)),
        ("container_ptr", POINTER(c_uint)),
        ("id_type", c_uint32),
    ]


rsmi_func_id_iter_handle_t = POINTER(rsmi_func_id_iter_handle)


RSMI_DEFAULT_VARIANT = 0xFFFFFFFFFFFFFFFF


class submodule_union(Union):
    _fields_ = [
        ("memory_type", c_int),  #    rsmi_memory_type_t,
        ("temp_metric", c_int),  #    rsmi_temperature_metric_t,
        ("evnt_type", c_int),  #    rsmi_event_type_t,
        ("evnt_group", c_int),  #    rsmi_event_group_t,
        ("clk_type", c_int),  #    rsmi_clk_type_t,
        ("fw_block", c_int),  #    rsmi_fw_block_t,
        ("gpu_block_type", c_int),
    ]  #    rsmi_gpu_block_t


class rsmi_func_id_value_t(Union):
    _fields_ = [("id", c_uint64), ("name", c_char_p), ("submodule", submodule_union)]

/**
# Copyright 2024 NVIDIA CORPORATION
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
**/

// Generated Code; DO NOT EDIT.

package nvml

// The variables below represent package level methods from the library type.
var (
	ComputeInstanceDestroy                          = libnvml.ComputeInstanceDestroy
	ComputeInstanceGetInfo                          = libnvml.ComputeInstanceGetInfo
	DeviceClearAccountingPids                       = libnvml.DeviceClearAccountingPids
	DeviceClearCpuAffinity                          = libnvml.DeviceClearCpuAffinity
	DeviceClearEccErrorCounts                       = libnvml.DeviceClearEccErrorCounts
	DeviceClearFieldValues                          = libnvml.DeviceClearFieldValues
	DeviceCreateGpuInstance                         = libnvml.DeviceCreateGpuInstance
	DeviceCreateGpuInstanceWithPlacement            = libnvml.DeviceCreateGpuInstanceWithPlacement
	DeviceDiscoverGpus                              = libnvml.DeviceDiscoverGpus
	DeviceFreezeNvLinkUtilizationCounter            = libnvml.DeviceFreezeNvLinkUtilizationCounter
	DeviceGetAPIRestriction                         = libnvml.DeviceGetAPIRestriction
	DeviceGetAccountingBufferSize                   = libnvml.DeviceGetAccountingBufferSize
	DeviceGetAccountingMode                         = libnvml.DeviceGetAccountingMode
	DeviceGetAccountingPids                         = libnvml.DeviceGetAccountingPids
	DeviceGetAccountingStats                        = libnvml.DeviceGetAccountingStats
	DeviceGetActiveVgpus                            = libnvml.DeviceGetActiveVgpus
	DeviceGetAdaptiveClockInfoStatus                = libnvml.DeviceGetAdaptiveClockInfoStatus
	DeviceGetApplicationsClock                      = libnvml.DeviceGetApplicationsClock
	DeviceGetArchitecture                           = libnvml.DeviceGetArchitecture
	DeviceGetAttributes                             = libnvml.DeviceGetAttributes
	DeviceGetAutoBoostedClocksEnabled               = libnvml.DeviceGetAutoBoostedClocksEnabled
	DeviceGetBAR1MemoryInfo                         = libnvml.DeviceGetBAR1MemoryInfo
	DeviceGetBoardId                                = libnvml.DeviceGetBoardId
	DeviceGetBoardPartNumber                        = libnvml.DeviceGetBoardPartNumber
	DeviceGetBrand                                  = libnvml.DeviceGetBrand
	DeviceGetBridgeChipInfo                         = libnvml.DeviceGetBridgeChipInfo
	DeviceGetBusType                                = libnvml.DeviceGetBusType
	DeviceGetC2cModeInfoV                           = libnvml.DeviceGetC2cModeInfoV
	DeviceGetClkMonStatus                           = libnvml.DeviceGetClkMonStatus
	DeviceGetClock                                  = libnvml.DeviceGetClock
	DeviceGetClockInfo                              = libnvml.DeviceGetClockInfo
	DeviceGetComputeInstanceId                      = libnvml.DeviceGetComputeInstanceId
	DeviceGetComputeMode                            = libnvml.DeviceGetComputeMode
	DeviceGetComputeRunningProcesses                = libnvml.DeviceGetComputeRunningProcesses
	DeviceGetConfComputeGpuAttestationReport        = libnvml.DeviceGetConfComputeGpuAttestationReport
	DeviceGetConfComputeGpuCertificate              = libnvml.DeviceGetConfComputeGpuCertificate
	DeviceGetConfComputeMemSizeInfo                 = libnvml.DeviceGetConfComputeMemSizeInfo
	DeviceGetConfComputeProtectedMemoryUsage        = libnvml.DeviceGetConfComputeProtectedMemoryUsage
	DeviceGetCount                                  = libnvml.DeviceGetCount
	DeviceGetCpuAffinity                            = libnvml.DeviceGetCpuAffinity
	DeviceGetCpuAffinityWithinScope                 = libnvml.DeviceGetCpuAffinityWithinScope
	DeviceGetCreatableVgpus                         = libnvml.DeviceGetCreatableVgpus
	DeviceGetCudaComputeCapability                  = libnvml.DeviceGetCudaComputeCapability
	DeviceGetCurrPcieLinkGeneration                 = libnvml.DeviceGetCurrPcieLinkGeneration
	DeviceGetCurrPcieLinkWidth                      = libnvml.DeviceGetCurrPcieLinkWidth
	DeviceGetCurrentClocksEventReasons              = libnvml.DeviceGetCurrentClocksEventReasons
	DeviceGetCurrentClocksThrottleReasons           = libnvml.DeviceGetCurrentClocksThrottleReasons
	DeviceGetDecoderUtilization                     = libnvml.DeviceGetDecoderUtilization
	DeviceGetDefaultApplicationsClock               = libnvml.DeviceGetDefaultApplicationsClock
	DeviceGetDefaultEccMode                         = libnvml.DeviceGetDefaultEccMode
	DeviceGetDetailedEccErrors                      = libnvml.DeviceGetDetailedEccErrors
	DeviceGetDeviceHandleFromMigDeviceHandle        = libnvml.DeviceGetDeviceHandleFromMigDeviceHandle
	DeviceGetDisplayActive                          = libnvml.DeviceGetDisplayActive
	DeviceGetDisplayMode                            = libnvml.DeviceGetDisplayMode
	DeviceGetDriverModel                            = libnvml.DeviceGetDriverModel
	DeviceGetDynamicPstatesInfo                     = libnvml.DeviceGetDynamicPstatesInfo
	DeviceGetEccMode                                = libnvml.DeviceGetEccMode
	DeviceGetEncoderCapacity                        = libnvml.DeviceGetEncoderCapacity
	DeviceGetEncoderSessions                        = libnvml.DeviceGetEncoderSessions
	DeviceGetEncoderStats                           = libnvml.DeviceGetEncoderStats
	DeviceGetEncoderUtilization                     = libnvml.DeviceGetEncoderUtilization
	DeviceGetEnforcedPowerLimit                     = libnvml.DeviceGetEnforcedPowerLimit
	DeviceGetFBCSessions                            = libnvml.DeviceGetFBCSessions
	DeviceGetFBCStats                               = libnvml.DeviceGetFBCStats
	DeviceGetFanControlPolicy_v2                    = libnvml.DeviceGetFanControlPolicy_v2
	DeviceGetFanSpeed                               = libnvml.DeviceGetFanSpeed
	DeviceGetFanSpeed_v2                            = libnvml.DeviceGetFanSpeed_v2
	DeviceGetFieldValues                            = libnvml.DeviceGetFieldValues
	DeviceGetGpcClkMinMaxVfOffset                   = libnvml.DeviceGetGpcClkMinMaxVfOffset
	DeviceGetGpcClkVfOffset                         = libnvml.DeviceGetGpcClkVfOffset
	DeviceGetGpuFabricInfo                          = libnvml.DeviceGetGpuFabricInfo
	DeviceGetGpuFabricInfoV                         = libnvml.DeviceGetGpuFabricInfoV
	DeviceGetGpuInstanceById                        = libnvml.DeviceGetGpuInstanceById
	DeviceGetGpuInstanceId                          = libnvml.DeviceGetGpuInstanceId
	DeviceGetGpuInstancePossiblePlacements          = libnvml.DeviceGetGpuInstancePossiblePlacements
	DeviceGetGpuInstanceProfileInfo                 = libnvml.DeviceGetGpuInstanceProfileInfo
	DeviceGetGpuInstanceProfileInfoV                = libnvml.DeviceGetGpuInstanceProfileInfoV
	DeviceGetGpuInstanceRemainingCapacity           = libnvml.DeviceGetGpuInstanceRemainingCapacity
	DeviceGetGpuInstances                           = libnvml.DeviceGetGpuInstances
	DeviceGetGpuMaxPcieLinkGeneration               = libnvml.DeviceGetGpuMaxPcieLinkGeneration
	DeviceGetGpuOperationMode                       = libnvml.DeviceGetGpuOperationMode
	DeviceGetGraphicsRunningProcesses               = libnvml.DeviceGetGraphicsRunningProcesses
	DeviceGetGridLicensableFeatures                 = libnvml.DeviceGetGridLicensableFeatures
	DeviceGetGspFirmwareMode                        = libnvml.DeviceGetGspFirmwareMode
	DeviceGetGspFirmwareVersion                     = libnvml.DeviceGetGspFirmwareVersion
	DeviceGetHandleByIndex                          = libnvml.DeviceGetHandleByIndex
	DeviceGetHandleByPciBusId                       = libnvml.DeviceGetHandleByPciBusId
	DeviceGetHandleBySerial                         = libnvml.DeviceGetHandleBySerial
	DeviceGetHandleByUUID                           = libnvml.DeviceGetHandleByUUID
	DeviceGetHostVgpuMode                           = libnvml.DeviceGetHostVgpuMode
	DeviceGetIndex                                  = libnvml.DeviceGetIndex
	DeviceGetInforomConfigurationChecksum           = libnvml.DeviceGetInforomConfigurationChecksum
	DeviceGetInforomImageVersion                    = libnvml.DeviceGetInforomImageVersion
	DeviceGetInforomVersion                         = libnvml.DeviceGetInforomVersion
	DeviceGetIrqNum                                 = libnvml.DeviceGetIrqNum
	DeviceGetJpgUtilization                         = libnvml.DeviceGetJpgUtilization
	DeviceGetLastBBXFlushTime                       = libnvml.DeviceGetLastBBXFlushTime
	DeviceGetMPSComputeRunningProcesses             = libnvml.DeviceGetMPSComputeRunningProcesses
	DeviceGetMaxClockInfo                           = libnvml.DeviceGetMaxClockInfo
	DeviceGetMaxCustomerBoostClock                  = libnvml.DeviceGetMaxCustomerBoostClock
	DeviceGetMaxMigDeviceCount                      = libnvml.DeviceGetMaxMigDeviceCount
	DeviceGetMaxPcieLinkGeneration                  = libnvml.DeviceGetMaxPcieLinkGeneration
	DeviceGetMaxPcieLinkWidth                       = libnvml.DeviceGetMaxPcieLinkWidth
	DeviceGetMemClkMinMaxVfOffset                   = libnvml.DeviceGetMemClkMinMaxVfOffset
	DeviceGetMemClkVfOffset                         = libnvml.DeviceGetMemClkVfOffset
	DeviceGetMemoryAffinity                         = libnvml.DeviceGetMemoryAffinity
	DeviceGetMemoryBusWidth                         = libnvml.DeviceGetMemoryBusWidth
	DeviceGetMemoryErrorCounter                     = libnvml.DeviceGetMemoryErrorCounter
	DeviceGetMemoryInfo                             = libnvml.DeviceGetMemoryInfo
	DeviceGetMemoryInfo_v2                          = libnvml.DeviceGetMemoryInfo_v2
	DeviceGetMigDeviceHandleByIndex                 = libnvml.DeviceGetMigDeviceHandleByIndex
	DeviceGetMigMode                                = libnvml.DeviceGetMigMode
	DeviceGetMinMaxClockOfPState                    = libnvml.DeviceGetMinMaxClockOfPState
	DeviceGetMinMaxFanSpeed                         = libnvml.DeviceGetMinMaxFanSpeed
	DeviceGetMinorNumber                            = libnvml.DeviceGetMinorNumber
	DeviceGetModuleId                               = libnvml.DeviceGetModuleId
	DeviceGetMultiGpuBoard                          = libnvml.DeviceGetMultiGpuBoard
	DeviceGetName                                   = libnvml.DeviceGetName
	DeviceGetNumFans                                = libnvml.DeviceGetNumFans
	DeviceGetNumGpuCores                            = libnvml.DeviceGetNumGpuCores
	DeviceGetNumaNodeId                             = libnvml.DeviceGetNumaNodeId
	DeviceGetNvLinkCapability                       = libnvml.DeviceGetNvLinkCapability
	DeviceGetNvLinkErrorCounter                     = libnvml.DeviceGetNvLinkErrorCounter
	DeviceGetNvLinkRemoteDeviceType                 = libnvml.DeviceGetNvLinkRemoteDeviceType
	DeviceGetNvLinkRemotePciInfo                    = libnvml.DeviceGetNvLinkRemotePciInfo
	DeviceGetNvLinkState                            = libnvml.DeviceGetNvLinkState
	DeviceGetNvLinkUtilizationControl               = libnvml.DeviceGetNvLinkUtilizationControl
	DeviceGetNvLinkUtilizationCounter               = libnvml.DeviceGetNvLinkUtilizationCounter
	DeviceGetNvLinkVersion                          = libnvml.DeviceGetNvLinkVersion
	DeviceGetOfaUtilization                         = libnvml.DeviceGetOfaUtilization
	DeviceGetP2PStatus                              = libnvml.DeviceGetP2PStatus
	DeviceGetPciInfo                                = libnvml.DeviceGetPciInfo
	DeviceGetPciInfoExt                             = libnvml.DeviceGetPciInfoExt
	DeviceGetPcieLinkMaxSpeed                       = libnvml.DeviceGetPcieLinkMaxSpeed
	DeviceGetPcieReplayCounter                      = libnvml.DeviceGetPcieReplayCounter
	DeviceGetPcieSpeed                              = libnvml.DeviceGetPcieSpeed
	DeviceGetPcieThroughput                         = libnvml.DeviceGetPcieThroughput
	DeviceGetPerformanceState                       = libnvml.DeviceGetPerformanceState
	DeviceGetPersistenceMode                        = libnvml.DeviceGetPersistenceMode
	DeviceGetPgpuMetadataString                     = libnvml.DeviceGetPgpuMetadataString
	DeviceGetPowerManagementDefaultLimit            = libnvml.DeviceGetPowerManagementDefaultLimit
	DeviceGetPowerManagementLimit                   = libnvml.DeviceGetPowerManagementLimit
	DeviceGetPowerManagementLimitConstraints        = libnvml.DeviceGetPowerManagementLimitConstraints
	DeviceGetPowerManagementMode                    = libnvml.DeviceGetPowerManagementMode
	DeviceGetPowerSource                            = libnvml.DeviceGetPowerSource
	DeviceGetPowerState                             = libnvml.DeviceGetPowerState
	DeviceGetPowerUsage                             = libnvml.DeviceGetPowerUsage
	DeviceGetProcessUtilization                     = libnvml.DeviceGetProcessUtilization
	DeviceGetProcessesUtilizationInfo               = libnvml.DeviceGetProcessesUtilizationInfo
	DeviceGetRemappedRows                           = libnvml.DeviceGetRemappedRows
	DeviceGetRetiredPages                           = libnvml.DeviceGetRetiredPages
	DeviceGetRetiredPagesPendingStatus              = libnvml.DeviceGetRetiredPagesPendingStatus
	DeviceGetRetiredPages_v2                        = libnvml.DeviceGetRetiredPages_v2
	DeviceGetRowRemapperHistogram                   = libnvml.DeviceGetRowRemapperHistogram
	DeviceGetRunningProcessDetailList               = libnvml.DeviceGetRunningProcessDetailList
	DeviceGetSamples                                = libnvml.DeviceGetSamples
	DeviceGetSerial                                 = libnvml.DeviceGetSerial
	DeviceGetSramEccErrorStatus                     = libnvml.DeviceGetSramEccErrorStatus
	DeviceGetSupportedClocksEventReasons            = libnvml.DeviceGetSupportedClocksEventReasons
	DeviceGetSupportedClocksThrottleReasons         = libnvml.DeviceGetSupportedClocksThrottleReasons
	DeviceGetSupportedEventTypes                    = libnvml.DeviceGetSupportedEventTypes
	DeviceGetSupportedGraphicsClocks                = libnvml.DeviceGetSupportedGraphicsClocks
	DeviceGetSupportedMemoryClocks                  = libnvml.DeviceGetSupportedMemoryClocks
	DeviceGetSupportedPerformanceStates             = libnvml.DeviceGetSupportedPerformanceStates
	DeviceGetSupportedVgpus                         = libnvml.DeviceGetSupportedVgpus
	DeviceGetTargetFanSpeed                         = libnvml.DeviceGetTargetFanSpeed
	DeviceGetTemperature                            = libnvml.DeviceGetTemperature
	DeviceGetTemperatureThreshold                   = libnvml.DeviceGetTemperatureThreshold
	DeviceGetThermalSettings                        = libnvml.DeviceGetThermalSettings
	DeviceGetTopologyCommonAncestor                 = libnvml.DeviceGetTopologyCommonAncestor
	DeviceGetTopologyNearestGpus                    = libnvml.DeviceGetTopologyNearestGpus
	DeviceGetTotalEccErrors                         = libnvml.DeviceGetTotalEccErrors
	DeviceGetTotalEnergyConsumption                 = libnvml.DeviceGetTotalEnergyConsumption
	DeviceGetUUID                                   = libnvml.DeviceGetUUID
	DeviceGetUtilizationRates                       = libnvml.DeviceGetUtilizationRates
	DeviceGetVbiosVersion                           = libnvml.DeviceGetVbiosVersion
	DeviceGetVgpuCapabilities                       = libnvml.DeviceGetVgpuCapabilities
	DeviceGetVgpuHeterogeneousMode                  = libnvml.DeviceGetVgpuHeterogeneousMode
	DeviceGetVgpuInstancesUtilizationInfo           = libnvml.DeviceGetVgpuInstancesUtilizationInfo
	DeviceGetVgpuMetadata                           = libnvml.DeviceGetVgpuMetadata
	DeviceGetVgpuProcessUtilization                 = libnvml.DeviceGetVgpuProcessUtilization
	DeviceGetVgpuProcessesUtilizationInfo           = libnvml.DeviceGetVgpuProcessesUtilizationInfo
	DeviceGetVgpuSchedulerCapabilities              = libnvml.DeviceGetVgpuSchedulerCapabilities
	DeviceGetVgpuSchedulerLog                       = libnvml.DeviceGetVgpuSchedulerLog
	DeviceGetVgpuSchedulerState                     = libnvml.DeviceGetVgpuSchedulerState
	DeviceGetVgpuTypeCreatablePlacements            = libnvml.DeviceGetVgpuTypeCreatablePlacements
	DeviceGetVgpuTypeSupportedPlacements            = libnvml.DeviceGetVgpuTypeSupportedPlacements
	DeviceGetVgpuUtilization                        = libnvml.DeviceGetVgpuUtilization
	DeviceGetViolationStatus                        = libnvml.DeviceGetViolationStatus
	DeviceGetVirtualizationMode                     = libnvml.DeviceGetVirtualizationMode
	DeviceIsMigDeviceHandle                         = libnvml.DeviceIsMigDeviceHandle
	DeviceModifyDrainState                          = libnvml.DeviceModifyDrainState
	DeviceOnSameBoard                               = libnvml.DeviceOnSameBoard
	DeviceQueryDrainState                           = libnvml.DeviceQueryDrainState
	DeviceRegisterEvents                            = libnvml.DeviceRegisterEvents
	DeviceRemoveGpu                                 = libnvml.DeviceRemoveGpu
	DeviceRemoveGpu_v2                              = libnvml.DeviceRemoveGpu_v2
	DeviceResetApplicationsClocks                   = libnvml.DeviceResetApplicationsClocks
	DeviceResetGpuLockedClocks                      = libnvml.DeviceResetGpuLockedClocks
	DeviceResetMemoryLockedClocks                   = libnvml.DeviceResetMemoryLockedClocks
	DeviceResetNvLinkErrorCounters                  = libnvml.DeviceResetNvLinkErrorCounters
	DeviceResetNvLinkUtilizationCounter             = libnvml.DeviceResetNvLinkUtilizationCounter
	DeviceSetAPIRestriction                         = libnvml.DeviceSetAPIRestriction
	DeviceSetAccountingMode                         = libnvml.DeviceSetAccountingMode
	DeviceSetApplicationsClocks                     = libnvml.DeviceSetApplicationsClocks
	DeviceSetAutoBoostedClocksEnabled               = libnvml.DeviceSetAutoBoostedClocksEnabled
	DeviceSetComputeMode                            = libnvml.DeviceSetComputeMode
	DeviceSetConfComputeUnprotectedMemSize          = libnvml.DeviceSetConfComputeUnprotectedMemSize
	DeviceSetCpuAffinity                            = libnvml.DeviceSetCpuAffinity
	DeviceSetDefaultAutoBoostedClocksEnabled        = libnvml.DeviceSetDefaultAutoBoostedClocksEnabled
	DeviceSetDefaultFanSpeed_v2                     = libnvml.DeviceSetDefaultFanSpeed_v2
	DeviceSetDriverModel                            = libnvml.DeviceSetDriverModel
	DeviceSetEccMode                                = libnvml.DeviceSetEccMode
	DeviceSetFanControlPolicy                       = libnvml.DeviceSetFanControlPolicy
	DeviceSetFanSpeed_v2                            = libnvml.DeviceSetFanSpeed_v2
	DeviceSetGpcClkVfOffset                         = libnvml.DeviceSetGpcClkVfOffset
	DeviceSetGpuLockedClocks                        = libnvml.DeviceSetGpuLockedClocks
	DeviceSetGpuOperationMode                       = libnvml.DeviceSetGpuOperationMode
	DeviceSetMemClkVfOffset                         = libnvml.DeviceSetMemClkVfOffset
	DeviceSetMemoryLockedClocks                     = libnvml.DeviceSetMemoryLockedClocks
	DeviceSetMigMode                                = libnvml.DeviceSetMigMode
	DeviceSetNvLinkDeviceLowPowerThreshold          = libnvml.DeviceSetNvLinkDeviceLowPowerThreshold
	DeviceSetNvLinkUtilizationControl               = libnvml.DeviceSetNvLinkUtilizationControl
	DeviceSetPersistenceMode                        = libnvml.DeviceSetPersistenceMode
	DeviceSetPowerManagementLimit                   = libnvml.DeviceSetPowerManagementLimit
	DeviceSetPowerManagementLimit_v2                = libnvml.DeviceSetPowerManagementLimit_v2
	DeviceSetTemperatureThreshold                   = libnvml.DeviceSetTemperatureThreshold
	DeviceSetVgpuCapabilities                       = libnvml.DeviceSetVgpuCapabilities
	DeviceSetVgpuHeterogeneousMode                  = libnvml.DeviceSetVgpuHeterogeneousMode
	DeviceSetVgpuSchedulerState                     = libnvml.DeviceSetVgpuSchedulerState
	DeviceSetVirtualizationMode                     = libnvml.DeviceSetVirtualizationMode
	DeviceValidateInforom                           = libnvml.DeviceValidateInforom
	ErrorString                                     = libnvml.ErrorString
	EventSetCreate                                  = libnvml.EventSetCreate
	EventSetFree                                    = libnvml.EventSetFree
	EventSetWait                                    = libnvml.EventSetWait
	Extensions                                      = libnvml.Extensions
	GetExcludedDeviceCount                          = libnvml.GetExcludedDeviceCount
	GetExcludedDeviceInfoByIndex                    = libnvml.GetExcludedDeviceInfoByIndex
	GetVgpuCompatibility                            = libnvml.GetVgpuCompatibility
	GetVgpuDriverCapabilities                       = libnvml.GetVgpuDriverCapabilities
	GetVgpuVersion                                  = libnvml.GetVgpuVersion
	GpmMetricsGet                                   = libnvml.GpmMetricsGet
	GpmMetricsGetV                                  = libnvml.GpmMetricsGetV
	GpmMigSampleGet                                 = libnvml.GpmMigSampleGet
	GpmQueryDeviceSupport                           = libnvml.GpmQueryDeviceSupport
	GpmQueryDeviceSupportV                          = libnvml.GpmQueryDeviceSupportV
	GpmQueryIfStreamingEnabled                      = libnvml.GpmQueryIfStreamingEnabled
	GpmSampleAlloc                                  = libnvml.GpmSampleAlloc
	GpmSampleFree                                   = libnvml.GpmSampleFree
	GpmSampleGet                                    = libnvml.GpmSampleGet
	GpmSetStreamingEnabled                          = libnvml.GpmSetStreamingEnabled
	GpuInstanceCreateComputeInstance                = libnvml.GpuInstanceCreateComputeInstance
	GpuInstanceCreateComputeInstanceWithPlacement   = libnvml.GpuInstanceCreateComputeInstanceWithPlacement
	GpuInstanceDestroy                              = libnvml.GpuInstanceDestroy
	GpuInstanceGetComputeInstanceById               = libnvml.GpuInstanceGetComputeInstanceById
	GpuInstanceGetComputeInstancePossiblePlacements = libnvml.GpuInstanceGetComputeInstancePossiblePlacements
	GpuInstanceGetComputeInstanceProfileInfo        = libnvml.GpuInstanceGetComputeInstanceProfileInfo
	GpuInstanceGetComputeInstanceProfileInfoV       = libnvml.GpuInstanceGetComputeInstanceProfileInfoV
	GpuInstanceGetComputeInstanceRemainingCapacity  = libnvml.GpuInstanceGetComputeInstanceRemainingCapacity
	GpuInstanceGetComputeInstances                  = libnvml.GpuInstanceGetComputeInstances
	GpuInstanceGetInfo                              = libnvml.GpuInstanceGetInfo
	Init                                            = libnvml.Init
	InitWithFlags                                   = libnvml.InitWithFlags
	SetVgpuVersion                                  = libnvml.SetVgpuVersion
	Shutdown                                        = libnvml.Shutdown
	SystemGetConfComputeCapabilities                = libnvml.SystemGetConfComputeCapabilities
	SystemGetConfComputeKeyRotationThresholdInfo    = libnvml.SystemGetConfComputeKeyRotationThresholdInfo
	SystemGetConfComputeSettings                    = libnvml.SystemGetConfComputeSettings
	SystemGetCudaDriverVersion                      = libnvml.SystemGetCudaDriverVersion
	SystemGetCudaDriverVersion_v2                   = libnvml.SystemGetCudaDriverVersion_v2
	SystemGetDriverVersion                          = libnvml.SystemGetDriverVersion
	SystemGetHicVersion                             = libnvml.SystemGetHicVersion
	SystemGetNVMLVersion                            = libnvml.SystemGetNVMLVersion
	SystemGetProcessName                            = libnvml.SystemGetProcessName
	SystemGetTopologyGpuSet                         = libnvml.SystemGetTopologyGpuSet
	SystemSetConfComputeKeyRotationThresholdInfo    = libnvml.SystemSetConfComputeKeyRotationThresholdInfo
	UnitGetCount                                    = libnvml.UnitGetCount
	UnitGetDevices                                  = libnvml.UnitGetDevices
	UnitGetFanSpeedInfo                             = libnvml.UnitGetFanSpeedInfo
	UnitGetHandleByIndex                            = libnvml.UnitGetHandleByIndex
	UnitGetLedState                                 = libnvml.UnitGetLedState
	UnitGetPsuInfo                                  = libnvml.UnitGetPsuInfo
	UnitGetTemperature                              = libnvml.UnitGetTemperature
	UnitGetUnitInfo                                 = libnvml.UnitGetUnitInfo
	UnitSetLedState                                 = libnvml.UnitSetLedState
	VgpuInstanceClearAccountingPids                 = libnvml.VgpuInstanceClearAccountingPids
	VgpuInstanceGetAccountingMode                   = libnvml.VgpuInstanceGetAccountingMode
	VgpuInstanceGetAccountingPids                   = libnvml.VgpuInstanceGetAccountingPids
	VgpuInstanceGetAccountingStats                  = libnvml.VgpuInstanceGetAccountingStats
	VgpuInstanceGetEccMode                          = libnvml.VgpuInstanceGetEccMode
	VgpuInstanceGetEncoderCapacity                  = libnvml.VgpuInstanceGetEncoderCapacity
	VgpuInstanceGetEncoderSessions                  = libnvml.VgpuInstanceGetEncoderSessions
	VgpuInstanceGetEncoderStats                     = libnvml.VgpuInstanceGetEncoderStats
	VgpuInstanceGetFBCSessions                      = libnvml.VgpuInstanceGetFBCSessions
	VgpuInstanceGetFBCStats                         = libnvml.VgpuInstanceGetFBCStats
	VgpuInstanceGetFbUsage                          = libnvml.VgpuInstanceGetFbUsage
	VgpuInstanceGetFrameRateLimit                   = libnvml.VgpuInstanceGetFrameRateLimit
	VgpuInstanceGetGpuInstanceId                    = libnvml.VgpuInstanceGetGpuInstanceId
	VgpuInstanceGetGpuPciId                         = libnvml.VgpuInstanceGetGpuPciId
	VgpuInstanceGetLicenseInfo                      = libnvml.VgpuInstanceGetLicenseInfo
	VgpuInstanceGetLicenseStatus                    = libnvml.VgpuInstanceGetLicenseStatus
	VgpuInstanceGetMdevUUID                         = libnvml.VgpuInstanceGetMdevUUID
	VgpuInstanceGetMetadata                         = libnvml.VgpuInstanceGetMetadata
	VgpuInstanceGetType                             = libnvml.VgpuInstanceGetType
	VgpuInstanceGetUUID                             = libnvml.VgpuInstanceGetUUID
	VgpuInstanceGetVmDriverVersion                  = libnvml.VgpuInstanceGetVmDriverVersion
	VgpuInstanceGetVmID                             = libnvml.VgpuInstanceGetVmID
	VgpuInstanceSetEncoderCapacity                  = libnvml.VgpuInstanceSetEncoderCapacity
	VgpuTypeGetCapabilities                         = libnvml.VgpuTypeGetCapabilities
	VgpuTypeGetClass                                = libnvml.VgpuTypeGetClass
	VgpuTypeGetDeviceID                             = libnvml.VgpuTypeGetDeviceID
	VgpuTypeGetFrameRateLimit                       = libnvml.VgpuTypeGetFrameRateLimit
	VgpuTypeGetFramebufferSize                      = libnvml.VgpuTypeGetFramebufferSize
	VgpuTypeGetGpuInstanceProfileId                 = libnvml.VgpuTypeGetGpuInstanceProfileId
	VgpuTypeGetLicense                              = libnvml.VgpuTypeGetLicense
	VgpuTypeGetMaxInstances                         = libnvml.VgpuTypeGetMaxInstances
	VgpuTypeGetMaxInstancesPerVm                    = libnvml.VgpuTypeGetMaxInstancesPerVm
	VgpuTypeGetName                                 = libnvml.VgpuTypeGetName
	VgpuTypeGetNumDisplayHeads                      = libnvml.VgpuTypeGetNumDisplayHeads
	VgpuTypeGetResolution                           = libnvml.VgpuTypeGetResolution
)

// Interface represents the interface for the library type.
//
//go:generate moq -out mock/interface.go -pkg mock . Interface:Interface
type Interface interface {
	ComputeInstanceDestroy(ComputeInstance) Return
	ComputeInstanceGetInfo(ComputeInstance) (ComputeInstanceInfo, Return)
	DeviceClearAccountingPids(Device) Return
	DeviceClearCpuAffinity(Device) Return
	DeviceClearEccErrorCounts(Device, EccCounterType) Return
	DeviceClearFieldValues(Device, []FieldValue) Return
	DeviceCreateGpuInstance(Device, *GpuInstanceProfileInfo) (GpuInstance, Return)
	DeviceCreateGpuInstanceWithPlacement(Device, *GpuInstanceProfileInfo, *GpuInstancePlacement) (GpuInstance, Return)
	DeviceDiscoverGpus() (PciInfo, Return)
	DeviceFreezeNvLinkUtilizationCounter(Device, int, int, EnableState) Return
	DeviceGetAPIRestriction(Device, RestrictedAPI) (EnableState, Return)
	DeviceGetAccountingBufferSize(Device) (int, Return)
	DeviceGetAccountingMode(Device) (EnableState, Return)
	DeviceGetAccountingPids(Device) ([]int, Return)
	DeviceGetAccountingStats(Device, uint32) (AccountingStats, Return)
	DeviceGetActiveVgpus(Device) ([]VgpuInstance, Return)
	DeviceGetAdaptiveClockInfoStatus(Device) (uint32, Return)
	DeviceGetApplicationsClock(Device, ClockType) (uint32, Return)
	DeviceGetArchitecture(Device) (DeviceArchitecture, Return)
	DeviceGetAttributes(Device) (DeviceAttributes, Return)
	DeviceGetAutoBoostedClocksEnabled(Device) (EnableState, EnableState, Return)
	DeviceGetBAR1MemoryInfo(Device) (BAR1Memory, Return)
	DeviceGetBoardId(Device) (uint32, Return)
	DeviceGetBoardPartNumber(Device) (string, Return)
	DeviceGetBrand(Device) (BrandType, Return)
	DeviceGetBridgeChipInfo(Device) (BridgeChipHierarchy, Return)
	DeviceGetBusType(Device) (BusType, Return)
	DeviceGetC2cModeInfoV(Device) C2cModeInfoHandler
	DeviceGetClkMonStatus(Device) (ClkMonStatus, Return)
	DeviceGetClock(Device, ClockType, ClockId) (uint32, Return)
	DeviceGetClockInfo(Device, ClockType) (uint32, Return)
	DeviceGetComputeInstanceId(Device) (int, Return)
	DeviceGetComputeMode(Device) (ComputeMode, Return)
	DeviceGetComputeRunningProcesses(Device) ([]ProcessInfo, Return)
	DeviceGetConfComputeGpuAttestationReport(Device) (ConfComputeGpuAttestationReport, Return)
	DeviceGetConfComputeGpuCertificate(Device) (ConfComputeGpuCertificate, Return)
	DeviceGetConfComputeMemSizeInfo(Device) (ConfComputeMemSizeInfo, Return)
	DeviceGetConfComputeProtectedMemoryUsage(Device) (Memory, Return)
	DeviceGetCount() (int, Return)
	DeviceGetCpuAffinity(Device, int) ([]uint, Return)
	DeviceGetCpuAffinityWithinScope(Device, int, AffinityScope) ([]uint, Return)
	DeviceGetCreatableVgpus(Device) ([]VgpuTypeId, Return)
	DeviceGetCudaComputeCapability(Device) (int, int, Return)
	DeviceGetCurrPcieLinkGeneration(Device) (int, Return)
	DeviceGetCurrPcieLinkWidth(Device) (int, Return)
	DeviceGetCurrentClocksEventReasons(Device) (uint64, Return)
	DeviceGetCurrentClocksThrottleReasons(Device) (uint64, Return)
	DeviceGetDecoderUtilization(Device) (uint32, uint32, Return)
	DeviceGetDefaultApplicationsClock(Device, ClockType) (uint32, Return)
	DeviceGetDefaultEccMode(Device) (EnableState, Return)
	DeviceGetDetailedEccErrors(Device, MemoryErrorType, EccCounterType) (EccErrorCounts, Return)
	DeviceGetDeviceHandleFromMigDeviceHandle(Device) (Device, Return)
	DeviceGetDisplayActive(Device) (EnableState, Return)
	DeviceGetDisplayMode(Device) (EnableState, Return)
	DeviceGetDriverModel(Device) (DriverModel, DriverModel, Return)
	DeviceGetDynamicPstatesInfo(Device) (GpuDynamicPstatesInfo, Return)
	DeviceGetEccMode(Device) (EnableState, EnableState, Return)
	DeviceGetEncoderCapacity(Device, EncoderType) (int, Return)
	DeviceGetEncoderSessions(Device) ([]EncoderSessionInfo, Return)
	DeviceGetEncoderStats(Device) (int, uint32, uint32, Return)
	DeviceGetEncoderUtilization(Device) (uint32, uint32, Return)
	DeviceGetEnforcedPowerLimit(Device) (uint32, Return)
	DeviceGetFBCSessions(Device) ([]FBCSessionInfo, Return)
	DeviceGetFBCStats(Device) (FBCStats, Return)
	DeviceGetFanControlPolicy_v2(Device, int) (FanControlPolicy, Return)
	DeviceGetFanSpeed(Device) (uint32, Return)
	DeviceGetFanSpeed_v2(Device, int) (uint32, Return)
	DeviceGetFieldValues(Device, []FieldValue) Return
	DeviceGetGpcClkMinMaxVfOffset(Device) (int, int, Return)
	DeviceGetGpcClkVfOffset(Device) (int, Return)
	DeviceGetGpuFabricInfo(Device) (GpuFabricInfo, Return)
	DeviceGetGpuFabricInfoV(Device) GpuFabricInfoHandler
	DeviceGetGpuInstanceById(Device, int) (GpuInstance, Return)
	DeviceGetGpuInstanceId(Device) (int, Return)
	DeviceGetGpuInstancePossiblePlacements(Device, *GpuInstanceProfileInfo) ([]GpuInstancePlacement, Return)
	DeviceGetGpuInstanceProfileInfo(Device, int) (GpuInstanceProfileInfo, Return)
	DeviceGetGpuInstanceProfileInfoV(Device, int) GpuInstanceProfileInfoHandler
	DeviceGetGpuInstanceRemainingCapacity(Device, *GpuInstanceProfileInfo) (int, Return)
	DeviceGetGpuInstances(Device, *GpuInstanceProfileInfo) ([]GpuInstance, Return)
	DeviceGetGpuMaxPcieLinkGeneration(Device) (int, Return)
	DeviceGetGpuOperationMode(Device) (GpuOperationMode, GpuOperationMode, Return)
	DeviceGetGraphicsRunningProcesses(Device) ([]ProcessInfo, Return)
	DeviceGetGridLicensableFeatures(Device) (GridLicensableFeatures, Return)
	DeviceGetGspFirmwareMode(Device) (bool, bool, Return)
	DeviceGetGspFirmwareVersion(Device) (string, Return)
	DeviceGetHandleByIndex(int) (Device, Return)
	DeviceGetHandleByPciBusId(string) (Device, Return)
	DeviceGetHandleBySerial(string) (Device, Return)
	DeviceGetHandleByUUID(string) (Device, Return)
	DeviceGetHostVgpuMode(Device) (HostVgpuMode, Return)
	DeviceGetIndex(Device) (int, Return)
	DeviceGetInforomConfigurationChecksum(Device) (uint32, Return)
	DeviceGetInforomImageVersion(Device) (string, Return)
	DeviceGetInforomVersion(Device, InforomObject) (string, Return)
	DeviceGetIrqNum(Device) (int, Return)
	DeviceGetJpgUtilization(Device) (uint32, uint32, Return)
	DeviceGetLastBBXFlushTime(Device) (uint64, uint, Return)
	DeviceGetMPSComputeRunningProcesses(Device) ([]ProcessInfo, Return)
	DeviceGetMaxClockInfo(Device, ClockType) (uint32, Return)
	DeviceGetMaxCustomerBoostClock(Device, ClockType) (uint32, Return)
	DeviceGetMaxMigDeviceCount(Device) (int, Return)
	DeviceGetMaxPcieLinkGeneration(Device) (int, Return)
	DeviceGetMaxPcieLinkWidth(Device) (int, Return)
	DeviceGetMemClkMinMaxVfOffset(Device) (int, int, Return)
	DeviceGetMemClkVfOffset(Device) (int, Return)
	DeviceGetMemoryAffinity(Device, int, AffinityScope) ([]uint, Return)
	DeviceGetMemoryBusWidth(Device) (uint32, Return)
	DeviceGetMemoryErrorCounter(Device, MemoryErrorType, EccCounterType, MemoryLocation) (uint64, Return)
	DeviceGetMemoryInfo(Device) (Memory, Return)
	DeviceGetMemoryInfo_v2(Device) (Memory_v2, Return)
	DeviceGetMigDeviceHandleByIndex(Device, int) (Device, Return)
	DeviceGetMigMode(Device) (int, int, Return)
	DeviceGetMinMaxClockOfPState(Device, ClockType, Pstates) (uint32, uint32, Return)
	DeviceGetMinMaxFanSpeed(Device) (int, int, Return)
	DeviceGetMinorNumber(Device) (int, Return)
	DeviceGetModuleId(Device) (int, Return)
	DeviceGetMultiGpuBoard(Device) (int, Return)
	DeviceGetName(Device) (string, Return)
	DeviceGetNumFans(Device) (int, Return)
	DeviceGetNumGpuCores(Device) (int, Return)
	DeviceGetNumaNodeId(Device) (int, Return)
	DeviceGetNvLinkCapability(Device, int, NvLinkCapability) (uint32, Return)
	DeviceGetNvLinkErrorCounter(Device, int, NvLinkErrorCounter) (uint64, Return)
	DeviceGetNvLinkRemoteDeviceType(Device, int) (IntNvLinkDeviceType, Return)
	DeviceGetNvLinkRemotePciInfo(Device, int) (PciInfo, Return)
	DeviceGetNvLinkState(Device, int) (EnableState, Return)
	DeviceGetNvLinkUtilizationControl(Device, int, int) (NvLinkUtilizationControl, Return)
	DeviceGetNvLinkUtilizationCounter(Device, int, int) (uint64, uint64, Return)
	DeviceGetNvLinkVersion(Device, int) (uint32, Return)
	DeviceGetOfaUtilization(Device) (uint32, uint32, Return)
	DeviceGetP2PStatus(Device, Device, GpuP2PCapsIndex) (GpuP2PStatus, Return)
	DeviceGetPciInfo(Device) (PciInfo, Return)
	DeviceGetPciInfoExt(Device) (PciInfoExt, Return)
	DeviceGetPcieLinkMaxSpeed(Device) (uint32, Return)
	DeviceGetPcieReplayCounter(Device) (int, Return)
	DeviceGetPcieSpeed(Device) (int, Return)
	DeviceGetPcieThroughput(Device, PcieUtilCounter) (uint32, Return)
	DeviceGetPerformanceState(Device) (Pstates, Return)
	DeviceGetPersistenceMode(Device) (EnableState, Return)
	DeviceGetPgpuMetadataString(Device) (string, Return)
	DeviceGetPowerManagementDefaultLimit(Device) (uint32, Return)
	DeviceGetPowerManagementLimit(Device) (uint32, Return)
	DeviceGetPowerManagementLimitConstraints(Device) (uint32, uint32, Return)
	DeviceGetPowerManagementMode(Device) (EnableState, Return)
	DeviceGetPowerSource(Device) (PowerSource, Return)
	DeviceGetPowerState(Device) (Pstates, Return)
	DeviceGetPowerUsage(Device) (uint32, Return)
	DeviceGetProcessUtilization(Device, uint64) ([]ProcessUtilizationSample, Return)
	DeviceGetProcessesUtilizationInfo(Device) (ProcessesUtilizationInfo, Return)
	DeviceGetRemappedRows(Device) (int, int, bool, bool, Return)
	DeviceGetRetiredPages(Device, PageRetirementCause) ([]uint64, Return)
	DeviceGetRetiredPagesPendingStatus(Device) (EnableState, Return)
	DeviceGetRetiredPages_v2(Device, PageRetirementCause) ([]uint64, []uint64, Return)
	DeviceGetRowRemapperHistogram(Device) (RowRemapperHistogramValues, Return)
	DeviceGetRunningProcessDetailList(Device) (ProcessDetailList, Return)
	DeviceGetSamples(Device, SamplingType, uint64) (ValueType, []Sample, Return)
	DeviceGetSerial(Device) (string, Return)
	DeviceGetSramEccErrorStatus(Device) (EccSramErrorStatus, Return)
	DeviceGetSupportedClocksEventReasons(Device) (uint64, Return)
	DeviceGetSupportedClocksThrottleReasons(Device) (uint64, Return)
	DeviceGetSupportedEventTypes(Device) (uint64, Return)
	DeviceGetSupportedGraphicsClocks(Device, int) (int, uint32, Return)
	DeviceGetSupportedMemoryClocks(Device) (int, uint32, Return)
	DeviceGetSupportedPerformanceStates(Device) ([]Pstates, Return)
	DeviceGetSupportedVgpus(Device) ([]VgpuTypeId, Return)
	DeviceGetTargetFanSpeed(Device, int) (int, Return)
	DeviceGetTemperature(Device, TemperatureSensors) (uint32, Return)
	DeviceGetTemperatureThreshold(Device, TemperatureThresholds) (uint32, Return)
	DeviceGetThermalSettings(Device, uint32) (GpuThermalSettings, Return)
	DeviceGetTopologyCommonAncestor(Device, Device) (GpuTopologyLevel, Return)
	DeviceGetTopologyNearestGpus(Device, GpuTopologyLevel) ([]Device, Return)
	DeviceGetTotalEccErrors(Device, MemoryErrorType, EccCounterType) (uint64, Return)
	DeviceGetTotalEnergyConsumption(Device) (uint64, Return)
	DeviceGetUUID(Device) (string, Return)
	DeviceGetUtilizationRates(Device) (Utilization, Return)
	DeviceGetVbiosVersion(Device) (string, Return)
	DeviceGetVgpuCapabilities(Device, DeviceVgpuCapability) (bool, Return)
	DeviceGetVgpuHeterogeneousMode(Device) (VgpuHeterogeneousMode, Return)
	DeviceGetVgpuInstancesUtilizationInfo(Device) (VgpuInstancesUtilizationInfo, Return)
	DeviceGetVgpuMetadata(Device) (VgpuPgpuMetadata, Return)
	DeviceGetVgpuProcessUtilization(Device, uint64) ([]VgpuProcessUtilizationSample, Return)
	DeviceGetVgpuProcessesUtilizationInfo(Device) (VgpuProcessesUtilizationInfo, Return)
	DeviceGetVgpuSchedulerCapabilities(Device) (VgpuSchedulerCapabilities, Return)
	DeviceGetVgpuSchedulerLog(Device) (VgpuSchedulerLog, Return)
	DeviceGetVgpuSchedulerState(Device) (VgpuSchedulerGetState, Return)
	DeviceGetVgpuTypeCreatablePlacements(Device, VgpuTypeId) (VgpuPlacementList, Return)
	DeviceGetVgpuTypeSupportedPlacements(Device, VgpuTypeId) (VgpuPlacementList, Return)
	DeviceGetVgpuUtilization(Device, uint64) (ValueType, []VgpuInstanceUtilizationSample, Return)
	DeviceGetViolationStatus(Device, PerfPolicyType) (ViolationTime, Return)
	DeviceGetVirtualizationMode(Device) (GpuVirtualizationMode, Return)
	DeviceIsMigDeviceHandle(Device) (bool, Return)
	DeviceModifyDrainState(*PciInfo, EnableState) Return
	DeviceOnSameBoard(Device, Device) (int, Return)
	DeviceQueryDrainState(*PciInfo) (EnableState, Return)
	DeviceRegisterEvents(Device, uint64, EventSet) Return
	DeviceRemoveGpu(*PciInfo) Return
	DeviceRemoveGpu_v2(*PciInfo, DetachGpuState, PcieLinkState) Return
	DeviceResetApplicationsClocks(Device) Return
	DeviceResetGpuLockedClocks(Device) Return
	DeviceResetMemoryLockedClocks(Device) Return
	DeviceResetNvLinkErrorCounters(Device, int) Return
	DeviceResetNvLinkUtilizationCounter(Device, int, int) Return
	DeviceSetAPIRestriction(Device, RestrictedAPI, EnableState) Return
	DeviceSetAccountingMode(Device, EnableState) Return
	DeviceSetApplicationsClocks(Device, uint32, uint32) Return
	DeviceSetAutoBoostedClocksEnabled(Device, EnableState) Return
	DeviceSetComputeMode(Device, ComputeMode) Return
	DeviceSetConfComputeUnprotectedMemSize(Device, uint64) Return
	DeviceSetCpuAffinity(Device) Return
	DeviceSetDefaultAutoBoostedClocksEnabled(Device, EnableState, uint32) Return
	DeviceSetDefaultFanSpeed_v2(Device, int) Return
	DeviceSetDriverModel(Device, DriverModel, uint32) Return
	DeviceSetEccMode(Device, EnableState) Return
	DeviceSetFanControlPolicy(Device, int, FanControlPolicy) Return
	DeviceSetFanSpeed_v2(Device, int, int) Return
	DeviceSetGpcClkVfOffset(Device, int) Return
	DeviceSetGpuLockedClocks(Device, uint32, uint32) Return
	DeviceSetGpuOperationMode(Device, GpuOperationMode) Return
	DeviceSetMemClkVfOffset(Device, int) Return
	DeviceSetMemoryLockedClocks(Device, uint32, uint32) Return
	DeviceSetMigMode(Device, int) (Return, Return)
	DeviceSetNvLinkDeviceLowPowerThreshold(Device, *NvLinkPowerThres) Return
	DeviceSetNvLinkUtilizationControl(Device, int, int, *NvLinkUtilizationControl, bool) Return
	DeviceSetPersistenceMode(Device, EnableState) Return
	DeviceSetPowerManagementLimit(Device, uint32) Return
	DeviceSetPowerManagementLimit_v2(Device, *PowerValue_v2) Return
	DeviceSetTemperatureThreshold(Device, TemperatureThresholds, int) Return
	DeviceSetVgpuCapabilities(Device, DeviceVgpuCapability, EnableState) Return
	DeviceSetVgpuHeterogeneousMode(Device, VgpuHeterogeneousMode) Return
	DeviceSetVgpuSchedulerState(Device, *VgpuSchedulerSetState) Return
	DeviceSetVirtualizationMode(Device, GpuVirtualizationMode) Return
	DeviceValidateInforom(Device) Return
	ErrorString(Return) string
	EventSetCreate() (EventSet, Return)
	EventSetFree(EventSet) Return
	EventSetWait(EventSet, uint32) (EventData, Return)
	Extensions() ExtendedInterface
	GetExcludedDeviceCount() (int, Return)
	GetExcludedDeviceInfoByIndex(int) (ExcludedDeviceInfo, Return)
	GetVgpuCompatibility(*VgpuMetadata, *VgpuPgpuMetadata) (VgpuPgpuCompatibility, Return)
	GetVgpuDriverCapabilities(VgpuDriverCapability) (bool, Return)
	GetVgpuVersion() (VgpuVersion, VgpuVersion, Return)
	GpmMetricsGet(*GpmMetricsGetType) Return
	GpmMetricsGetV(*GpmMetricsGetType) GpmMetricsGetVType
	GpmMigSampleGet(Device, int, GpmSample) Return
	GpmQueryDeviceSupport(Device) (GpmSupport, Return)
	GpmQueryDeviceSupportV(Device) GpmSupportV
	GpmQueryIfStreamingEnabled(Device) (uint32, Return)
	GpmSampleAlloc() (GpmSample, Return)
	GpmSampleFree(GpmSample) Return
	GpmSampleGet(Device, GpmSample) Return
	GpmSetStreamingEnabled(Device, uint32) Return
	GpuInstanceCreateComputeInstance(GpuInstance, *ComputeInstanceProfileInfo) (ComputeInstance, Return)
	GpuInstanceCreateComputeInstanceWithPlacement(GpuInstance, *ComputeInstanceProfileInfo, *ComputeInstancePlacement) (ComputeInstance, Return)
	GpuInstanceDestroy(GpuInstance) Return
	GpuInstanceGetComputeInstanceById(GpuInstance, int) (ComputeInstance, Return)
	GpuInstanceGetComputeInstancePossiblePlacements(GpuInstance, *ComputeInstanceProfileInfo) ([]ComputeInstancePlacement, Return)
	GpuInstanceGetComputeInstanceProfileInfo(GpuInstance, int, int) (ComputeInstanceProfileInfo, Return)
	GpuInstanceGetComputeInstanceProfileInfoV(GpuInstance, int, int) ComputeInstanceProfileInfoHandler
	GpuInstanceGetComputeInstanceRemainingCapacity(GpuInstance, *ComputeInstanceProfileInfo) (int, Return)
	GpuInstanceGetComputeInstances(GpuInstance, *ComputeInstanceProfileInfo) ([]ComputeInstance, Return)
	GpuInstanceGetInfo(GpuInstance) (GpuInstanceInfo, Return)
	Init() Return
	InitWithFlags(uint32) Return
	SetVgpuVersion(*VgpuVersion) Return
	Shutdown() Return
	SystemGetConfComputeCapabilities() (ConfComputeSystemCaps, Return)
	SystemGetConfComputeKeyRotationThresholdInfo() (ConfComputeGetKeyRotationThresholdInfo, Return)
	SystemGetConfComputeSettings() (SystemConfComputeSettings, Return)
	SystemGetCudaDriverVersion() (int, Return)
	SystemGetCudaDriverVersion_v2() (int, Return)
	SystemGetDriverVersion() (string, Return)
	SystemGetHicVersion() ([]HwbcEntry, Return)
	SystemGetNVMLVersion() (string, Return)
	SystemGetProcessName(int) (string, Return)
	SystemGetTopologyGpuSet(int) ([]Device, Return)
	SystemSetConfComputeKeyRotationThresholdInfo(ConfComputeSetKeyRotationThresholdInfo) Return
	UnitGetCount() (int, Return)
	UnitGetDevices(Unit) ([]Device, Return)
	UnitGetFanSpeedInfo(Unit) (UnitFanSpeeds, Return)
	UnitGetHandleByIndex(int) (Unit, Return)
	UnitGetLedState(Unit) (LedState, Return)
	UnitGetPsuInfo(Unit) (PSUInfo, Return)
	UnitGetTemperature(Unit, int) (uint32, Return)
	UnitGetUnitInfo(Unit) (UnitInfo, Return)
	UnitSetLedState(Unit, LedColor) Return
	VgpuInstanceClearAccountingPids(VgpuInstance) Return
	VgpuInstanceGetAccountingMode(VgpuInstance) (EnableState, Return)
	VgpuInstanceGetAccountingPids(VgpuInstance) ([]int, Return)
	VgpuInstanceGetAccountingStats(VgpuInstance, int) (AccountingStats, Return)
	VgpuInstanceGetEccMode(VgpuInstance) (EnableState, Return)
	VgpuInstanceGetEncoderCapacity(VgpuInstance) (int, Return)
	VgpuInstanceGetEncoderSessions(VgpuInstance) (int, EncoderSessionInfo, Return)
	VgpuInstanceGetEncoderStats(VgpuInstance) (int, uint32, uint32, Return)
	VgpuInstanceGetFBCSessions(VgpuInstance) (int, FBCSessionInfo, Return)
	VgpuInstanceGetFBCStats(VgpuInstance) (FBCStats, Return)
	VgpuInstanceGetFbUsage(VgpuInstance) (uint64, Return)
	VgpuInstanceGetFrameRateLimit(VgpuInstance) (uint32, Return)
	VgpuInstanceGetGpuInstanceId(VgpuInstance) (int, Return)
	VgpuInstanceGetGpuPciId(VgpuInstance) (string, Return)
	VgpuInstanceGetLicenseInfo(VgpuInstance) (VgpuLicenseInfo, Return)
	VgpuInstanceGetLicenseStatus(VgpuInstance) (int, Return)
	VgpuInstanceGetMdevUUID(VgpuInstance) (string, Return)
	VgpuInstanceGetMetadata(VgpuInstance) (VgpuMetadata, Return)
	VgpuInstanceGetType(VgpuInstance) (VgpuTypeId, Return)
	VgpuInstanceGetUUID(VgpuInstance) (string, Return)
	VgpuInstanceGetVmDriverVersion(VgpuInstance) (string, Return)
	VgpuInstanceGetVmID(VgpuInstance) (string, VgpuVmIdType, Return)
	VgpuInstanceSetEncoderCapacity(VgpuInstance, int) Return
	VgpuTypeGetCapabilities(VgpuTypeId, VgpuCapability) (bool, Return)
	VgpuTypeGetClass(VgpuTypeId) (string, Return)
	VgpuTypeGetDeviceID(VgpuTypeId) (uint64, uint64, Return)
	VgpuTypeGetFrameRateLimit(VgpuTypeId) (uint32, Return)
	VgpuTypeGetFramebufferSize(VgpuTypeId) (uint64, Return)
	VgpuTypeGetGpuInstanceProfileId(VgpuTypeId) (uint32, Return)
	VgpuTypeGetLicense(VgpuTypeId) (string, Return)
	VgpuTypeGetMaxInstances(Device, VgpuTypeId) (int, Return)
	VgpuTypeGetMaxInstancesPerVm(VgpuTypeId) (int, Return)
	VgpuTypeGetName(VgpuTypeId) (string, Return)
	VgpuTypeGetNumDisplayHeads(VgpuTypeId) (int, Return)
	VgpuTypeGetResolution(VgpuTypeId, int) (uint32, uint32, Return)
}

// Device represents the interface for the nvmlDevice type.
//
//go:generate moq -out mock/device.go -pkg mock . Device:Device
type Device interface {
	ClearAccountingPids() Return
	ClearCpuAffinity() Return
	ClearEccErrorCounts(EccCounterType) Return
	ClearFieldValues([]FieldValue) Return
	CreateGpuInstance(*GpuInstanceProfileInfo) (GpuInstance, Return)
	CreateGpuInstanceWithPlacement(*GpuInstanceProfileInfo, *GpuInstancePlacement) (GpuInstance, Return)
	FreezeNvLinkUtilizationCounter(int, int, EnableState) Return
	GetAPIRestriction(RestrictedAPI) (EnableState, Return)
	GetAccountingBufferSize() (int, Return)
	GetAccountingMode() (EnableState, Return)
	GetAccountingPids() ([]int, Return)
	GetAccountingStats(uint32) (AccountingStats, Return)
	GetActiveVgpus() ([]VgpuInstance, Return)
	GetAdaptiveClockInfoStatus() (uint32, Return)
	GetApplicationsClock(ClockType) (uint32, Return)
	GetArchitecture() (DeviceArchitecture, Return)
	GetAttributes() (DeviceAttributes, Return)
	GetAutoBoostedClocksEnabled() (EnableState, EnableState, Return)
	GetBAR1MemoryInfo() (BAR1Memory, Return)
	GetBoardId() (uint32, Return)
	GetBoardPartNumber() (string, Return)
	GetBrand() (BrandType, Return)
	GetBridgeChipInfo() (BridgeChipHierarchy, Return)
	GetBusType() (BusType, Return)
	GetC2cModeInfoV() C2cModeInfoHandler
	GetClkMonStatus() (ClkMonStatus, Return)
	GetClock(ClockType, ClockId) (uint32, Return)
	GetClockInfo(ClockType) (uint32, Return)
	GetComputeInstanceId() (int, Return)
	GetComputeMode() (ComputeMode, Return)
	GetComputeRunningProcesses() ([]ProcessInfo, Return)
	GetConfComputeGpuAttestationReport() (ConfComputeGpuAttestationReport, Return)
	GetConfComputeGpuCertificate() (ConfComputeGpuCertificate, Return)
	GetConfComputeMemSizeInfo() (ConfComputeMemSizeInfo, Return)
	GetConfComputeProtectedMemoryUsage() (Memory, Return)
	GetCpuAffinity(int) ([]uint, Return)
	GetCpuAffinityWithinScope(int, AffinityScope) ([]uint, Return)
	GetCreatableVgpus() ([]VgpuTypeId, Return)
	GetCudaComputeCapability() (int, int, Return)
	GetCurrPcieLinkGeneration() (int, Return)
	GetCurrPcieLinkWidth() (int, Return)
	GetCurrentClocksEventReasons() (uint64, Return)
	GetCurrentClocksThrottleReasons() (uint64, Return)
	GetDecoderUtilization() (uint32, uint32, Return)
	GetDefaultApplicationsClock(ClockType) (uint32, Return)
	GetDefaultEccMode() (EnableState, Return)
	GetDetailedEccErrors(MemoryErrorType, EccCounterType) (EccErrorCounts, Return)
	GetDeviceHandleFromMigDeviceHandle() (Device, Return)
	GetDisplayActive() (EnableState, Return)
	GetDisplayMode() (EnableState, Return)
	GetDriverModel() (DriverModel, DriverModel, Return)
	GetDynamicPstatesInfo() (GpuDynamicPstatesInfo, Return)
	GetEccMode() (EnableState, EnableState, Return)
	GetEncoderCapacity(EncoderType) (int, Return)
	GetEncoderSessions() ([]EncoderSessionInfo, Return)
	GetEncoderStats() (int, uint32, uint32, Return)
	GetEncoderUtilization() (uint32, uint32, Return)
	GetEnforcedPowerLimit() (uint32, Return)
	GetFBCSessions() ([]FBCSessionInfo, Return)
	GetFBCStats() (FBCStats, Return)
	GetFanControlPolicy_v2(int) (FanControlPolicy, Return)
	GetFanSpeed() (uint32, Return)
	GetFanSpeed_v2(int) (uint32, Return)
	GetFieldValues([]FieldValue) Return
	GetGpcClkMinMaxVfOffset() (int, int, Return)
	GetGpcClkVfOffset() (int, Return)
	GetGpuFabricInfo() (GpuFabricInfo, Return)
	GetGpuFabricInfoV() GpuFabricInfoHandler
	GetGpuInstanceById(int) (GpuInstance, Return)
	GetGpuInstanceId() (int, Return)
	GetGpuInstancePossiblePlacements(*GpuInstanceProfileInfo) ([]GpuInstancePlacement, Return)
	GetGpuInstanceProfileInfo(int) (GpuInstanceProfileInfo, Return)
	GetGpuInstanceProfileInfoV(int) GpuInstanceProfileInfoHandler
	GetGpuInstanceRemainingCapacity(*GpuInstanceProfileInfo) (int, Return)
	GetGpuInstances(*GpuInstanceProfileInfo) ([]GpuInstance, Return)
	GetGpuMaxPcieLinkGeneration() (int, Return)
	GetGpuOperationMode() (GpuOperationMode, GpuOperationMode, Return)
	GetGraphicsRunningProcesses() ([]ProcessInfo, Return)
	GetGridLicensableFeatures() (GridLicensableFeatures, Return)
	GetGspFirmwareMode() (bool, bool, Return)
	GetGspFirmwareVersion() (string, Return)
	GetHostVgpuMode() (HostVgpuMode, Return)
	GetIndex() (int, Return)
	GetInforomConfigurationChecksum() (uint32, Return)
	GetInforomImageVersion() (string, Return)
	GetInforomVersion(InforomObject) (string, Return)
	GetIrqNum() (int, Return)
	GetJpgUtilization() (uint32, uint32, Return)
	GetLastBBXFlushTime() (uint64, uint, Return)
	GetMPSComputeRunningProcesses() ([]ProcessInfo, Return)
	GetMaxClockInfo(ClockType) (uint32, Return)
	GetMaxCustomerBoostClock(ClockType) (uint32, Return)
	GetMaxMigDeviceCount() (int, Return)
	GetMaxPcieLinkGeneration() (int, Return)
	GetMaxPcieLinkWidth() (int, Return)
	GetMemClkMinMaxVfOffset() (int, int, Return)
	GetMemClkVfOffset() (int, Return)
	GetMemoryAffinity(int, AffinityScope) ([]uint, Return)
	GetMemoryBusWidth() (uint32, Return)
	GetMemoryErrorCounter(MemoryErrorType, EccCounterType, MemoryLocation) (uint64, Return)
	GetMemoryInfo() (Memory, Return)
	GetMemoryInfo_v2() (Memory_v2, Return)
	GetMigDeviceHandleByIndex(int) (Device, Return)
	GetMigMode() (int, int, Return)
	GetMinMaxClockOfPState(ClockType, Pstates) (uint32, uint32, Return)
	GetMinMaxFanSpeed() (int, int, Return)
	GetMinorNumber() (int, Return)
	GetModuleId() (int, Return)
	GetMultiGpuBoard() (int, Return)
	GetName() (string, Return)
	GetNumFans() (int, Return)
	GetNumGpuCores() (int, Return)
	GetNumaNodeId() (int, Return)
	GetNvLinkCapability(int, NvLinkCapability) (uint32, Return)
	GetNvLinkErrorCounter(int, NvLinkErrorCounter) (uint64, Return)
	GetNvLinkRemoteDeviceType(int) (IntNvLinkDeviceType, Return)
	GetNvLinkRemotePciInfo(int) (PciInfo, Return)
	GetNvLinkState(int) (EnableState, Return)
	GetNvLinkUtilizationControl(int, int) (NvLinkUtilizationControl, Return)
	GetNvLinkUtilizationCounter(int, int) (uint64, uint64, Return)
	GetNvLinkVersion(int) (uint32, Return)
	GetOfaUtilization() (uint32, uint32, Return)
	GetP2PStatus(Device, GpuP2PCapsIndex) (GpuP2PStatus, Return)
	GetPciInfo() (PciInfo, Return)
	GetPciInfoExt() (PciInfoExt, Return)
	GetPcieLinkMaxSpeed() (uint32, Return)
	GetPcieReplayCounter() (int, Return)
	GetPcieSpeed() (int, Return)
	GetPcieThroughput(PcieUtilCounter) (uint32, Return)
	GetPerformanceState() (Pstates, Return)
	GetPersistenceMode() (EnableState, Return)
	GetPgpuMetadataString() (string, Return)
	GetPowerManagementDefaultLimit() (uint32, Return)
	GetPowerManagementLimit() (uint32, Return)
	GetPowerManagementLimitConstraints() (uint32, uint32, Return)
	GetPowerManagementMode() (EnableState, Return)
	GetPowerSource() (PowerSource, Return)
	GetPowerState() (Pstates, Return)
	GetPowerUsage() (uint32, Return)
	GetProcessUtilization(uint64) ([]ProcessUtilizationSample, Return)
	GetProcessesUtilizationInfo() (ProcessesUtilizationInfo, Return)
	GetRemappedRows() (int, int, bool, bool, Return)
	GetRetiredPages(PageRetirementCause) ([]uint64, Return)
	GetRetiredPagesPendingStatus() (EnableState, Return)
	GetRetiredPages_v2(PageRetirementCause) ([]uint64, []uint64, Return)
	GetRowRemapperHistogram() (RowRemapperHistogramValues, Return)
	GetRunningProcessDetailList() (ProcessDetailList, Return)
	GetSamples(SamplingType, uint64) (ValueType, []Sample, Return)
	GetSerial() (string, Return)
	GetSramEccErrorStatus() (EccSramErrorStatus, Return)
	GetSupportedClocksEventReasons() (uint64, Return)
	GetSupportedClocksThrottleReasons() (uint64, Return)
	GetSupportedEventTypes() (uint64, Return)
	GetSupportedGraphicsClocks(int) (int, uint32, Return)
	GetSupportedMemoryClocks() (int, uint32, Return)
	GetSupportedPerformanceStates() ([]Pstates, Return)
	GetSupportedVgpus() ([]VgpuTypeId, Return)
	GetTargetFanSpeed(int) (int, Return)
	GetTemperature(TemperatureSensors) (uint32, Return)
	GetTemperatureThreshold(TemperatureThresholds) (uint32, Return)
	GetThermalSettings(uint32) (GpuThermalSettings, Return)
	GetTopologyCommonAncestor(Device) (GpuTopologyLevel, Return)
	GetTopologyNearestGpus(GpuTopologyLevel) ([]Device, Return)
	GetTotalEccErrors(MemoryErrorType, EccCounterType) (uint64, Return)
	GetTotalEnergyConsumption() (uint64, Return)
	GetUUID() (string, Return)
	GetUtilizationRates() (Utilization, Return)
	GetVbiosVersion() (string, Return)
	GetVgpuCapabilities(DeviceVgpuCapability) (bool, Return)
	GetVgpuHeterogeneousMode() (VgpuHeterogeneousMode, Return)
	GetVgpuInstancesUtilizationInfo() (VgpuInstancesUtilizationInfo, Return)
	GetVgpuMetadata() (VgpuPgpuMetadata, Return)
	GetVgpuProcessUtilization(uint64) ([]VgpuProcessUtilizationSample, Return)
	GetVgpuProcessesUtilizationInfo() (VgpuProcessesUtilizationInfo, Return)
	GetVgpuSchedulerCapabilities() (VgpuSchedulerCapabilities, Return)
	GetVgpuSchedulerLog() (VgpuSchedulerLog, Return)
	GetVgpuSchedulerState() (VgpuSchedulerGetState, Return)
	GetVgpuTypeCreatablePlacements(VgpuTypeId) (VgpuPlacementList, Return)
	GetVgpuTypeSupportedPlacements(VgpuTypeId) (VgpuPlacementList, Return)
	GetVgpuUtilization(uint64) (ValueType, []VgpuInstanceUtilizationSample, Return)
	GetViolationStatus(PerfPolicyType) (ViolationTime, Return)
	GetVirtualizationMode() (GpuVirtualizationMode, Return)
	GpmMigSampleGet(int, GpmSample) Return
	GpmQueryDeviceSupport() (GpmSupport, Return)
	GpmQueryDeviceSupportV() GpmSupportV
	GpmQueryIfStreamingEnabled() (uint32, Return)
	GpmSampleGet(GpmSample) Return
	GpmSetStreamingEnabled(uint32) Return
	IsMigDeviceHandle() (bool, Return)
	OnSameBoard(Device) (int, Return)
	RegisterEvents(uint64, EventSet) Return
	ResetApplicationsClocks() Return
	ResetGpuLockedClocks() Return
	ResetMemoryLockedClocks() Return
	ResetNvLinkErrorCounters(int) Return
	ResetNvLinkUtilizationCounter(int, int) Return
	SetAPIRestriction(RestrictedAPI, EnableState) Return
	SetAccountingMode(EnableState) Return
	SetApplicationsClocks(uint32, uint32) Return
	SetAutoBoostedClocksEnabled(EnableState) Return
	SetComputeMode(ComputeMode) Return
	SetConfComputeUnprotectedMemSize(uint64) Return
	SetCpuAffinity() Return
	SetDefaultAutoBoostedClocksEnabled(EnableState, uint32) Return
	SetDefaultFanSpeed_v2(int) Return
	SetDriverModel(DriverModel, uint32) Return
	SetEccMode(EnableState) Return
	SetFanControlPolicy(int, FanControlPolicy) Return
	SetFanSpeed_v2(int, int) Return
	SetGpcClkVfOffset(int) Return
	SetGpuLockedClocks(uint32, uint32) Return
	SetGpuOperationMode(GpuOperationMode) Return
	SetMemClkVfOffset(int) Return
	SetMemoryLockedClocks(uint32, uint32) Return
	SetMigMode(int) (Return, Return)
	SetNvLinkDeviceLowPowerThreshold(*NvLinkPowerThres) Return
	SetNvLinkUtilizationControl(int, int, *NvLinkUtilizationControl, bool) Return
	SetPersistenceMode(EnableState) Return
	SetPowerManagementLimit(uint32) Return
	SetPowerManagementLimit_v2(*PowerValue_v2) Return
	SetTemperatureThreshold(TemperatureThresholds, int) Return
	SetVgpuCapabilities(DeviceVgpuCapability, EnableState) Return
	SetVgpuHeterogeneousMode(VgpuHeterogeneousMode) Return
	SetVgpuSchedulerState(*VgpuSchedulerSetState) Return
	SetVirtualizationMode(GpuVirtualizationMode) Return
	ValidateInforom() Return
	VgpuTypeGetMaxInstances(VgpuTypeId) (int, Return)
}

// GpuInstance represents the interface for the nvmlGpuInstance type.
//
//go:generate moq -out mock/gpuinstance.go -pkg mock . GpuInstance:GpuInstance
type GpuInstance interface {
	CreateComputeInstance(*ComputeInstanceProfileInfo) (ComputeInstance, Return)
	CreateComputeInstanceWithPlacement(*ComputeInstanceProfileInfo, *ComputeInstancePlacement) (ComputeInstance, Return)
	Destroy() Return
	GetComputeInstanceById(int) (ComputeInstance, Return)
	GetComputeInstancePossiblePlacements(*ComputeInstanceProfileInfo) ([]ComputeInstancePlacement, Return)
	GetComputeInstanceProfileInfo(int, int) (ComputeInstanceProfileInfo, Return)
	GetComputeInstanceProfileInfoV(int, int) ComputeInstanceProfileInfoHandler
	GetComputeInstanceRemainingCapacity(*ComputeInstanceProfileInfo) (int, Return)
	GetComputeInstances(*ComputeInstanceProfileInfo) ([]ComputeInstance, Return)
	GetInfo() (GpuInstanceInfo, Return)
}

// ComputeInstance represents the interface for the nvmlComputeInstance type.
//
//go:generate moq -out mock/computeinstance.go -pkg mock . ComputeInstance:ComputeInstance
type ComputeInstance interface {
	Destroy() Return
	GetInfo() (ComputeInstanceInfo, Return)
}

// EventSet represents the interface for the nvmlEventSet type.
//
//go:generate moq -out mock/eventset.go -pkg mock . EventSet:EventSet
type EventSet interface {
	Free() Return
	Wait(uint32) (EventData, Return)
}

// GpmSample represents the interface for the nvmlGpmSample type.
//
//go:generate moq -out mock/gpmsample.go -pkg mock . GpmSample:GpmSample
type GpmSample interface {
	Free() Return
	Get(Device) Return
	MigGet(Device, int) Return
}

// Unit represents the interface for the nvmlUnit type.
//
//go:generate moq -out mock/unit.go -pkg mock . Unit:Unit
type Unit interface {
	GetDevices() ([]Device, Return)
	GetFanSpeedInfo() (UnitFanSpeeds, Return)
	GetLedState() (LedState, Return)
	GetPsuInfo() (PSUInfo, Return)
	GetTemperature(int) (uint32, Return)
	GetUnitInfo() (UnitInfo, Return)
	SetLedState(LedColor) Return
}

// VgpuInstance represents the interface for the nvmlVgpuInstance type.
//
//go:generate moq -out mock/vgpuinstance.go -pkg mock . VgpuInstance:VgpuInstance
type VgpuInstance interface {
	ClearAccountingPids() Return
	GetAccountingMode() (EnableState, Return)
	GetAccountingPids() ([]int, Return)
	GetAccountingStats(int) (AccountingStats, Return)
	GetEccMode() (EnableState, Return)
	GetEncoderCapacity() (int, Return)
	GetEncoderSessions() (int, EncoderSessionInfo, Return)
	GetEncoderStats() (int, uint32, uint32, Return)
	GetFBCSessions() (int, FBCSessionInfo, Return)
	GetFBCStats() (FBCStats, Return)
	GetFbUsage() (uint64, Return)
	GetFrameRateLimit() (uint32, Return)
	GetGpuInstanceId() (int, Return)
	GetGpuPciId() (string, Return)
	GetLicenseInfo() (VgpuLicenseInfo, Return)
	GetLicenseStatus() (int, Return)
	GetMdevUUID() (string, Return)
	GetMetadata() (VgpuMetadata, Return)
	GetType() (VgpuTypeId, Return)
	GetUUID() (string, Return)
	GetVmDriverVersion() (string, Return)
	GetVmID() (string, VgpuVmIdType, Return)
	SetEncoderCapacity(int) Return
}

// VgpuTypeId represents the interface for the nvmlVgpuTypeId type.
//
//go:generate moq -out mock/vgputypeid.go -pkg mock . VgpuTypeId:VgpuTypeId
type VgpuTypeId interface {
	GetCapabilities(VgpuCapability) (bool, Return)
	GetClass() (string, Return)
	GetCreatablePlacements(Device) (VgpuPlacementList, Return)
	GetDeviceID() (uint64, uint64, Return)
	GetFrameRateLimit() (uint32, Return)
	GetFramebufferSize() (uint64, Return)
	GetGpuInstanceProfileId() (uint32, Return)
	GetLicense() (string, Return)
	GetMaxInstances(Device) (int, Return)
	GetMaxInstancesPerVm() (int, Return)
	GetName() (string, Return)
	GetNumDisplayHeads() (int, Return)
	GetResolution(int) (uint32, uint32, Return)
	GetSupportedPlacements(Device) (VgpuPlacementList, Return)
}

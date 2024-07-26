// Copyright (c) 2020, NVIDIA CORPORATION.  All rights reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package nvml

import (
	"unsafe"
)

// nvml.VgpuMetadata
type VgpuMetadata struct {
	nvmlVgpuMetadata
	OpaqueData []byte
}

// nvml.VgpuPgpuMetadata
type VgpuPgpuMetadata struct {
	nvmlVgpuPgpuMetadata
	OpaqueData []byte
}

// nvml.VgpuTypeGetClass()
func (l *library) VgpuTypeGetClass(vgpuTypeId VgpuTypeId) (string, Return) {
	return vgpuTypeId.GetClass()
}

func (vgpuTypeId nvmlVgpuTypeId) GetClass() (string, Return) {
	var size uint32 = DEVICE_NAME_BUFFER_SIZE
	vgpuTypeClass := make([]byte, DEVICE_NAME_BUFFER_SIZE)
	ret := nvmlVgpuTypeGetClass(vgpuTypeId, &vgpuTypeClass[0], &size)
	return string(vgpuTypeClass[:clen(vgpuTypeClass)]), ret
}

// nvml.VgpuTypeGetName()
func (l *library) VgpuTypeGetName(vgpuTypeId VgpuTypeId) (string, Return) {
	return vgpuTypeId.GetName()
}

func (vgpuTypeId nvmlVgpuTypeId) GetName() (string, Return) {
	var size uint32 = DEVICE_NAME_BUFFER_SIZE
	vgpuTypeName := make([]byte, DEVICE_NAME_BUFFER_SIZE)
	ret := nvmlVgpuTypeGetName(vgpuTypeId, &vgpuTypeName[0], &size)
	return string(vgpuTypeName[:clen(vgpuTypeName)]), ret
}

// nvml.VgpuTypeGetGpuInstanceProfileId()
func (l *library) VgpuTypeGetGpuInstanceProfileId(vgpuTypeId VgpuTypeId) (uint32, Return) {
	return vgpuTypeId.GetGpuInstanceProfileId()
}

func (vgpuTypeId nvmlVgpuTypeId) GetGpuInstanceProfileId() (uint32, Return) {
	var size uint32
	ret := nvmlVgpuTypeGetGpuInstanceProfileId(vgpuTypeId, &size)
	return size, ret
}

// nvml.VgpuTypeGetDeviceID()
func (l *library) VgpuTypeGetDeviceID(vgpuTypeId VgpuTypeId) (uint64, uint64, Return) {
	return vgpuTypeId.GetDeviceID()
}

func (vgpuTypeId nvmlVgpuTypeId) GetDeviceID() (uint64, uint64, Return) {
	var deviceID, subsystemID uint64
	ret := nvmlVgpuTypeGetDeviceID(vgpuTypeId, &deviceID, &subsystemID)
	return deviceID, subsystemID, ret
}

// nvml.VgpuTypeGetFramebufferSize()
func (l *library) VgpuTypeGetFramebufferSize(vgpuTypeId VgpuTypeId) (uint64, Return) {
	return vgpuTypeId.GetFramebufferSize()
}

func (vgpuTypeId nvmlVgpuTypeId) GetFramebufferSize() (uint64, Return) {
	var fbSize uint64
	ret := nvmlVgpuTypeGetFramebufferSize(vgpuTypeId, &fbSize)
	return fbSize, ret
}

// nvml.VgpuTypeGetNumDisplayHeads()
func (l *library) VgpuTypeGetNumDisplayHeads(vgpuTypeId VgpuTypeId) (int, Return) {
	return vgpuTypeId.GetNumDisplayHeads()
}

func (vgpuTypeId nvmlVgpuTypeId) GetNumDisplayHeads() (int, Return) {
	var numDisplayHeads uint32
	ret := nvmlVgpuTypeGetNumDisplayHeads(vgpuTypeId, &numDisplayHeads)
	return int(numDisplayHeads), ret
}

// nvml.VgpuTypeGetResolution()
func (l *library) VgpuTypeGetResolution(vgpuTypeId VgpuTypeId, displayIndex int) (uint32, uint32, Return) {
	return vgpuTypeId.GetResolution(displayIndex)
}

func (vgpuTypeId nvmlVgpuTypeId) GetResolution(displayIndex int) (uint32, uint32, Return) {
	var xdim, ydim uint32
	ret := nvmlVgpuTypeGetResolution(vgpuTypeId, uint32(displayIndex), &xdim, &ydim)
	return xdim, ydim, ret
}

// nvml.VgpuTypeGetLicense()
func (l *library) VgpuTypeGetLicense(vgpuTypeId VgpuTypeId) (string, Return) {
	return vgpuTypeId.GetLicense()
}

func (vgpuTypeId nvmlVgpuTypeId) GetLicense() (string, Return) {
	vgpuTypeLicenseString := make([]byte, GRID_LICENSE_BUFFER_SIZE)
	ret := nvmlVgpuTypeGetLicense(vgpuTypeId, &vgpuTypeLicenseString[0], GRID_LICENSE_BUFFER_SIZE)
	return string(vgpuTypeLicenseString[:clen(vgpuTypeLicenseString)]), ret
}

// nvml.VgpuTypeGetFrameRateLimit()
func (l *library) VgpuTypeGetFrameRateLimit(vgpuTypeId VgpuTypeId) (uint32, Return) {
	return vgpuTypeId.GetFrameRateLimit()
}

func (vgpuTypeId nvmlVgpuTypeId) GetFrameRateLimit() (uint32, Return) {
	var frameRateLimit uint32
	ret := nvmlVgpuTypeGetFrameRateLimit(vgpuTypeId, &frameRateLimit)
	return frameRateLimit, ret
}

// nvml.VgpuTypeGetMaxInstances()
func (l *library) VgpuTypeGetMaxInstances(device Device, vgpuTypeId VgpuTypeId) (int, Return) {
	return vgpuTypeId.GetMaxInstances(device)
}

func (device nvmlDevice) VgpuTypeGetMaxInstances(vgpuTypeId VgpuTypeId) (int, Return) {
	return vgpuTypeId.GetMaxInstances(device)
}

func (vgpuTypeId nvmlVgpuTypeId) GetMaxInstances(device Device) (int, Return) {
	var vgpuInstanceCount uint32
	ret := nvmlVgpuTypeGetMaxInstances(nvmlDeviceHandle(device), vgpuTypeId, &vgpuInstanceCount)
	return int(vgpuInstanceCount), ret
}

// nvml.VgpuTypeGetMaxInstancesPerVm()
func (l *library) VgpuTypeGetMaxInstancesPerVm(vgpuTypeId VgpuTypeId) (int, Return) {
	return vgpuTypeId.GetMaxInstancesPerVm()
}

func (vgpuTypeId nvmlVgpuTypeId) GetMaxInstancesPerVm() (int, Return) {
	var vgpuInstanceCountPerVm uint32
	ret := nvmlVgpuTypeGetMaxInstancesPerVm(vgpuTypeId, &vgpuInstanceCountPerVm)
	return int(vgpuInstanceCountPerVm), ret
}

// nvml.VgpuInstanceGetVmID()
func (l *library) VgpuInstanceGetVmID(vgpuInstance VgpuInstance) (string, VgpuVmIdType, Return) {
	return vgpuInstance.GetVmID()
}

func (vgpuInstance nvmlVgpuInstance) GetVmID() (string, VgpuVmIdType, Return) {
	var vmIdType VgpuVmIdType
	vmId := make([]byte, DEVICE_UUID_BUFFER_SIZE)
	ret := nvmlVgpuInstanceGetVmID(vgpuInstance, &vmId[0], DEVICE_UUID_BUFFER_SIZE, &vmIdType)
	return string(vmId[:clen(vmId)]), vmIdType, ret
}

// nvml.VgpuInstanceGetUUID()
func (l *library) VgpuInstanceGetUUID(vgpuInstance VgpuInstance) (string, Return) {
	return vgpuInstance.GetUUID()
}

func (vgpuInstance nvmlVgpuInstance) GetUUID() (string, Return) {
	uuid := make([]byte, DEVICE_UUID_BUFFER_SIZE)
	ret := nvmlVgpuInstanceGetUUID(vgpuInstance, &uuid[0], DEVICE_UUID_BUFFER_SIZE)
	return string(uuid[:clen(uuid)]), ret
}

// nvml.VgpuInstanceGetVmDriverVersion()
func (l *library) VgpuInstanceGetVmDriverVersion(vgpuInstance VgpuInstance) (string, Return) {
	return vgpuInstance.GetVmDriverVersion()
}

func (vgpuInstance nvmlVgpuInstance) GetVmDriverVersion() (string, Return) {
	version := make([]byte, SYSTEM_DRIVER_VERSION_BUFFER_SIZE)
	ret := nvmlVgpuInstanceGetVmDriverVersion(vgpuInstance, &version[0], SYSTEM_DRIVER_VERSION_BUFFER_SIZE)
	return string(version[:clen(version)]), ret
}

// nvml.VgpuInstanceGetFbUsage()
func (l *library) VgpuInstanceGetFbUsage(vgpuInstance VgpuInstance) (uint64, Return) {
	return vgpuInstance.GetFbUsage()
}

func (vgpuInstance nvmlVgpuInstance) GetFbUsage() (uint64, Return) {
	var fbUsage uint64
	ret := nvmlVgpuInstanceGetFbUsage(vgpuInstance, &fbUsage)
	return fbUsage, ret
}

// nvml.VgpuInstanceGetLicenseInfo()
func (l *library) VgpuInstanceGetLicenseInfo(vgpuInstance VgpuInstance) (VgpuLicenseInfo, Return) {
	return vgpuInstance.GetLicenseInfo()
}

func (vgpuInstance nvmlVgpuInstance) GetLicenseInfo() (VgpuLicenseInfo, Return) {
	var licenseInfo VgpuLicenseInfo
	ret := nvmlVgpuInstanceGetLicenseInfo(vgpuInstance, &licenseInfo)
	return licenseInfo, ret
}

// nvml.VgpuInstanceGetLicenseStatus()
func (l *library) VgpuInstanceGetLicenseStatus(vgpuInstance VgpuInstance) (int, Return) {
	return vgpuInstance.GetLicenseStatus()
}

func (vgpuInstance nvmlVgpuInstance) GetLicenseStatus() (int, Return) {
	var licensed uint32
	ret := nvmlVgpuInstanceGetLicenseStatus(vgpuInstance, &licensed)
	return int(licensed), ret
}

// nvml.VgpuInstanceGetType()
func (l *library) VgpuInstanceGetType(vgpuInstance VgpuInstance) (VgpuTypeId, Return) {
	return vgpuInstance.GetType()
}

func (vgpuInstance nvmlVgpuInstance) GetType() (VgpuTypeId, Return) {
	var vgpuTypeId nvmlVgpuTypeId
	ret := nvmlVgpuInstanceGetType(vgpuInstance, &vgpuTypeId)
	return vgpuTypeId, ret
}

// nvml.VgpuInstanceGetFrameRateLimit()
func (l *library) VgpuInstanceGetFrameRateLimit(vgpuInstance VgpuInstance) (uint32, Return) {
	return vgpuInstance.GetFrameRateLimit()
}

func (vgpuInstance nvmlVgpuInstance) GetFrameRateLimit() (uint32, Return) {
	var frameRateLimit uint32
	ret := nvmlVgpuInstanceGetFrameRateLimit(vgpuInstance, &frameRateLimit)
	return frameRateLimit, ret
}

// nvml.VgpuInstanceGetEccMode()
func (l *library) VgpuInstanceGetEccMode(vgpuInstance VgpuInstance) (EnableState, Return) {
	return vgpuInstance.GetEccMode()
}

func (vgpuInstance nvmlVgpuInstance) GetEccMode() (EnableState, Return) {
	var eccMode EnableState
	ret := nvmlVgpuInstanceGetEccMode(vgpuInstance, &eccMode)
	return eccMode, ret
}

// nvml.VgpuInstanceGetEncoderCapacity()
func (l *library) VgpuInstanceGetEncoderCapacity(vgpuInstance VgpuInstance) (int, Return) {
	return vgpuInstance.GetEncoderCapacity()
}

func (vgpuInstance nvmlVgpuInstance) GetEncoderCapacity() (int, Return) {
	var encoderCapacity uint32
	ret := nvmlVgpuInstanceGetEncoderCapacity(vgpuInstance, &encoderCapacity)
	return int(encoderCapacity), ret
}

// nvml.VgpuInstanceSetEncoderCapacity()
func (l *library) VgpuInstanceSetEncoderCapacity(vgpuInstance VgpuInstance, encoderCapacity int) Return {
	return vgpuInstance.SetEncoderCapacity(encoderCapacity)
}

func (vgpuInstance nvmlVgpuInstance) SetEncoderCapacity(encoderCapacity int) Return {
	return nvmlVgpuInstanceSetEncoderCapacity(vgpuInstance, uint32(encoderCapacity))
}

// nvml.VgpuInstanceGetEncoderStats()
func (l *library) VgpuInstanceGetEncoderStats(vgpuInstance VgpuInstance) (int, uint32, uint32, Return) {
	return vgpuInstance.GetEncoderStats()
}

func (vgpuInstance nvmlVgpuInstance) GetEncoderStats() (int, uint32, uint32, Return) {
	var sessionCount, averageFps, averageLatency uint32
	ret := nvmlVgpuInstanceGetEncoderStats(vgpuInstance, &sessionCount, &averageFps, &averageLatency)
	return int(sessionCount), averageFps, averageLatency, ret
}

// nvml.VgpuInstanceGetEncoderSessions()
func (l *library) VgpuInstanceGetEncoderSessions(vgpuInstance VgpuInstance) (int, EncoderSessionInfo, Return) {
	return vgpuInstance.GetEncoderSessions()
}

func (vgpuInstance nvmlVgpuInstance) GetEncoderSessions() (int, EncoderSessionInfo, Return) {
	var sessionCount uint32
	var sessionInfo EncoderSessionInfo
	ret := nvmlVgpuInstanceGetEncoderSessions(vgpuInstance, &sessionCount, &sessionInfo)
	return int(sessionCount), sessionInfo, ret
}

// nvml.VgpuInstanceGetFBCStats()
func (l *library) VgpuInstanceGetFBCStats(vgpuInstance VgpuInstance) (FBCStats, Return) {
	return vgpuInstance.GetFBCStats()
}

func (vgpuInstance nvmlVgpuInstance) GetFBCStats() (FBCStats, Return) {
	var fbcStats FBCStats
	ret := nvmlVgpuInstanceGetFBCStats(vgpuInstance, &fbcStats)
	return fbcStats, ret
}

// nvml.VgpuInstanceGetFBCSessions()
func (l *library) VgpuInstanceGetFBCSessions(vgpuInstance VgpuInstance) (int, FBCSessionInfo, Return) {
	return vgpuInstance.GetFBCSessions()
}

func (vgpuInstance nvmlVgpuInstance) GetFBCSessions() (int, FBCSessionInfo, Return) {
	var sessionCount uint32
	var sessionInfo FBCSessionInfo
	ret := nvmlVgpuInstanceGetFBCSessions(vgpuInstance, &sessionCount, &sessionInfo)
	return int(sessionCount), sessionInfo, ret
}

// nvml.VgpuInstanceGetGpuInstanceId()
func (l *library) VgpuInstanceGetGpuInstanceId(vgpuInstance VgpuInstance) (int, Return) {
	return vgpuInstance.GetGpuInstanceId()
}

func (vgpuInstance nvmlVgpuInstance) GetGpuInstanceId() (int, Return) {
	var gpuInstanceId uint32
	ret := nvmlVgpuInstanceGetGpuInstanceId(vgpuInstance, &gpuInstanceId)
	return int(gpuInstanceId), ret
}

// nvml.VgpuInstanceGetGpuPciId()
func (l *library) VgpuInstanceGetGpuPciId(vgpuInstance VgpuInstance) (string, Return) {
	return vgpuInstance.GetGpuPciId()
}

func (vgpuInstance nvmlVgpuInstance) GetGpuPciId() (string, Return) {
	var length uint32 = 1 // Will be reduced upon returning
	for {
		vgpuPciId := make([]byte, length)
		ret := nvmlVgpuInstanceGetGpuPciId(vgpuInstance, &vgpuPciId[0], &length)
		if ret == SUCCESS {
			return string(vgpuPciId[:clen(vgpuPciId)]), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return "", ret
		}
		length *= 2
	}
}

// nvml.VgpuInstanceGetMetadata()
func (l *library) VgpuInstanceGetMetadata(vgpuInstance VgpuInstance) (VgpuMetadata, Return) {
	return vgpuInstance.GetMetadata()
}

func (vgpuInstance nvmlVgpuInstance) GetMetadata() (VgpuMetadata, Return) {
	var vgpuMetadata VgpuMetadata
	opaqueDataSize := unsafe.Sizeof(vgpuMetadata.nvmlVgpuMetadata.OpaqueData)
	vgpuMetadataSize := unsafe.Sizeof(vgpuMetadata.nvmlVgpuMetadata) - opaqueDataSize
	for {
		bufferSize := uint32(vgpuMetadataSize + opaqueDataSize)
		buffer := make([]byte, bufferSize)
		nvmlVgpuMetadataPtr := (*nvmlVgpuMetadata)(unsafe.Pointer(&buffer[0]))
		ret := nvmlVgpuInstanceGetMetadata(vgpuInstance, nvmlVgpuMetadataPtr, &bufferSize)
		if ret == SUCCESS {
			vgpuMetadata.nvmlVgpuMetadata = *nvmlVgpuMetadataPtr
			vgpuMetadata.OpaqueData = buffer[vgpuMetadataSize:bufferSize]
			return vgpuMetadata, ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return vgpuMetadata, ret
		}
		opaqueDataSize = 2 * opaqueDataSize
	}
}

// nvml.VgpuInstanceGetAccountingMode()
func (l *library) VgpuInstanceGetAccountingMode(vgpuInstance VgpuInstance) (EnableState, Return) {
	return vgpuInstance.GetAccountingMode()
}

func (vgpuInstance nvmlVgpuInstance) GetAccountingMode() (EnableState, Return) {
	var mode EnableState
	ret := nvmlVgpuInstanceGetAccountingMode(vgpuInstance, &mode)
	return mode, ret
}

// nvml.VgpuInstanceGetAccountingPids()
func (l *library) VgpuInstanceGetAccountingPids(vgpuInstance VgpuInstance) ([]int, Return) {
	return vgpuInstance.GetAccountingPids()
}

func (vgpuInstance nvmlVgpuInstance) GetAccountingPids() ([]int, Return) {
	var count uint32 = 1 // Will be reduced upon returning
	for {
		pids := make([]uint32, count)
		ret := nvmlVgpuInstanceGetAccountingPids(vgpuInstance, &count, &pids[0])
		if ret == SUCCESS {
			return uint32SliceToIntSlice(pids[:count]), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		count *= 2
	}
}

// nvml.VgpuInstanceGetAccountingStats()
func (l *library) VgpuInstanceGetAccountingStats(vgpuInstance VgpuInstance, pid int) (AccountingStats, Return) {
	return vgpuInstance.GetAccountingStats(pid)
}

func (vgpuInstance nvmlVgpuInstance) GetAccountingStats(pid int) (AccountingStats, Return) {
	var stats AccountingStats
	ret := nvmlVgpuInstanceGetAccountingStats(vgpuInstance, uint32(pid), &stats)
	return stats, ret
}

// nvml.GetVgpuCompatibility()
func (l *library) GetVgpuCompatibility(vgpuMetadata *VgpuMetadata, pgpuMetadata *VgpuPgpuMetadata) (VgpuPgpuCompatibility, Return) {
	var compatibilityInfo VgpuPgpuCompatibility
	ret := nvmlGetVgpuCompatibility(&vgpuMetadata.nvmlVgpuMetadata, &pgpuMetadata.nvmlVgpuPgpuMetadata, &compatibilityInfo)
	return compatibilityInfo, ret
}

// nvml.GetVgpuVersion()
func (l *library) GetVgpuVersion() (VgpuVersion, VgpuVersion, Return) {
	var supported, current VgpuVersion
	ret := nvmlGetVgpuVersion(&supported, &current)
	return supported, current, ret
}

// nvml.SetVgpuVersion()
func (l *library) SetVgpuVersion(vgpuVersion *VgpuVersion) Return {
	return nvmlSetVgpuVersion(vgpuVersion)
}

// nvml.VgpuInstanceClearAccountingPids()
func (l *library) VgpuInstanceClearAccountingPids(vgpuInstance VgpuInstance) Return {
	return vgpuInstance.ClearAccountingPids()
}

func (vgpuInstance nvmlVgpuInstance) ClearAccountingPids() Return {
	return nvmlVgpuInstanceClearAccountingPids(vgpuInstance)
}

// nvml.VgpuInstanceGetMdevUUID()
func (l *library) VgpuInstanceGetMdevUUID(vgpuInstance VgpuInstance) (string, Return) {
	return vgpuInstance.GetMdevUUID()
}

func (vgpuInstance nvmlVgpuInstance) GetMdevUUID() (string, Return) {
	mdevUUID := make([]byte, DEVICE_UUID_BUFFER_SIZE)
	ret := nvmlVgpuInstanceGetMdevUUID(vgpuInstance, &mdevUUID[0], DEVICE_UUID_BUFFER_SIZE)
	return string(mdevUUID[:clen(mdevUUID)]), ret
}

// nvml.VgpuTypeGetCapabilities()
func (l *library) VgpuTypeGetCapabilities(vgpuTypeId VgpuTypeId, capability VgpuCapability) (bool, Return) {
	return vgpuTypeId.GetCapabilities(capability)
}

func (vgpuTypeId nvmlVgpuTypeId) GetCapabilities(capability VgpuCapability) (bool, Return) {
	var capResult uint32
	ret := nvmlVgpuTypeGetCapabilities(vgpuTypeId, capability, &capResult)
	return (capResult != 0), ret
}

// nvml.GetVgpuDriverCapabilities()
func (l *library) GetVgpuDriverCapabilities(capability VgpuDriverCapability) (bool, Return) {
	var capResult uint32
	ret := nvmlGetVgpuDriverCapabilities(capability, &capResult)
	return (capResult != 0), ret
}

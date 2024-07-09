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
	"fmt"
	"reflect"
	"unsafe"
)

// nvmlDeviceHandle attempts to convert a device d to an nvmlDevice.
// This is required for functions such as GetTopologyCommonAncestor which
// accept Device arguments that need to be passed to internal nvml* functions
// as nvmlDevice parameters.
func nvmlDeviceHandle(d Device) nvmlDevice {
	var helper func(val reflect.Value) nvmlDevice
	helper = func(val reflect.Value) nvmlDevice {
		if val.Kind() == reflect.Interface {
			val = val.Elem()
		}

		if val.Kind() == reflect.Ptr {
			val = val.Elem()
		}

		if val.Type() == reflect.TypeOf(nvmlDevice{}) {
			return val.Interface().(nvmlDevice)
		}

		if val.Kind() != reflect.Struct {
			panic(fmt.Errorf("unable to convert non-struct type %v to nvmlDevice", val.Kind()))
		}

		for i := 0; i < val.Type().NumField(); i++ {
			if !val.Type().Field(i).Anonymous {
				continue
			}
			if !val.Field(i).Type().Implements(reflect.TypeOf((*Device)(nil)).Elem()) {
				continue
			}
			return helper(val.Field(i))
		}
		panic(fmt.Errorf("unable to convert %T to nvmlDevice", d))
	}
	return helper(reflect.ValueOf(d))
}

// EccBitType
type EccBitType = MemoryErrorType

// GpuInstanceInfo includes an interface type for Device instead of nvmlDevice
type GpuInstanceInfo struct {
	Device    Device
	Id        uint32
	ProfileId uint32
	Placement GpuInstancePlacement
}

func (g GpuInstanceInfo) convert() nvmlGpuInstanceInfo {
	out := nvmlGpuInstanceInfo{
		Device:    g.Device.(nvmlDevice),
		Id:        g.Id,
		ProfileId: g.ProfileId,
		Placement: g.Placement,
	}
	return out
}

func (g nvmlGpuInstanceInfo) convert() GpuInstanceInfo {
	out := GpuInstanceInfo{
		Device:    g.Device,
		Id:        g.Id,
		ProfileId: g.ProfileId,
		Placement: g.Placement,
	}
	return out
}

// ComputeInstanceInfo includes an interface type for Device instead of nvmlDevice
type ComputeInstanceInfo struct {
	Device      Device
	GpuInstance GpuInstance
	Id          uint32
	ProfileId   uint32
	Placement   ComputeInstancePlacement
}

func (c ComputeInstanceInfo) convert() nvmlComputeInstanceInfo {
	out := nvmlComputeInstanceInfo{
		Device:      c.Device.(nvmlDevice),
		GpuInstance: c.GpuInstance.(nvmlGpuInstance),
		Id:          c.Id,
		ProfileId:   c.ProfileId,
		Placement:   c.Placement,
	}
	return out
}

func (c nvmlComputeInstanceInfo) convert() ComputeInstanceInfo {
	out := ComputeInstanceInfo{
		Device:      c.Device,
		GpuInstance: c.GpuInstance,
		Id:          c.Id,
		ProfileId:   c.ProfileId,
		Placement:   c.Placement,
	}
	return out
}

// nvml.DeviceGetCount()
func (l *library) DeviceGetCount() (int, Return) {
	var deviceCount uint32
	ret := nvmlDeviceGetCount(&deviceCount)
	return int(deviceCount), ret
}

// nvml.DeviceGetHandleByIndex()
func (l *library) DeviceGetHandleByIndex(index int) (Device, Return) {
	var device nvmlDevice
	ret := nvmlDeviceGetHandleByIndex(uint32(index), &device)
	return device, ret
}

// nvml.DeviceGetHandleBySerial()
func (l *library) DeviceGetHandleBySerial(serial string) (Device, Return) {
	var device nvmlDevice
	ret := nvmlDeviceGetHandleBySerial(serial+string(rune(0)), &device)
	return device, ret
}

// nvml.DeviceGetHandleByUUID()
func (l *library) DeviceGetHandleByUUID(uuid string) (Device, Return) {
	var device nvmlDevice
	ret := nvmlDeviceGetHandleByUUID(uuid+string(rune(0)), &device)
	return device, ret
}

// nvml.DeviceGetHandleByPciBusId()
func (l *library) DeviceGetHandleByPciBusId(pciBusId string) (Device, Return) {
	var device nvmlDevice
	ret := nvmlDeviceGetHandleByPciBusId(pciBusId+string(rune(0)), &device)
	return device, ret
}

// nvml.DeviceGetName()
func (l *library) DeviceGetName(device Device) (string, Return) {
	return device.GetName()
}

func (device nvmlDevice) GetName() (string, Return) {
	name := make([]byte, DEVICE_NAME_V2_BUFFER_SIZE)
	ret := nvmlDeviceGetName(device, &name[0], DEVICE_NAME_V2_BUFFER_SIZE)
	return string(name[:clen(name)]), ret
}

// nvml.DeviceGetBrand()
func (l *library) DeviceGetBrand(device Device) (BrandType, Return) {
	return device.GetBrand()
}

func (device nvmlDevice) GetBrand() (BrandType, Return) {
	var brandType BrandType
	ret := nvmlDeviceGetBrand(device, &brandType)
	return brandType, ret
}

// nvml.DeviceGetIndex()
func (l *library) DeviceGetIndex(device Device) (int, Return) {
	return device.GetIndex()
}

func (device nvmlDevice) GetIndex() (int, Return) {
	var index uint32
	ret := nvmlDeviceGetIndex(device, &index)
	return int(index), ret
}

// nvml.DeviceGetSerial()
func (l *library) DeviceGetSerial(device Device) (string, Return) {
	return device.GetSerial()
}

func (device nvmlDevice) GetSerial() (string, Return) {
	serial := make([]byte, DEVICE_SERIAL_BUFFER_SIZE)
	ret := nvmlDeviceGetSerial(device, &serial[0], DEVICE_SERIAL_BUFFER_SIZE)
	return string(serial[:clen(serial)]), ret
}

// nvml.DeviceGetCpuAffinity()
func (l *library) DeviceGetCpuAffinity(device Device, numCPUs int) ([]uint, Return) {
	return device.GetCpuAffinity(numCPUs)
}

func (device nvmlDevice) GetCpuAffinity(numCPUs int) ([]uint, Return) {
	cpuSetSize := uint32((numCPUs-1)/int(unsafe.Sizeof(uint(0))) + 1)
	cpuSet := make([]uint, cpuSetSize)
	ret := nvmlDeviceGetCpuAffinity(device, cpuSetSize, &cpuSet[0])
	return cpuSet, ret
}

// nvml.DeviceSetCpuAffinity()
func (l *library) DeviceSetCpuAffinity(device Device) Return {
	return device.SetCpuAffinity()
}

func (device nvmlDevice) SetCpuAffinity() Return {
	return nvmlDeviceSetCpuAffinity(device)
}

// nvml.DeviceClearCpuAffinity()
func (l *library) DeviceClearCpuAffinity(device Device) Return {
	return device.ClearCpuAffinity()
}

func (device nvmlDevice) ClearCpuAffinity() Return {
	return nvmlDeviceClearCpuAffinity(device)
}

// nvml.DeviceGetMemoryAffinity()
func (l *library) DeviceGetMemoryAffinity(device Device, numNodes int, scope AffinityScope) ([]uint, Return) {
	return device.GetMemoryAffinity(numNodes, scope)
}

func (device nvmlDevice) GetMemoryAffinity(numNodes int, scope AffinityScope) ([]uint, Return) {
	nodeSetSize := uint32((numNodes-1)/int(unsafe.Sizeof(uint(0))) + 1)
	nodeSet := make([]uint, nodeSetSize)
	ret := nvmlDeviceGetMemoryAffinity(device, nodeSetSize, &nodeSet[0], scope)
	return nodeSet, ret
}

// nvml.DeviceGetCpuAffinityWithinScope()
func (l *library) DeviceGetCpuAffinityWithinScope(device Device, numCPUs int, scope AffinityScope) ([]uint, Return) {
	return device.GetCpuAffinityWithinScope(numCPUs, scope)
}

func (device nvmlDevice) GetCpuAffinityWithinScope(numCPUs int, scope AffinityScope) ([]uint, Return) {
	cpuSetSize := uint32((numCPUs-1)/int(unsafe.Sizeof(uint(0))) + 1)
	cpuSet := make([]uint, cpuSetSize)
	ret := nvmlDeviceGetCpuAffinityWithinScope(device, cpuSetSize, &cpuSet[0], scope)
	return cpuSet, ret
}

// nvml.DeviceGetTopologyCommonAncestor()
func (l *library) DeviceGetTopologyCommonAncestor(device1 Device, device2 Device) (GpuTopologyLevel, Return) {
	return device1.GetTopologyCommonAncestor(device2)
}

func (device1 nvmlDevice) GetTopologyCommonAncestor(device2 Device) (GpuTopologyLevel, Return) {
	var pathInfo GpuTopologyLevel
	ret := nvmlDeviceGetTopologyCommonAncestorStub(device1, nvmlDeviceHandle(device2), &pathInfo)
	return pathInfo, ret
}

// nvmlDeviceGetTopologyCommonAncestorStub allows us to override this for testing.
var nvmlDeviceGetTopologyCommonAncestorStub = nvmlDeviceGetTopologyCommonAncestor

// nvml.DeviceGetTopologyNearestGpus()
func (l *library) DeviceGetTopologyNearestGpus(device Device, level GpuTopologyLevel) ([]Device, Return) {
	return device.GetTopologyNearestGpus(level)
}

func (device nvmlDevice) GetTopologyNearestGpus(level GpuTopologyLevel) ([]Device, Return) {
	var count uint32
	ret := nvmlDeviceGetTopologyNearestGpus(device, level, &count, nil)
	if ret != SUCCESS {
		return nil, ret
	}
	if count == 0 {
		return []Device{}, ret
	}
	deviceArray := make([]nvmlDevice, count)
	ret = nvmlDeviceGetTopologyNearestGpus(device, level, &count, &deviceArray[0])
	return convertSlice[nvmlDevice, Device](deviceArray), ret
}

// nvml.DeviceGetP2PStatus()
func (l *library) DeviceGetP2PStatus(device1 Device, device2 Device, p2pIndex GpuP2PCapsIndex) (GpuP2PStatus, Return) {
	return device1.GetP2PStatus(device2, p2pIndex)
}

func (device1 nvmlDevice) GetP2PStatus(device2 Device, p2pIndex GpuP2PCapsIndex) (GpuP2PStatus, Return) {
	var p2pStatus GpuP2PStatus
	ret := nvmlDeviceGetP2PStatus(device1, nvmlDeviceHandle(device2), p2pIndex, &p2pStatus)
	return p2pStatus, ret
}

// nvml.DeviceGetUUID()
func (l *library) DeviceGetUUID(device Device) (string, Return) {
	return device.GetUUID()
}

func (device nvmlDevice) GetUUID() (string, Return) {
	uuid := make([]byte, DEVICE_UUID_V2_BUFFER_SIZE)
	ret := nvmlDeviceGetUUID(device, &uuid[0], DEVICE_UUID_V2_BUFFER_SIZE)
	return string(uuid[:clen(uuid)]), ret
}

// nvml.DeviceGetMinorNumber()
func (l *library) DeviceGetMinorNumber(device Device) (int, Return) {
	return device.GetMinorNumber()
}

func (device nvmlDevice) GetMinorNumber() (int, Return) {
	var minorNumber uint32
	ret := nvmlDeviceGetMinorNumber(device, &minorNumber)
	return int(minorNumber), ret
}

// nvml.DeviceGetBoardPartNumber()
func (l *library) DeviceGetBoardPartNumber(device Device) (string, Return) {
	return device.GetBoardPartNumber()
}

func (device nvmlDevice) GetBoardPartNumber() (string, Return) {
	partNumber := make([]byte, DEVICE_PART_NUMBER_BUFFER_SIZE)
	ret := nvmlDeviceGetBoardPartNumber(device, &partNumber[0], DEVICE_PART_NUMBER_BUFFER_SIZE)
	return string(partNumber[:clen(partNumber)]), ret
}

// nvml.DeviceGetInforomVersion()
func (l *library) DeviceGetInforomVersion(device Device, object InforomObject) (string, Return) {
	return device.GetInforomVersion(object)
}

func (device nvmlDevice) GetInforomVersion(object InforomObject) (string, Return) {
	version := make([]byte, DEVICE_INFOROM_VERSION_BUFFER_SIZE)
	ret := nvmlDeviceGetInforomVersion(device, object, &version[0], DEVICE_INFOROM_VERSION_BUFFER_SIZE)
	return string(version[:clen(version)]), ret
}

// nvml.DeviceGetInforomImageVersion()
func (l *library) DeviceGetInforomImageVersion(device Device) (string, Return) {
	return device.GetInforomImageVersion()
}

func (device nvmlDevice) GetInforomImageVersion() (string, Return) {
	version := make([]byte, DEVICE_INFOROM_VERSION_BUFFER_SIZE)
	ret := nvmlDeviceGetInforomImageVersion(device, &version[0], DEVICE_INFOROM_VERSION_BUFFER_SIZE)
	return string(version[:clen(version)]), ret
}

// nvml.DeviceGetInforomConfigurationChecksum()
func (l *library) DeviceGetInforomConfigurationChecksum(device Device) (uint32, Return) {
	return device.GetInforomConfigurationChecksum()
}

func (device nvmlDevice) GetInforomConfigurationChecksum() (uint32, Return) {
	var checksum uint32
	ret := nvmlDeviceGetInforomConfigurationChecksum(device, &checksum)
	return checksum, ret
}

// nvml.DeviceValidateInforom()
func (l *library) DeviceValidateInforom(device Device) Return {
	return device.ValidateInforom()
}

func (device nvmlDevice) ValidateInforom() Return {
	return nvmlDeviceValidateInforom(device)
}

// nvml.DeviceGetDisplayMode()
func (l *library) DeviceGetDisplayMode(device Device) (EnableState, Return) {
	return device.GetDisplayMode()
}

func (device nvmlDevice) GetDisplayMode() (EnableState, Return) {
	var display EnableState
	ret := nvmlDeviceGetDisplayMode(device, &display)
	return display, ret
}

// nvml.DeviceGetDisplayActive()
func (l *library) DeviceGetDisplayActive(device Device) (EnableState, Return) {
	return device.GetDisplayActive()
}

func (device nvmlDevice) GetDisplayActive() (EnableState, Return) {
	var isActive EnableState
	ret := nvmlDeviceGetDisplayActive(device, &isActive)
	return isActive, ret
}

// nvml.DeviceGetPersistenceMode()
func (l *library) DeviceGetPersistenceMode(device Device) (EnableState, Return) {
	return device.GetPersistenceMode()
}

func (device nvmlDevice) GetPersistenceMode() (EnableState, Return) {
	var mode EnableState
	ret := nvmlDeviceGetPersistenceMode(device, &mode)
	return mode, ret
}

// nvml.DeviceGetPciInfo()
func (l *library) DeviceGetPciInfo(device Device) (PciInfo, Return) {
	return device.GetPciInfo()
}

func (device nvmlDevice) GetPciInfo() (PciInfo, Return) {
	var pci PciInfo
	ret := nvmlDeviceGetPciInfo(device, &pci)
	return pci, ret
}

// nvml.DeviceGetMaxPcieLinkGeneration()
func (l *library) DeviceGetMaxPcieLinkGeneration(device Device) (int, Return) {
	return device.GetMaxPcieLinkGeneration()
}

func (device nvmlDevice) GetMaxPcieLinkGeneration() (int, Return) {
	var maxLinkGen uint32
	ret := nvmlDeviceGetMaxPcieLinkGeneration(device, &maxLinkGen)
	return int(maxLinkGen), ret
}

// nvml.DeviceGetMaxPcieLinkWidth()
func (l *library) DeviceGetMaxPcieLinkWidth(device Device) (int, Return) {
	return device.GetMaxPcieLinkWidth()
}

func (device nvmlDevice) GetMaxPcieLinkWidth() (int, Return) {
	var maxLinkWidth uint32
	ret := nvmlDeviceGetMaxPcieLinkWidth(device, &maxLinkWidth)
	return int(maxLinkWidth), ret
}

// nvml.DeviceGetCurrPcieLinkGeneration()
func (l *library) DeviceGetCurrPcieLinkGeneration(device Device) (int, Return) {
	return device.GetCurrPcieLinkGeneration()
}

func (device nvmlDevice) GetCurrPcieLinkGeneration() (int, Return) {
	var currLinkGen uint32
	ret := nvmlDeviceGetCurrPcieLinkGeneration(device, &currLinkGen)
	return int(currLinkGen), ret
}

// nvml.DeviceGetCurrPcieLinkWidth()
func (l *library) DeviceGetCurrPcieLinkWidth(device Device) (int, Return) {
	return device.GetCurrPcieLinkWidth()
}

func (device nvmlDevice) GetCurrPcieLinkWidth() (int, Return) {
	var currLinkWidth uint32
	ret := nvmlDeviceGetCurrPcieLinkWidth(device, &currLinkWidth)
	return int(currLinkWidth), ret
}

// nvml.DeviceGetPcieThroughput()
func (l *library) DeviceGetPcieThroughput(device Device, counter PcieUtilCounter) (uint32, Return) {
	return device.GetPcieThroughput(counter)
}

func (device nvmlDevice) GetPcieThroughput(counter PcieUtilCounter) (uint32, Return) {
	var value uint32
	ret := nvmlDeviceGetPcieThroughput(device, counter, &value)
	return value, ret
}

// nvml.DeviceGetPcieReplayCounter()
func (l *library) DeviceGetPcieReplayCounter(device Device) (int, Return) {
	return device.GetPcieReplayCounter()
}

func (device nvmlDevice) GetPcieReplayCounter() (int, Return) {
	var value uint32
	ret := nvmlDeviceGetPcieReplayCounter(device, &value)
	return int(value), ret
}

// nvml.nvmlDeviceGetClockInfo()
func (l *library) DeviceGetClockInfo(device Device, clockType ClockType) (uint32, Return) {
	return device.GetClockInfo(clockType)
}

func (device nvmlDevice) GetClockInfo(clockType ClockType) (uint32, Return) {
	var clock uint32
	ret := nvmlDeviceGetClockInfo(device, clockType, &clock)
	return clock, ret
}

// nvml.DeviceGetMaxClockInfo()
func (l *library) DeviceGetMaxClockInfo(device Device, clockType ClockType) (uint32, Return) {
	return device.GetMaxClockInfo(clockType)
}

func (device nvmlDevice) GetMaxClockInfo(clockType ClockType) (uint32, Return) {
	var clock uint32
	ret := nvmlDeviceGetMaxClockInfo(device, clockType, &clock)
	return clock, ret
}

// nvml.DeviceGetApplicationsClock()
func (l *library) DeviceGetApplicationsClock(device Device, clockType ClockType) (uint32, Return) {
	return device.GetApplicationsClock(clockType)
}

func (device nvmlDevice) GetApplicationsClock(clockType ClockType) (uint32, Return) {
	var clockMHz uint32
	ret := nvmlDeviceGetApplicationsClock(device, clockType, &clockMHz)
	return clockMHz, ret
}

// nvml.DeviceGetDefaultApplicationsClock()
func (l *library) DeviceGetDefaultApplicationsClock(device Device, clockType ClockType) (uint32, Return) {
	return device.GetDefaultApplicationsClock(clockType)
}

func (device nvmlDevice) GetDefaultApplicationsClock(clockType ClockType) (uint32, Return) {
	var clockMHz uint32
	ret := nvmlDeviceGetDefaultApplicationsClock(device, clockType, &clockMHz)
	return clockMHz, ret
}

// nvml.DeviceResetApplicationsClocks()
func (l *library) DeviceResetApplicationsClocks(device Device) Return {
	return device.ResetApplicationsClocks()
}

func (device nvmlDevice) ResetApplicationsClocks() Return {
	return nvmlDeviceResetApplicationsClocks(device)
}

// nvml.DeviceGetClock()
func (l *library) DeviceGetClock(device Device, clockType ClockType, clockId ClockId) (uint32, Return) {
	return device.GetClock(clockType, clockId)
}

func (device nvmlDevice) GetClock(clockType ClockType, clockId ClockId) (uint32, Return) {
	var clockMHz uint32
	ret := nvmlDeviceGetClock(device, clockType, clockId, &clockMHz)
	return clockMHz, ret
}

// nvml.DeviceGetMaxCustomerBoostClock()
func (l *library) DeviceGetMaxCustomerBoostClock(device Device, clockType ClockType) (uint32, Return) {
	return device.GetMaxCustomerBoostClock(clockType)
}

func (device nvmlDevice) GetMaxCustomerBoostClock(clockType ClockType) (uint32, Return) {
	var clockMHz uint32
	ret := nvmlDeviceGetMaxCustomerBoostClock(device, clockType, &clockMHz)
	return clockMHz, ret
}

// nvml.DeviceGetSupportedMemoryClocks()
func (l *library) DeviceGetSupportedMemoryClocks(device Device) (int, uint32, Return) {
	return device.GetSupportedMemoryClocks()
}

func (device nvmlDevice) GetSupportedMemoryClocks() (int, uint32, Return) {
	var count, clocksMHz uint32
	ret := nvmlDeviceGetSupportedMemoryClocks(device, &count, &clocksMHz)
	return int(count), clocksMHz, ret
}

// nvml.DeviceGetSupportedGraphicsClocks()
func (l *library) DeviceGetSupportedGraphicsClocks(device Device, memoryClockMHz int) (int, uint32, Return) {
	return device.GetSupportedGraphicsClocks(memoryClockMHz)
}

func (device nvmlDevice) GetSupportedGraphicsClocks(memoryClockMHz int) (int, uint32, Return) {
	var count, clocksMHz uint32
	ret := nvmlDeviceGetSupportedGraphicsClocks(device, uint32(memoryClockMHz), &count, &clocksMHz)
	return int(count), clocksMHz, ret
}

// nvml.DeviceGetAutoBoostedClocksEnabled()
func (l *library) DeviceGetAutoBoostedClocksEnabled(device Device) (EnableState, EnableState, Return) {
	return device.GetAutoBoostedClocksEnabled()
}

func (device nvmlDevice) GetAutoBoostedClocksEnabled() (EnableState, EnableState, Return) {
	var isEnabled, defaultIsEnabled EnableState
	ret := nvmlDeviceGetAutoBoostedClocksEnabled(device, &isEnabled, &defaultIsEnabled)
	return isEnabled, defaultIsEnabled, ret
}

// nvml.DeviceSetAutoBoostedClocksEnabled()
func (l *library) DeviceSetAutoBoostedClocksEnabled(device Device, enabled EnableState) Return {
	return device.SetAutoBoostedClocksEnabled(enabled)
}

func (device nvmlDevice) SetAutoBoostedClocksEnabled(enabled EnableState) Return {
	return nvmlDeviceSetAutoBoostedClocksEnabled(device, enabled)
}

// nvml.DeviceSetDefaultAutoBoostedClocksEnabled()
func (l *library) DeviceSetDefaultAutoBoostedClocksEnabled(device Device, enabled EnableState, flags uint32) Return {
	return device.SetDefaultAutoBoostedClocksEnabled(enabled, flags)
}

func (device nvmlDevice) SetDefaultAutoBoostedClocksEnabled(enabled EnableState, flags uint32) Return {
	return nvmlDeviceSetDefaultAutoBoostedClocksEnabled(device, enabled, flags)
}

// nvml.DeviceGetFanSpeed()
func (l *library) DeviceGetFanSpeed(device Device) (uint32, Return) {
	return device.GetFanSpeed()
}

func (device nvmlDevice) GetFanSpeed() (uint32, Return) {
	var speed uint32
	ret := nvmlDeviceGetFanSpeed(device, &speed)
	return speed, ret
}

// nvml.DeviceGetFanSpeed_v2()
func (l *library) DeviceGetFanSpeed_v2(device Device, fan int) (uint32, Return) {
	return device.GetFanSpeed_v2(fan)
}

func (device nvmlDevice) GetFanSpeed_v2(fan int) (uint32, Return) {
	var speed uint32
	ret := nvmlDeviceGetFanSpeed_v2(device, uint32(fan), &speed)
	return speed, ret
}

// nvml.DeviceGetNumFans()
func (l *library) DeviceGetNumFans(device Device) (int, Return) {
	return device.GetNumFans()
}

func (device nvmlDevice) GetNumFans() (int, Return) {
	var numFans uint32
	ret := nvmlDeviceGetNumFans(device, &numFans)
	return int(numFans), ret
}

// nvml.DeviceGetTemperature()
func (l *library) DeviceGetTemperature(device Device, sensorType TemperatureSensors) (uint32, Return) {
	return device.GetTemperature(sensorType)
}

func (device nvmlDevice) GetTemperature(sensorType TemperatureSensors) (uint32, Return) {
	var temp uint32
	ret := nvmlDeviceGetTemperature(device, sensorType, &temp)
	return temp, ret
}

// nvml.DeviceGetTemperatureThreshold()
func (l *library) DeviceGetTemperatureThreshold(device Device, thresholdType TemperatureThresholds) (uint32, Return) {
	return device.GetTemperatureThreshold(thresholdType)
}

func (device nvmlDevice) GetTemperatureThreshold(thresholdType TemperatureThresholds) (uint32, Return) {
	var temp uint32
	ret := nvmlDeviceGetTemperatureThreshold(device, thresholdType, &temp)
	return temp, ret
}

// nvml.DeviceSetTemperatureThreshold()
func (l *library) DeviceSetTemperatureThreshold(device Device, thresholdType TemperatureThresholds, temp int) Return {
	return device.SetTemperatureThreshold(thresholdType, temp)
}

func (device nvmlDevice) SetTemperatureThreshold(thresholdType TemperatureThresholds, temp int) Return {
	t := int32(temp)
	ret := nvmlDeviceSetTemperatureThreshold(device, thresholdType, &t)
	return ret
}

// nvml.DeviceGetPerformanceState()
func (l *library) DeviceGetPerformanceState(device Device) (Pstates, Return) {
	return device.GetPerformanceState()
}

func (device nvmlDevice) GetPerformanceState() (Pstates, Return) {
	var pState Pstates
	ret := nvmlDeviceGetPerformanceState(device, &pState)
	return pState, ret
}

// nvml.DeviceGetCurrentClocksThrottleReasons()
func (l *library) DeviceGetCurrentClocksThrottleReasons(device Device) (uint64, Return) {
	return device.GetCurrentClocksThrottleReasons()
}

func (device nvmlDevice) GetCurrentClocksThrottleReasons() (uint64, Return) {
	var clocksThrottleReasons uint64
	ret := nvmlDeviceGetCurrentClocksThrottleReasons(device, &clocksThrottleReasons)
	return clocksThrottleReasons, ret
}

// nvml.DeviceGetSupportedClocksThrottleReasons()
func (l *library) DeviceGetSupportedClocksThrottleReasons(device Device) (uint64, Return) {
	return device.GetSupportedClocksThrottleReasons()
}

func (device nvmlDevice) GetSupportedClocksThrottleReasons() (uint64, Return) {
	var supportedClocksThrottleReasons uint64
	ret := nvmlDeviceGetSupportedClocksThrottleReasons(device, &supportedClocksThrottleReasons)
	return supportedClocksThrottleReasons, ret
}

// nvml.DeviceGetPowerState()
func (l *library) DeviceGetPowerState(device Device) (Pstates, Return) {
	return device.GetPowerState()
}

func (device nvmlDevice) GetPowerState() (Pstates, Return) {
	var pState Pstates
	ret := nvmlDeviceGetPowerState(device, &pState)
	return pState, ret
}

// nvml.DeviceGetPowerManagementMode()
func (l *library) DeviceGetPowerManagementMode(device Device) (EnableState, Return) {
	return device.GetPowerManagementMode()
}

func (device nvmlDevice) GetPowerManagementMode() (EnableState, Return) {
	var mode EnableState
	ret := nvmlDeviceGetPowerManagementMode(device, &mode)
	return mode, ret
}

// nvml.DeviceGetPowerManagementLimit()
func (l *library) DeviceGetPowerManagementLimit(device Device) (uint32, Return) {
	return device.GetPowerManagementLimit()
}

func (device nvmlDevice) GetPowerManagementLimit() (uint32, Return) {
	var limit uint32
	ret := nvmlDeviceGetPowerManagementLimit(device, &limit)
	return limit, ret
}

// nvml.DeviceGetPowerManagementLimitConstraints()
func (l *library) DeviceGetPowerManagementLimitConstraints(device Device) (uint32, uint32, Return) {
	return device.GetPowerManagementLimitConstraints()
}

func (device nvmlDevice) GetPowerManagementLimitConstraints() (uint32, uint32, Return) {
	var minLimit, maxLimit uint32
	ret := nvmlDeviceGetPowerManagementLimitConstraints(device, &minLimit, &maxLimit)
	return minLimit, maxLimit, ret
}

// nvml.DeviceGetPowerManagementDefaultLimit()
func (l *library) DeviceGetPowerManagementDefaultLimit(device Device) (uint32, Return) {
	return device.GetPowerManagementDefaultLimit()
}

func (device nvmlDevice) GetPowerManagementDefaultLimit() (uint32, Return) {
	var defaultLimit uint32
	ret := nvmlDeviceGetPowerManagementDefaultLimit(device, &defaultLimit)
	return defaultLimit, ret
}

// nvml.DeviceGetPowerUsage()
func (l *library) DeviceGetPowerUsage(device Device) (uint32, Return) {
	return device.GetPowerUsage()
}

func (device nvmlDevice) GetPowerUsage() (uint32, Return) {
	var power uint32
	ret := nvmlDeviceGetPowerUsage(device, &power)
	return power, ret
}

// nvml.DeviceGetTotalEnergyConsumption()
func (l *library) DeviceGetTotalEnergyConsumption(device Device) (uint64, Return) {
	return device.GetTotalEnergyConsumption()
}

func (device nvmlDevice) GetTotalEnergyConsumption() (uint64, Return) {
	var energy uint64
	ret := nvmlDeviceGetTotalEnergyConsumption(device, &energy)
	return energy, ret
}

// nvml.DeviceGetEnforcedPowerLimit()
func (l *library) DeviceGetEnforcedPowerLimit(device Device) (uint32, Return) {
	return device.GetEnforcedPowerLimit()
}

func (device nvmlDevice) GetEnforcedPowerLimit() (uint32, Return) {
	var limit uint32
	ret := nvmlDeviceGetEnforcedPowerLimit(device, &limit)
	return limit, ret
}

// nvml.DeviceGetGpuOperationMode()
func (l *library) DeviceGetGpuOperationMode(device Device) (GpuOperationMode, GpuOperationMode, Return) {
	return device.GetGpuOperationMode()
}

func (device nvmlDevice) GetGpuOperationMode() (GpuOperationMode, GpuOperationMode, Return) {
	var current, pending GpuOperationMode
	ret := nvmlDeviceGetGpuOperationMode(device, &current, &pending)
	return current, pending, ret
}

// nvml.DeviceGetMemoryInfo()
func (l *library) DeviceGetMemoryInfo(device Device) (Memory, Return) {
	return device.GetMemoryInfo()
}

func (device nvmlDevice) GetMemoryInfo() (Memory, Return) {
	var memory Memory
	ret := nvmlDeviceGetMemoryInfo(device, &memory)
	return memory, ret
}

// nvml.DeviceGetMemoryInfo_v2()
func (l *library) DeviceGetMemoryInfo_v2(device Device) (Memory_v2, Return) {
	return device.GetMemoryInfo_v2()
}

func (device nvmlDevice) GetMemoryInfo_v2() (Memory_v2, Return) {
	var memory Memory_v2
	memory.Version = STRUCT_VERSION(memory, 2)
	ret := nvmlDeviceGetMemoryInfo_v2(device, &memory)
	return memory, ret
}

// nvml.DeviceGetComputeMode()
func (l *library) DeviceGetComputeMode(device Device) (ComputeMode, Return) {
	return device.GetComputeMode()
}

func (device nvmlDevice) GetComputeMode() (ComputeMode, Return) {
	var mode ComputeMode
	ret := nvmlDeviceGetComputeMode(device, &mode)
	return mode, ret
}

// nvml.DeviceGetCudaComputeCapability()
func (l *library) DeviceGetCudaComputeCapability(device Device) (int, int, Return) {
	return device.GetCudaComputeCapability()
}

func (device nvmlDevice) GetCudaComputeCapability() (int, int, Return) {
	var major, minor int32
	ret := nvmlDeviceGetCudaComputeCapability(device, &major, &minor)
	return int(major), int(minor), ret
}

// nvml.DeviceGetEccMode()
func (l *library) DeviceGetEccMode(device Device) (EnableState, EnableState, Return) {
	return device.GetEccMode()
}

func (device nvmlDevice) GetEccMode() (EnableState, EnableState, Return) {
	var current, pending EnableState
	ret := nvmlDeviceGetEccMode(device, &current, &pending)
	return current, pending, ret
}

// nvml.DeviceGetBoardId()
func (l *library) DeviceGetBoardId(device Device) (uint32, Return) {
	return device.GetBoardId()
}

func (device nvmlDevice) GetBoardId() (uint32, Return) {
	var boardId uint32
	ret := nvmlDeviceGetBoardId(device, &boardId)
	return boardId, ret
}

// nvml.DeviceGetMultiGpuBoard()
func (l *library) DeviceGetMultiGpuBoard(device Device) (int, Return) {
	return device.GetMultiGpuBoard()
}

func (device nvmlDevice) GetMultiGpuBoard() (int, Return) {
	var multiGpuBool uint32
	ret := nvmlDeviceGetMultiGpuBoard(device, &multiGpuBool)
	return int(multiGpuBool), ret
}

// nvml.DeviceGetTotalEccErrors()
func (l *library) DeviceGetTotalEccErrors(device Device, errorType MemoryErrorType, counterType EccCounterType) (uint64, Return) {
	return device.GetTotalEccErrors(errorType, counterType)
}

func (device nvmlDevice) GetTotalEccErrors(errorType MemoryErrorType, counterType EccCounterType) (uint64, Return) {
	var eccCounts uint64
	ret := nvmlDeviceGetTotalEccErrors(device, errorType, counterType, &eccCounts)
	return eccCounts, ret
}

// nvml.DeviceGetDetailedEccErrors()
func (l *library) DeviceGetDetailedEccErrors(device Device, errorType MemoryErrorType, counterType EccCounterType) (EccErrorCounts, Return) {
	return device.GetDetailedEccErrors(errorType, counterType)
}

func (device nvmlDevice) GetDetailedEccErrors(errorType MemoryErrorType, counterType EccCounterType) (EccErrorCounts, Return) {
	var eccCounts EccErrorCounts
	ret := nvmlDeviceGetDetailedEccErrors(device, errorType, counterType, &eccCounts)
	return eccCounts, ret
}

// nvml.DeviceGetMemoryErrorCounter()
func (l *library) DeviceGetMemoryErrorCounter(device Device, errorType MemoryErrorType, counterType EccCounterType, locationType MemoryLocation) (uint64, Return) {
	return device.GetMemoryErrorCounter(errorType, counterType, locationType)
}

func (device nvmlDevice) GetMemoryErrorCounter(errorType MemoryErrorType, counterType EccCounterType, locationType MemoryLocation) (uint64, Return) {
	var count uint64
	ret := nvmlDeviceGetMemoryErrorCounter(device, errorType, counterType, locationType, &count)
	return count, ret
}

// nvml.DeviceGetUtilizationRates()
func (l *library) DeviceGetUtilizationRates(device Device) (Utilization, Return) {
	return device.GetUtilizationRates()
}

func (device nvmlDevice) GetUtilizationRates() (Utilization, Return) {
	var utilization Utilization
	ret := nvmlDeviceGetUtilizationRates(device, &utilization)
	return utilization, ret
}

// nvml.DeviceGetEncoderUtilization()
func (l *library) DeviceGetEncoderUtilization(device Device) (uint32, uint32, Return) {
	return device.GetEncoderUtilization()
}

func (device nvmlDevice) GetEncoderUtilization() (uint32, uint32, Return) {
	var utilization, samplingPeriodUs uint32
	ret := nvmlDeviceGetEncoderUtilization(device, &utilization, &samplingPeriodUs)
	return utilization, samplingPeriodUs, ret
}

// nvml.DeviceGetEncoderCapacity()
func (l *library) DeviceGetEncoderCapacity(device Device, encoderQueryType EncoderType) (int, Return) {
	return device.GetEncoderCapacity(encoderQueryType)
}

func (device nvmlDevice) GetEncoderCapacity(encoderQueryType EncoderType) (int, Return) {
	var encoderCapacity uint32
	ret := nvmlDeviceGetEncoderCapacity(device, encoderQueryType, &encoderCapacity)
	return int(encoderCapacity), ret
}

// nvml.DeviceGetEncoderStats()
func (l *library) DeviceGetEncoderStats(device Device) (int, uint32, uint32, Return) {
	return device.GetEncoderStats()
}

func (device nvmlDevice) GetEncoderStats() (int, uint32, uint32, Return) {
	var sessionCount, averageFps, averageLatency uint32
	ret := nvmlDeviceGetEncoderStats(device, &sessionCount, &averageFps, &averageLatency)
	return int(sessionCount), averageFps, averageLatency, ret
}

// nvml.DeviceGetEncoderSessions()
func (l *library) DeviceGetEncoderSessions(device Device) ([]EncoderSessionInfo, Return) {
	return device.GetEncoderSessions()
}

func (device nvmlDevice) GetEncoderSessions() ([]EncoderSessionInfo, Return) {
	var sessionCount uint32 = 1 // Will be reduced upon returning
	for {
		sessionInfos := make([]EncoderSessionInfo, sessionCount)
		ret := nvmlDeviceGetEncoderSessions(device, &sessionCount, &sessionInfos[0])
		if ret == SUCCESS {
			return sessionInfos[:sessionCount], ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		sessionCount *= 2
	}
}

// nvml.DeviceGetDecoderUtilization()
func (l *library) DeviceGetDecoderUtilization(device Device) (uint32, uint32, Return) {
	return device.GetDecoderUtilization()
}

func (device nvmlDevice) GetDecoderUtilization() (uint32, uint32, Return) {
	var utilization, samplingPeriodUs uint32
	ret := nvmlDeviceGetDecoderUtilization(device, &utilization, &samplingPeriodUs)
	return utilization, samplingPeriodUs, ret
}

// nvml.DeviceGetFBCStats()
func (l *library) DeviceGetFBCStats(device Device) (FBCStats, Return) {
	return device.GetFBCStats()
}

func (device nvmlDevice) GetFBCStats() (FBCStats, Return) {
	var fbcStats FBCStats
	ret := nvmlDeviceGetFBCStats(device, &fbcStats)
	return fbcStats, ret
}

// nvml.DeviceGetFBCSessions()
func (l *library) DeviceGetFBCSessions(device Device) ([]FBCSessionInfo, Return) {
	return device.GetFBCSessions()
}

func (device nvmlDevice) GetFBCSessions() ([]FBCSessionInfo, Return) {
	var sessionCount uint32 = 1 // Will be reduced upon returning
	for {
		sessionInfo := make([]FBCSessionInfo, sessionCount)
		ret := nvmlDeviceGetFBCSessions(device, &sessionCount, &sessionInfo[0])
		if ret == SUCCESS {
			return sessionInfo[:sessionCount], ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		sessionCount *= 2
	}
}

// nvml.DeviceGetDriverModel()
func (l *library) DeviceGetDriverModel(device Device) (DriverModel, DriverModel, Return) {
	return device.GetDriverModel()
}

func (device nvmlDevice) GetDriverModel() (DriverModel, DriverModel, Return) {
	var current, pending DriverModel
	ret := nvmlDeviceGetDriverModel(device, &current, &pending)
	return current, pending, ret
}

// nvml.DeviceGetVbiosVersion()
func (l *library) DeviceGetVbiosVersion(device Device) (string, Return) {
	return device.GetVbiosVersion()
}

func (device nvmlDevice) GetVbiosVersion() (string, Return) {
	version := make([]byte, DEVICE_VBIOS_VERSION_BUFFER_SIZE)
	ret := nvmlDeviceGetVbiosVersion(device, &version[0], DEVICE_VBIOS_VERSION_BUFFER_SIZE)
	return string(version[:clen(version)]), ret
}

// nvml.DeviceGetBridgeChipInfo()
func (l *library) DeviceGetBridgeChipInfo(device Device) (BridgeChipHierarchy, Return) {
	return device.GetBridgeChipInfo()
}

func (device nvmlDevice) GetBridgeChipInfo() (BridgeChipHierarchy, Return) {
	var bridgeHierarchy BridgeChipHierarchy
	ret := nvmlDeviceGetBridgeChipInfo(device, &bridgeHierarchy)
	return bridgeHierarchy, ret
}

// nvml.DeviceGetComputeRunningProcesses()
func deviceGetComputeRunningProcesses_v1(device nvmlDevice) ([]ProcessInfo, Return) {
	var infoCount uint32 = 1 // Will be reduced upon returning
	for {
		infos := make([]ProcessInfo_v1, infoCount)
		ret := nvmlDeviceGetComputeRunningProcesses_v1(device, &infoCount, &infos[0])
		if ret == SUCCESS {
			return ProcessInfo_v1Slice(infos[:infoCount]).ToProcessInfoSlice(), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		infoCount *= 2
	}
}

func deviceGetComputeRunningProcesses_v2(device nvmlDevice) ([]ProcessInfo, Return) {
	var infoCount uint32 = 1 // Will be reduced upon returning
	for {
		infos := make([]ProcessInfo_v2, infoCount)
		ret := nvmlDeviceGetComputeRunningProcesses_v2(device, &infoCount, &infos[0])
		if ret == SUCCESS {
			return ProcessInfo_v2Slice(infos[:infoCount]).ToProcessInfoSlice(), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		infoCount *= 2
	}
}

func deviceGetComputeRunningProcesses_v3(device nvmlDevice) ([]ProcessInfo, Return) {
	var infoCount uint32 = 1 // Will be reduced upon returning
	for {
		infos := make([]ProcessInfo, infoCount)
		ret := nvmlDeviceGetComputeRunningProcesses_v3(device, &infoCount, &infos[0])
		if ret == SUCCESS {
			return infos[:infoCount], ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		infoCount *= 2
	}
}

func (l *library) DeviceGetComputeRunningProcesses(device Device) ([]ProcessInfo, Return) {
	return device.GetComputeRunningProcesses()
}

func (device nvmlDevice) GetComputeRunningProcesses() ([]ProcessInfo, Return) {
	return deviceGetComputeRunningProcesses(device)
}

// nvml.DeviceGetGraphicsRunningProcesses()
func deviceGetGraphicsRunningProcesses_v1(device nvmlDevice) ([]ProcessInfo, Return) {
	var infoCount uint32 = 1 // Will be reduced upon returning
	for {
		infos := make([]ProcessInfo_v1, infoCount)
		ret := nvmlDeviceGetGraphicsRunningProcesses_v1(device, &infoCount, &infos[0])
		if ret == SUCCESS {
			return ProcessInfo_v1Slice(infos[:infoCount]).ToProcessInfoSlice(), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		infoCount *= 2
	}
}

func deviceGetGraphicsRunningProcesses_v2(device nvmlDevice) ([]ProcessInfo, Return) {
	var infoCount uint32 = 1 // Will be reduced upon returning
	for {
		infos := make([]ProcessInfo_v2, infoCount)
		ret := nvmlDeviceGetGraphicsRunningProcesses_v2(device, &infoCount, &infos[0])
		if ret == SUCCESS {
			return ProcessInfo_v2Slice(infos[:infoCount]).ToProcessInfoSlice(), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		infoCount *= 2
	}
}

func deviceGetGraphicsRunningProcesses_v3(device nvmlDevice) ([]ProcessInfo, Return) {
	var infoCount uint32 = 1 // Will be reduced upon returning
	for {
		infos := make([]ProcessInfo, infoCount)
		ret := nvmlDeviceGetGraphicsRunningProcesses_v3(device, &infoCount, &infos[0])
		if ret == SUCCESS {
			return infos[:infoCount], ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		infoCount *= 2
	}
}

func (l *library) DeviceGetGraphicsRunningProcesses(device Device) ([]ProcessInfo, Return) {
	return device.GetGraphicsRunningProcesses()
}

func (device nvmlDevice) GetGraphicsRunningProcesses() ([]ProcessInfo, Return) {
	return deviceGetGraphicsRunningProcesses(device)
}

// nvml.DeviceGetMPSComputeRunningProcesses()
func deviceGetMPSComputeRunningProcesses_v1(device nvmlDevice) ([]ProcessInfo, Return) {
	var infoCount uint32 = 1 // Will be reduced upon returning
	for {
		infos := make([]ProcessInfo_v1, infoCount)
		ret := nvmlDeviceGetMPSComputeRunningProcesses_v1(device, &infoCount, &infos[0])
		if ret == SUCCESS {
			return ProcessInfo_v1Slice(infos[:infoCount]).ToProcessInfoSlice(), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		infoCount *= 2
	}
}

func deviceGetMPSComputeRunningProcesses_v2(device nvmlDevice) ([]ProcessInfo, Return) {
	var infoCount uint32 = 1 // Will be reduced upon returning
	for {
		infos := make([]ProcessInfo_v2, infoCount)
		ret := nvmlDeviceGetMPSComputeRunningProcesses_v2(device, &infoCount, &infos[0])
		if ret == SUCCESS {
			return ProcessInfo_v2Slice(infos[:infoCount]).ToProcessInfoSlice(), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		infoCount *= 2
	}
}

func deviceGetMPSComputeRunningProcesses_v3(device nvmlDevice) ([]ProcessInfo, Return) {
	var infoCount uint32 = 1 // Will be reduced upon returning
	for {
		infos := make([]ProcessInfo, infoCount)
		ret := nvmlDeviceGetMPSComputeRunningProcesses_v3(device, &infoCount, &infos[0])
		if ret == SUCCESS {
			return infos[:infoCount], ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		infoCount *= 2
	}
}

func (l *library) DeviceGetMPSComputeRunningProcesses(device Device) ([]ProcessInfo, Return) {
	return device.GetMPSComputeRunningProcesses()
}

func (device nvmlDevice) GetMPSComputeRunningProcesses() ([]ProcessInfo, Return) {
	return deviceGetMPSComputeRunningProcesses(device)
}

// nvml.DeviceOnSameBoard()
func (l *library) DeviceOnSameBoard(device1 Device, device2 Device) (int, Return) {
	return device1.OnSameBoard(device2)
}

func (device1 nvmlDevice) OnSameBoard(device2 Device) (int, Return) {
	var onSameBoard int32
	ret := nvmlDeviceOnSameBoard(device1, nvmlDeviceHandle(device2), &onSameBoard)
	return int(onSameBoard), ret
}

// nvml.DeviceGetAPIRestriction()
func (l *library) DeviceGetAPIRestriction(device Device, apiType RestrictedAPI) (EnableState, Return) {
	return device.GetAPIRestriction(apiType)
}

func (device nvmlDevice) GetAPIRestriction(apiType RestrictedAPI) (EnableState, Return) {
	var isRestricted EnableState
	ret := nvmlDeviceGetAPIRestriction(device, apiType, &isRestricted)
	return isRestricted, ret
}

// nvml.DeviceGetSamples()
func (l *library) DeviceGetSamples(device Device, samplingType SamplingType, lastSeenTimestamp uint64) (ValueType, []Sample, Return) {
	return device.GetSamples(samplingType, lastSeenTimestamp)
}

func (device nvmlDevice) GetSamples(samplingType SamplingType, lastSeenTimestamp uint64) (ValueType, []Sample, Return) {
	var sampleValType ValueType
	var sampleCount uint32
	ret := nvmlDeviceGetSamples(device, samplingType, lastSeenTimestamp, &sampleValType, &sampleCount, nil)
	if ret != SUCCESS {
		return sampleValType, nil, ret
	}
	if sampleCount == 0 {
		return sampleValType, []Sample{}, ret
	}
	samples := make([]Sample, sampleCount)
	ret = nvmlDeviceGetSamples(device, samplingType, lastSeenTimestamp, &sampleValType, &sampleCount, &samples[0])
	return sampleValType, samples, ret
}

// nvml.DeviceGetBAR1MemoryInfo()
func (l *library) DeviceGetBAR1MemoryInfo(device Device) (BAR1Memory, Return) {
	return device.GetBAR1MemoryInfo()
}

func (device nvmlDevice) GetBAR1MemoryInfo() (BAR1Memory, Return) {
	var bar1Memory BAR1Memory
	ret := nvmlDeviceGetBAR1MemoryInfo(device, &bar1Memory)
	return bar1Memory, ret
}

// nvml.DeviceGetViolationStatus()
func (l *library) DeviceGetViolationStatus(device Device, perfPolicyType PerfPolicyType) (ViolationTime, Return) {
	return device.GetViolationStatus(perfPolicyType)
}

func (device nvmlDevice) GetViolationStatus(perfPolicyType PerfPolicyType) (ViolationTime, Return) {
	var violTime ViolationTime
	ret := nvmlDeviceGetViolationStatus(device, perfPolicyType, &violTime)
	return violTime, ret
}

// nvml.DeviceGetIrqNum()
func (l *library) DeviceGetIrqNum(device Device) (int, Return) {
	return device.GetIrqNum()
}

func (device nvmlDevice) GetIrqNum() (int, Return) {
	var irqNum uint32
	ret := nvmlDeviceGetIrqNum(device, &irqNum)
	return int(irqNum), ret
}

// nvml.DeviceGetNumGpuCores()
func (l *library) DeviceGetNumGpuCores(device Device) (int, Return) {
	return device.GetNumGpuCores()
}

func (device nvmlDevice) GetNumGpuCores() (int, Return) {
	var numCores uint32
	ret := nvmlDeviceGetNumGpuCores(device, &numCores)
	return int(numCores), ret
}

// nvml.DeviceGetPowerSource()
func (l *library) DeviceGetPowerSource(device Device) (PowerSource, Return) {
	return device.GetPowerSource()
}

func (device nvmlDevice) GetPowerSource() (PowerSource, Return) {
	var powerSource PowerSource
	ret := nvmlDeviceGetPowerSource(device, &powerSource)
	return powerSource, ret
}

// nvml.DeviceGetMemoryBusWidth()
func (l *library) DeviceGetMemoryBusWidth(device Device) (uint32, Return) {
	return device.GetMemoryBusWidth()
}

func (device nvmlDevice) GetMemoryBusWidth() (uint32, Return) {
	var busWidth uint32
	ret := nvmlDeviceGetMemoryBusWidth(device, &busWidth)
	return busWidth, ret
}

// nvml.DeviceGetPcieLinkMaxSpeed()
func (l *library) DeviceGetPcieLinkMaxSpeed(device Device) (uint32, Return) {
	return device.GetPcieLinkMaxSpeed()
}

func (device nvmlDevice) GetPcieLinkMaxSpeed() (uint32, Return) {
	var maxSpeed uint32
	ret := nvmlDeviceGetPcieLinkMaxSpeed(device, &maxSpeed)
	return maxSpeed, ret
}

// nvml.DeviceGetAdaptiveClockInfoStatus()
func (l *library) DeviceGetAdaptiveClockInfoStatus(device Device) (uint32, Return) {
	return device.GetAdaptiveClockInfoStatus()
}

func (device nvmlDevice) GetAdaptiveClockInfoStatus() (uint32, Return) {
	var adaptiveClockStatus uint32
	ret := nvmlDeviceGetAdaptiveClockInfoStatus(device, &adaptiveClockStatus)
	return adaptiveClockStatus, ret
}

// nvml.DeviceGetAccountingMode()
func (l *library) DeviceGetAccountingMode(device Device) (EnableState, Return) {
	return device.GetAccountingMode()
}

func (device nvmlDevice) GetAccountingMode() (EnableState, Return) {
	var mode EnableState
	ret := nvmlDeviceGetAccountingMode(device, &mode)
	return mode, ret
}

// nvml.DeviceGetAccountingStats()
func (l *library) DeviceGetAccountingStats(device Device, pid uint32) (AccountingStats, Return) {
	return device.GetAccountingStats(pid)
}

func (device nvmlDevice) GetAccountingStats(pid uint32) (AccountingStats, Return) {
	var stats AccountingStats
	ret := nvmlDeviceGetAccountingStats(device, pid, &stats)
	return stats, ret
}

// nvml.DeviceGetAccountingPids()
func (l *library) DeviceGetAccountingPids(device Device) ([]int, Return) {
	return device.GetAccountingPids()
}

func (device nvmlDevice) GetAccountingPids() ([]int, Return) {
	var count uint32 = 1 // Will be reduced upon returning
	for {
		pids := make([]uint32, count)
		ret := nvmlDeviceGetAccountingPids(device, &count, &pids[0])
		if ret == SUCCESS {
			return uint32SliceToIntSlice(pids[:count]), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		count *= 2
	}
}

// nvml.DeviceGetAccountingBufferSize()
func (l *library) DeviceGetAccountingBufferSize(device Device) (int, Return) {
	return device.GetAccountingBufferSize()
}

func (device nvmlDevice) GetAccountingBufferSize() (int, Return) {
	var bufferSize uint32
	ret := nvmlDeviceGetAccountingBufferSize(device, &bufferSize)
	return int(bufferSize), ret
}

// nvml.DeviceGetRetiredPages()
func (l *library) DeviceGetRetiredPages(device Device, cause PageRetirementCause) ([]uint64, Return) {
	return device.GetRetiredPages(cause)
}

func (device nvmlDevice) GetRetiredPages(cause PageRetirementCause) ([]uint64, Return) {
	var pageCount uint32 = 1 // Will be reduced upon returning
	for {
		addresses := make([]uint64, pageCount)
		ret := nvmlDeviceGetRetiredPages(device, cause, &pageCount, &addresses[0])
		if ret == SUCCESS {
			return addresses[:pageCount], ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		pageCount *= 2
	}
}

// nvml.DeviceGetRetiredPages_v2()
func (l *library) DeviceGetRetiredPages_v2(device Device, cause PageRetirementCause) ([]uint64, []uint64, Return) {
	return device.GetRetiredPages_v2(cause)
}

func (device nvmlDevice) GetRetiredPages_v2(cause PageRetirementCause) ([]uint64, []uint64, Return) {
	var pageCount uint32 = 1 // Will be reduced upon returning
	for {
		addresses := make([]uint64, pageCount)
		timestamps := make([]uint64, pageCount)
		ret := nvmlDeviceGetRetiredPages_v2(device, cause, &pageCount, &addresses[0], &timestamps[0])
		if ret == SUCCESS {
			return addresses[:pageCount], timestamps[:pageCount], ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, nil, ret
		}
		pageCount *= 2
	}
}

// nvml.DeviceGetRetiredPagesPendingStatus()
func (l *library) DeviceGetRetiredPagesPendingStatus(device Device) (EnableState, Return) {
	return device.GetRetiredPagesPendingStatus()
}

func (device nvmlDevice) GetRetiredPagesPendingStatus() (EnableState, Return) {
	var isPending EnableState
	ret := nvmlDeviceGetRetiredPagesPendingStatus(device, &isPending)
	return isPending, ret
}

// nvml.DeviceSetPersistenceMode()
func (l *library) DeviceSetPersistenceMode(device Device, mode EnableState) Return {
	return device.SetPersistenceMode(mode)
}

func (device nvmlDevice) SetPersistenceMode(mode EnableState) Return {
	return nvmlDeviceSetPersistenceMode(device, mode)
}

// nvml.DeviceSetComputeMode()
func (l *library) DeviceSetComputeMode(device Device, mode ComputeMode) Return {
	return device.SetComputeMode(mode)
}

func (device nvmlDevice) SetComputeMode(mode ComputeMode) Return {
	return nvmlDeviceSetComputeMode(device, mode)
}

// nvml.DeviceSetEccMode()
func (l *library) DeviceSetEccMode(device Device, ecc EnableState) Return {
	return device.SetEccMode(ecc)
}

func (device nvmlDevice) SetEccMode(ecc EnableState) Return {
	return nvmlDeviceSetEccMode(device, ecc)
}

// nvml.DeviceClearEccErrorCounts()
func (l *library) DeviceClearEccErrorCounts(device Device, counterType EccCounterType) Return {
	return device.ClearEccErrorCounts(counterType)
}

func (device nvmlDevice) ClearEccErrorCounts(counterType EccCounterType) Return {
	return nvmlDeviceClearEccErrorCounts(device, counterType)
}

// nvml.DeviceSetDriverModel()
func (l *library) DeviceSetDriverModel(device Device, driverModel DriverModel, flags uint32) Return {
	return device.SetDriverModel(driverModel, flags)
}

func (device nvmlDevice) SetDriverModel(driverModel DriverModel, flags uint32) Return {
	return nvmlDeviceSetDriverModel(device, driverModel, flags)
}

// nvml.DeviceSetGpuLockedClocks()
func (l *library) DeviceSetGpuLockedClocks(device Device, minGpuClockMHz uint32, maxGpuClockMHz uint32) Return {
	return device.SetGpuLockedClocks(minGpuClockMHz, maxGpuClockMHz)
}

func (device nvmlDevice) SetGpuLockedClocks(minGpuClockMHz uint32, maxGpuClockMHz uint32) Return {
	return nvmlDeviceSetGpuLockedClocks(device, minGpuClockMHz, maxGpuClockMHz)
}

// nvml.DeviceResetGpuLockedClocks()
func (l *library) DeviceResetGpuLockedClocks(device Device) Return {
	return device.ResetGpuLockedClocks()
}

func (device nvmlDevice) ResetGpuLockedClocks() Return {
	return nvmlDeviceResetGpuLockedClocks(device)
}

// nvmlDeviceSetMemoryLockedClocks()
func (l *library) DeviceSetMemoryLockedClocks(device Device, minMemClockMHz uint32, maxMemClockMHz uint32) Return {
	return device.SetMemoryLockedClocks(minMemClockMHz, maxMemClockMHz)
}

func (device nvmlDevice) SetMemoryLockedClocks(minMemClockMHz uint32, maxMemClockMHz uint32) Return {
	return nvmlDeviceSetMemoryLockedClocks(device, minMemClockMHz, maxMemClockMHz)
}

// nvmlDeviceResetMemoryLockedClocks()
func (l *library) DeviceResetMemoryLockedClocks(device Device) Return {
	return device.ResetMemoryLockedClocks()
}

func (device nvmlDevice) ResetMemoryLockedClocks() Return {
	return nvmlDeviceResetMemoryLockedClocks(device)
}

// nvml.DeviceGetClkMonStatus()
func (l *library) DeviceGetClkMonStatus(device Device) (ClkMonStatus, Return) {
	return device.GetClkMonStatus()
}

func (device nvmlDevice) GetClkMonStatus() (ClkMonStatus, Return) {
	var status ClkMonStatus
	ret := nvmlDeviceGetClkMonStatus(device, &status)
	return status, ret
}

// nvml.DeviceSetApplicationsClocks()
func (l *library) DeviceSetApplicationsClocks(device Device, memClockMHz uint32, graphicsClockMHz uint32) Return {
	return device.SetApplicationsClocks(memClockMHz, graphicsClockMHz)
}

func (device nvmlDevice) SetApplicationsClocks(memClockMHz uint32, graphicsClockMHz uint32) Return {
	return nvmlDeviceSetApplicationsClocks(device, memClockMHz, graphicsClockMHz)
}

// nvml.DeviceSetPowerManagementLimit()
func (l *library) DeviceSetPowerManagementLimit(device Device, limit uint32) Return {
	return device.SetPowerManagementLimit(limit)
}

func (device nvmlDevice) SetPowerManagementLimit(limit uint32) Return {
	return nvmlDeviceSetPowerManagementLimit(device, limit)
}

// nvml.DeviceSetGpuOperationMode()
func (l *library) DeviceSetGpuOperationMode(device Device, mode GpuOperationMode) Return {
	return device.SetGpuOperationMode(mode)
}

func (device nvmlDevice) SetGpuOperationMode(mode GpuOperationMode) Return {
	return nvmlDeviceSetGpuOperationMode(device, mode)
}

// nvml.DeviceSetAPIRestriction()
func (l *library) DeviceSetAPIRestriction(device Device, apiType RestrictedAPI, isRestricted EnableState) Return {
	return device.SetAPIRestriction(apiType, isRestricted)
}

func (device nvmlDevice) SetAPIRestriction(apiType RestrictedAPI, isRestricted EnableState) Return {
	return nvmlDeviceSetAPIRestriction(device, apiType, isRestricted)
}

// nvml.DeviceSetAccountingMode()
func (l *library) DeviceSetAccountingMode(device Device, mode EnableState) Return {
	return device.SetAccountingMode(mode)
}

func (device nvmlDevice) SetAccountingMode(mode EnableState) Return {
	return nvmlDeviceSetAccountingMode(device, mode)
}

// nvml.DeviceClearAccountingPids()
func (l *library) DeviceClearAccountingPids(device Device) Return {
	return device.ClearAccountingPids()
}

func (device nvmlDevice) ClearAccountingPids() Return {
	return nvmlDeviceClearAccountingPids(device)
}

// nvml.DeviceGetNvLinkState()
func (l *library) DeviceGetNvLinkState(device Device, link int) (EnableState, Return) {
	return device.GetNvLinkState(link)
}

func (device nvmlDevice) GetNvLinkState(link int) (EnableState, Return) {
	var isActive EnableState
	ret := nvmlDeviceGetNvLinkState(device, uint32(link), &isActive)
	return isActive, ret
}

// nvml.DeviceGetNvLinkVersion()
func (l *library) DeviceGetNvLinkVersion(device Device, link int) (uint32, Return) {
	return device.GetNvLinkVersion(link)
}

func (device nvmlDevice) GetNvLinkVersion(link int) (uint32, Return) {
	var version uint32
	ret := nvmlDeviceGetNvLinkVersion(device, uint32(link), &version)
	return version, ret
}

// nvml.DeviceGetNvLinkCapability()
func (l *library) DeviceGetNvLinkCapability(device Device, link int, capability NvLinkCapability) (uint32, Return) {
	return device.GetNvLinkCapability(link, capability)
}

func (device nvmlDevice) GetNvLinkCapability(link int, capability NvLinkCapability) (uint32, Return) {
	var capResult uint32
	ret := nvmlDeviceGetNvLinkCapability(device, uint32(link), capability, &capResult)
	return capResult, ret
}

// nvml.DeviceGetNvLinkRemotePciInfo()
func (l *library) DeviceGetNvLinkRemotePciInfo(device Device, link int) (PciInfo, Return) {
	return device.GetNvLinkRemotePciInfo(link)
}

func (device nvmlDevice) GetNvLinkRemotePciInfo(link int) (PciInfo, Return) {
	var pci PciInfo
	ret := nvmlDeviceGetNvLinkRemotePciInfo(device, uint32(link), &pci)
	return pci, ret
}

// nvml.DeviceGetNvLinkErrorCounter()
func (l *library) DeviceGetNvLinkErrorCounter(device Device, link int, counter NvLinkErrorCounter) (uint64, Return) {
	return device.GetNvLinkErrorCounter(link, counter)
}

func (device nvmlDevice) GetNvLinkErrorCounter(link int, counter NvLinkErrorCounter) (uint64, Return) {
	var counterValue uint64
	ret := nvmlDeviceGetNvLinkErrorCounter(device, uint32(link), counter, &counterValue)
	return counterValue, ret
}

// nvml.DeviceResetNvLinkErrorCounters()
func (l *library) DeviceResetNvLinkErrorCounters(device Device, link int) Return {
	return device.ResetNvLinkErrorCounters(link)
}

func (device nvmlDevice) ResetNvLinkErrorCounters(link int) Return {
	return nvmlDeviceResetNvLinkErrorCounters(device, uint32(link))
}

// nvml.DeviceSetNvLinkUtilizationControl()
func (l *library) DeviceSetNvLinkUtilizationControl(device Device, link int, counter int, control *NvLinkUtilizationControl, reset bool) Return {
	return device.SetNvLinkUtilizationControl(link, counter, control, reset)
}

func (device nvmlDevice) SetNvLinkUtilizationControl(link int, counter int, control *NvLinkUtilizationControl, reset bool) Return {
	resetValue := uint32(0)
	if reset {
		resetValue = 1
	}
	return nvmlDeviceSetNvLinkUtilizationControl(device, uint32(link), uint32(counter), control, resetValue)
}

// nvml.DeviceGetNvLinkUtilizationControl()
func (l *library) DeviceGetNvLinkUtilizationControl(device Device, link int, counter int) (NvLinkUtilizationControl, Return) {
	return device.GetNvLinkUtilizationControl(link, counter)
}

func (device nvmlDevice) GetNvLinkUtilizationControl(link int, counter int) (NvLinkUtilizationControl, Return) {
	var control NvLinkUtilizationControl
	ret := nvmlDeviceGetNvLinkUtilizationControl(device, uint32(link), uint32(counter), &control)
	return control, ret
}

// nvml.DeviceGetNvLinkUtilizationCounter()
func (l *library) DeviceGetNvLinkUtilizationCounter(device Device, link int, counter int) (uint64, uint64, Return) {
	return device.GetNvLinkUtilizationCounter(link, counter)
}

func (device nvmlDevice) GetNvLinkUtilizationCounter(link int, counter int) (uint64, uint64, Return) {
	var rxCounter, txCounter uint64
	ret := nvmlDeviceGetNvLinkUtilizationCounter(device, uint32(link), uint32(counter), &rxCounter, &txCounter)
	return rxCounter, txCounter, ret
}

// nvml.DeviceFreezeNvLinkUtilizationCounter()
func (l *library) DeviceFreezeNvLinkUtilizationCounter(device Device, link int, counter int, freeze EnableState) Return {
	return device.FreezeNvLinkUtilizationCounter(link, counter, freeze)
}

func (device nvmlDevice) FreezeNvLinkUtilizationCounter(link int, counter int, freeze EnableState) Return {
	return nvmlDeviceFreezeNvLinkUtilizationCounter(device, uint32(link), uint32(counter), freeze)
}

// nvml.DeviceResetNvLinkUtilizationCounter()
func (l *library) DeviceResetNvLinkUtilizationCounter(device Device, link int, counter int) Return {
	return device.ResetNvLinkUtilizationCounter(link, counter)
}

func (device nvmlDevice) ResetNvLinkUtilizationCounter(link int, counter int) Return {
	return nvmlDeviceResetNvLinkUtilizationCounter(device, uint32(link), uint32(counter))
}

// nvml.DeviceGetNvLinkRemoteDeviceType()
func (l *library) DeviceGetNvLinkRemoteDeviceType(device Device, link int) (IntNvLinkDeviceType, Return) {
	return device.GetNvLinkRemoteDeviceType(link)
}

func (device nvmlDevice) GetNvLinkRemoteDeviceType(link int) (IntNvLinkDeviceType, Return) {
	var nvLinkDeviceType IntNvLinkDeviceType
	ret := nvmlDeviceGetNvLinkRemoteDeviceType(device, uint32(link), &nvLinkDeviceType)
	return nvLinkDeviceType, ret
}

// nvml.DeviceRegisterEvents()
func (l *library) DeviceRegisterEvents(device Device, eventTypes uint64, set EventSet) Return {
	return device.RegisterEvents(eventTypes, set)
}

func (device nvmlDevice) RegisterEvents(eventTypes uint64, set EventSet) Return {
	return nvmlDeviceRegisterEvents(device, eventTypes, set.(nvmlEventSet))
}

// nvmlDeviceGetSupportedEventTypes()
func (l *library) DeviceGetSupportedEventTypes(device Device) (uint64, Return) {
	return device.GetSupportedEventTypes()
}

func (device nvmlDevice) GetSupportedEventTypes() (uint64, Return) {
	var eventTypes uint64
	ret := nvmlDeviceGetSupportedEventTypes(device, &eventTypes)
	return eventTypes, ret
}

// nvml.DeviceModifyDrainState()
func (l *library) DeviceModifyDrainState(pciInfo *PciInfo, newState EnableState) Return {
	return nvmlDeviceModifyDrainState(pciInfo, newState)
}

// nvml.DeviceQueryDrainState()
func (l *library) DeviceQueryDrainState(pciInfo *PciInfo) (EnableState, Return) {
	var currentState EnableState
	ret := nvmlDeviceQueryDrainState(pciInfo, &currentState)
	return currentState, ret
}

// nvml.DeviceRemoveGpu()
func (l *library) DeviceRemoveGpu(pciInfo *PciInfo) Return {
	return nvmlDeviceRemoveGpu(pciInfo)
}

// nvml.DeviceRemoveGpu_v2()
func (l *library) DeviceRemoveGpu_v2(pciInfo *PciInfo, gpuState DetachGpuState, linkState PcieLinkState) Return {
	return nvmlDeviceRemoveGpu_v2(pciInfo, gpuState, linkState)
}

// nvml.DeviceDiscoverGpus()
func (l *library) DeviceDiscoverGpus() (PciInfo, Return) {
	var pciInfo PciInfo
	ret := nvmlDeviceDiscoverGpus(&pciInfo)
	return pciInfo, ret
}

// nvml.DeviceGetFieldValues()
func (l *library) DeviceGetFieldValues(device Device, values []FieldValue) Return {
	return device.GetFieldValues(values)
}

func (device nvmlDevice) GetFieldValues(values []FieldValue) Return {
	valuesCount := len(values)
	return nvmlDeviceGetFieldValues(device, int32(valuesCount), &values[0])
}

// nvml.DeviceGetVirtualizationMode()
func (l *library) DeviceGetVirtualizationMode(device Device) (GpuVirtualizationMode, Return) {
	return device.GetVirtualizationMode()
}

func (device nvmlDevice) GetVirtualizationMode() (GpuVirtualizationMode, Return) {
	var pVirtualMode GpuVirtualizationMode
	ret := nvmlDeviceGetVirtualizationMode(device, &pVirtualMode)
	return pVirtualMode, ret
}

// nvml.DeviceGetHostVgpuMode()
func (l *library) DeviceGetHostVgpuMode(device Device) (HostVgpuMode, Return) {
	return device.GetHostVgpuMode()
}

func (device nvmlDevice) GetHostVgpuMode() (HostVgpuMode, Return) {
	var pHostVgpuMode HostVgpuMode
	ret := nvmlDeviceGetHostVgpuMode(device, &pHostVgpuMode)
	return pHostVgpuMode, ret
}

// nvml.DeviceSetVirtualizationMode()
func (l *library) DeviceSetVirtualizationMode(device Device, virtualMode GpuVirtualizationMode) Return {
	return device.SetVirtualizationMode(virtualMode)
}

func (device nvmlDevice) SetVirtualizationMode(virtualMode GpuVirtualizationMode) Return {
	return nvmlDeviceSetVirtualizationMode(device, virtualMode)
}

// nvml.DeviceGetGridLicensableFeatures()
func (l *library) DeviceGetGridLicensableFeatures(device Device) (GridLicensableFeatures, Return) {
	return device.GetGridLicensableFeatures()
}

func (device nvmlDevice) GetGridLicensableFeatures() (GridLicensableFeatures, Return) {
	var pGridLicensableFeatures GridLicensableFeatures
	ret := nvmlDeviceGetGridLicensableFeatures(device, &pGridLicensableFeatures)
	return pGridLicensableFeatures, ret
}

// nvml.DeviceGetProcessUtilization()
func (l *library) DeviceGetProcessUtilization(device Device, lastSeenTimestamp uint64) ([]ProcessUtilizationSample, Return) {
	return device.GetProcessUtilization(lastSeenTimestamp)
}

func (device nvmlDevice) GetProcessUtilization(lastSeenTimestamp uint64) ([]ProcessUtilizationSample, Return) {
	var processSamplesCount uint32
	ret := nvmlDeviceGetProcessUtilization(device, nil, &processSamplesCount, lastSeenTimestamp)
	if ret != ERROR_INSUFFICIENT_SIZE {
		return nil, ret
	}
	if processSamplesCount == 0 {
		return []ProcessUtilizationSample{}, ret
	}
	utilization := make([]ProcessUtilizationSample, processSamplesCount)
	ret = nvmlDeviceGetProcessUtilization(device, &utilization[0], &processSamplesCount, lastSeenTimestamp)
	return utilization[:processSamplesCount], ret
}

// nvml.DeviceGetSupportedVgpus()
func (l *library) DeviceGetSupportedVgpus(device Device) ([]VgpuTypeId, Return) {
	return device.GetSupportedVgpus()
}

func (device nvmlDevice) GetSupportedVgpus() ([]VgpuTypeId, Return) {
	var vgpuCount uint32 = 1 // Will be reduced upon returning
	for {
		vgpuTypeIds := make([]nvmlVgpuTypeId, vgpuCount)
		ret := nvmlDeviceGetSupportedVgpus(device, &vgpuCount, &vgpuTypeIds[0])
		if ret == SUCCESS {
			return convertSlice[nvmlVgpuTypeId, VgpuTypeId](vgpuTypeIds[:vgpuCount]), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		vgpuCount *= 2
	}
}

// nvml.DeviceGetCreatableVgpus()
func (l *library) DeviceGetCreatableVgpus(device Device) ([]VgpuTypeId, Return) {
	return device.GetCreatableVgpus()
}

func (device nvmlDevice) GetCreatableVgpus() ([]VgpuTypeId, Return) {
	var vgpuCount uint32 = 1 // Will be reduced upon returning
	for {
		vgpuTypeIds := make([]nvmlVgpuTypeId, vgpuCount)
		ret := nvmlDeviceGetCreatableVgpus(device, &vgpuCount, &vgpuTypeIds[0])
		if ret == SUCCESS {
			return convertSlice[nvmlVgpuTypeId, VgpuTypeId](vgpuTypeIds[:vgpuCount]), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		vgpuCount *= 2
	}
}

// nvml.DeviceGetActiveVgpus()
func (l *library) DeviceGetActiveVgpus(device Device) ([]VgpuInstance, Return) {
	return device.GetActiveVgpus()
}

func (device nvmlDevice) GetActiveVgpus() ([]VgpuInstance, Return) {
	var vgpuCount uint32 = 1 // Will be reduced upon returning
	for {
		vgpuInstances := make([]nvmlVgpuInstance, vgpuCount)
		ret := nvmlDeviceGetActiveVgpus(device, &vgpuCount, &vgpuInstances[0])
		if ret == SUCCESS {
			return convertSlice[nvmlVgpuInstance, VgpuInstance](vgpuInstances[:vgpuCount]), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		vgpuCount *= 2
	}
}

// nvml.DeviceGetVgpuMetadata()
func (l *library) DeviceGetVgpuMetadata(device Device) (VgpuPgpuMetadata, Return) {
	return device.GetVgpuMetadata()
}

func (device nvmlDevice) GetVgpuMetadata() (VgpuPgpuMetadata, Return) {
	var vgpuPgpuMetadata VgpuPgpuMetadata
	opaqueDataSize := unsafe.Sizeof(vgpuPgpuMetadata.nvmlVgpuPgpuMetadata.OpaqueData)
	vgpuPgpuMetadataSize := unsafe.Sizeof(vgpuPgpuMetadata.nvmlVgpuPgpuMetadata) - opaqueDataSize
	for {
		bufferSize := uint32(vgpuPgpuMetadataSize + opaqueDataSize)
		buffer := make([]byte, bufferSize)
		nvmlVgpuPgpuMetadataPtr := (*nvmlVgpuPgpuMetadata)(unsafe.Pointer(&buffer[0]))
		ret := nvmlDeviceGetVgpuMetadata(device, nvmlVgpuPgpuMetadataPtr, &bufferSize)
		if ret == SUCCESS {
			vgpuPgpuMetadata.nvmlVgpuPgpuMetadata = *nvmlVgpuPgpuMetadataPtr
			vgpuPgpuMetadata.OpaqueData = buffer[vgpuPgpuMetadataSize:bufferSize]
			return vgpuPgpuMetadata, ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return vgpuPgpuMetadata, ret
		}
		opaqueDataSize = 2 * opaqueDataSize
	}
}

// nvml.DeviceGetPgpuMetadataString()
func (l *library) DeviceGetPgpuMetadataString(device Device) (string, Return) {
	return device.GetPgpuMetadataString()
}

func (device nvmlDevice) GetPgpuMetadataString() (string, Return) {
	var bufferSize uint32 = 1 // Will be reduced upon returning
	for {
		pgpuMetadata := make([]byte, bufferSize)
		ret := nvmlDeviceGetPgpuMetadataString(device, &pgpuMetadata[0], &bufferSize)
		if ret == SUCCESS {
			return string(pgpuMetadata[:clen(pgpuMetadata)]), ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return "", ret
		}
		bufferSize *= 2
	}
}

// nvml.DeviceGetVgpuUtilization()
func (l *library) DeviceGetVgpuUtilization(device Device, lastSeenTimestamp uint64) (ValueType, []VgpuInstanceUtilizationSample, Return) {
	return device.GetVgpuUtilization(lastSeenTimestamp)
}

func (device nvmlDevice) GetVgpuUtilization(lastSeenTimestamp uint64) (ValueType, []VgpuInstanceUtilizationSample, Return) {
	var sampleValType ValueType
	var vgpuInstanceSamplesCount uint32 = 1 // Will be reduced upon returning
	for {
		utilizationSamples := make([]VgpuInstanceUtilizationSample, vgpuInstanceSamplesCount)
		ret := nvmlDeviceGetVgpuUtilization(device, lastSeenTimestamp, &sampleValType, &vgpuInstanceSamplesCount, &utilizationSamples[0])
		if ret == SUCCESS {
			return sampleValType, utilizationSamples[:vgpuInstanceSamplesCount], ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return sampleValType, nil, ret
		}
		vgpuInstanceSamplesCount *= 2
	}
}

// nvml.DeviceGetAttributes()
func (l *library) DeviceGetAttributes(device Device) (DeviceAttributes, Return) {
	return device.GetAttributes()
}

func (device nvmlDevice) GetAttributes() (DeviceAttributes, Return) {
	var attributes DeviceAttributes
	ret := nvmlDeviceGetAttributes(device, &attributes)
	return attributes, ret
}

// nvml.DeviceGetRemappedRows()
func (l *library) DeviceGetRemappedRows(device Device) (int, int, bool, bool, Return) {
	return device.GetRemappedRows()
}

func (device nvmlDevice) GetRemappedRows() (int, int, bool, bool, Return) {
	var corrRows, uncRows, isPending, failureOccured uint32
	ret := nvmlDeviceGetRemappedRows(device, &corrRows, &uncRows, &isPending, &failureOccured)
	return int(corrRows), int(uncRows), (isPending != 0), (failureOccured != 0), ret
}

// nvml.DeviceGetRowRemapperHistogram()
func (l *library) DeviceGetRowRemapperHistogram(device Device) (RowRemapperHistogramValues, Return) {
	return device.GetRowRemapperHistogram()
}

func (device nvmlDevice) GetRowRemapperHistogram() (RowRemapperHistogramValues, Return) {
	var values RowRemapperHistogramValues
	ret := nvmlDeviceGetRowRemapperHistogram(device, &values)
	return values, ret
}

// nvml.DeviceGetArchitecture()
func (l *library) DeviceGetArchitecture(device Device) (DeviceArchitecture, Return) {
	return device.GetArchitecture()
}

func (device nvmlDevice) GetArchitecture() (DeviceArchitecture, Return) {
	var arch DeviceArchitecture
	ret := nvmlDeviceGetArchitecture(device, &arch)
	return arch, ret
}

// nvml.DeviceGetVgpuProcessUtilization()
func (l *library) DeviceGetVgpuProcessUtilization(device Device, lastSeenTimestamp uint64) ([]VgpuProcessUtilizationSample, Return) {
	return device.GetVgpuProcessUtilization(lastSeenTimestamp)
}

func (device nvmlDevice) GetVgpuProcessUtilization(lastSeenTimestamp uint64) ([]VgpuProcessUtilizationSample, Return) {
	var vgpuProcessSamplesCount uint32 = 1 // Will be reduced upon returning
	for {
		utilizationSamples := make([]VgpuProcessUtilizationSample, vgpuProcessSamplesCount)
		ret := nvmlDeviceGetVgpuProcessUtilization(device, lastSeenTimestamp, &vgpuProcessSamplesCount, &utilizationSamples[0])
		if ret == SUCCESS {
			return utilizationSamples[:vgpuProcessSamplesCount], ret
		}
		if ret != ERROR_INSUFFICIENT_SIZE {
			return nil, ret
		}
		vgpuProcessSamplesCount *= 2
	}
}

// nvml.GetExcludedDeviceCount()
func (l *library) GetExcludedDeviceCount() (int, Return) {
	var deviceCount uint32
	ret := nvmlGetExcludedDeviceCount(&deviceCount)
	return int(deviceCount), ret
}

// nvml.GetExcludedDeviceInfoByIndex()
func (l *library) GetExcludedDeviceInfoByIndex(index int) (ExcludedDeviceInfo, Return) {
	var info ExcludedDeviceInfo
	ret := nvmlGetExcludedDeviceInfoByIndex(uint32(index), &info)
	return info, ret
}

// nvml.DeviceSetMigMode()
func (l *library) DeviceSetMigMode(device Device, mode int) (Return, Return) {
	return device.SetMigMode(mode)
}

func (device nvmlDevice) SetMigMode(mode int) (Return, Return) {
	var activationStatus Return
	ret := nvmlDeviceSetMigMode(device, uint32(mode), &activationStatus)
	return activationStatus, ret
}

// nvml.DeviceGetMigMode()
func (l *library) DeviceGetMigMode(device Device) (int, int, Return) {
	return device.GetMigMode()
}

func (device nvmlDevice) GetMigMode() (int, int, Return) {
	var currentMode, pendingMode uint32
	ret := nvmlDeviceGetMigMode(device, &currentMode, &pendingMode)
	return int(currentMode), int(pendingMode), ret
}

// nvml.DeviceGetGpuInstanceProfileInfo()
func (l *library) DeviceGetGpuInstanceProfileInfo(device Device, profile int) (GpuInstanceProfileInfo, Return) {
	return device.GetGpuInstanceProfileInfo(profile)
}

func (device nvmlDevice) GetGpuInstanceProfileInfo(profile int) (GpuInstanceProfileInfo, Return) {
	var info GpuInstanceProfileInfo
	ret := nvmlDeviceGetGpuInstanceProfileInfo(device, uint32(profile), &info)
	return info, ret
}

// nvml.DeviceGetGpuInstanceProfileInfoV()
type GpuInstanceProfileInfoHandler struct {
	device  nvmlDevice
	profile int
}

func (handler GpuInstanceProfileInfoHandler) V1() (GpuInstanceProfileInfo, Return) {
	return DeviceGetGpuInstanceProfileInfo(handler.device, handler.profile)
}

func (handler GpuInstanceProfileInfoHandler) V2() (GpuInstanceProfileInfo_v2, Return) {
	var info GpuInstanceProfileInfo_v2
	info.Version = STRUCT_VERSION(info, 2)
	ret := nvmlDeviceGetGpuInstanceProfileInfoV(handler.device, uint32(handler.profile), &info)
	return info, ret
}

func (l *library) DeviceGetGpuInstanceProfileInfoV(device Device, profile int) GpuInstanceProfileInfoHandler {
	return device.GetGpuInstanceProfileInfoV(profile)
}

func (device nvmlDevice) GetGpuInstanceProfileInfoV(profile int) GpuInstanceProfileInfoHandler {
	return GpuInstanceProfileInfoHandler{device, profile}
}

// nvml.DeviceGetGpuInstancePossiblePlacements()
func (l *library) DeviceGetGpuInstancePossiblePlacements(device Device, info *GpuInstanceProfileInfo) ([]GpuInstancePlacement, Return) {
	return device.GetGpuInstancePossiblePlacements(info)
}

func (device nvmlDevice) GetGpuInstancePossiblePlacements(info *GpuInstanceProfileInfo) ([]GpuInstancePlacement, Return) {
	if info == nil {
		return nil, ERROR_INVALID_ARGUMENT
	}
	var count uint32
	ret := nvmlDeviceGetGpuInstancePossiblePlacements(device, info.Id, nil, &count)
	if ret != SUCCESS {
		return nil, ret
	}
	if count == 0 {
		return []GpuInstancePlacement{}, ret
	}
	placements := make([]GpuInstancePlacement, count)
	ret = nvmlDeviceGetGpuInstancePossiblePlacements(device, info.Id, &placements[0], &count)
	return placements[:count], ret
}

// nvml.DeviceGetGpuInstanceRemainingCapacity()
func (l *library) DeviceGetGpuInstanceRemainingCapacity(device Device, info *GpuInstanceProfileInfo) (int, Return) {
	return device.GetGpuInstanceRemainingCapacity(info)
}

func (device nvmlDevice) GetGpuInstanceRemainingCapacity(info *GpuInstanceProfileInfo) (int, Return) {
	if info == nil {
		return 0, ERROR_INVALID_ARGUMENT
	}
	var count uint32
	ret := nvmlDeviceGetGpuInstanceRemainingCapacity(device, info.Id, &count)
	return int(count), ret
}

// nvml.DeviceCreateGpuInstance()
func (l *library) DeviceCreateGpuInstance(device Device, info *GpuInstanceProfileInfo) (GpuInstance, Return) {
	return device.CreateGpuInstance(info)
}

func (device nvmlDevice) CreateGpuInstance(info *GpuInstanceProfileInfo) (GpuInstance, Return) {
	if info == nil {
		return nil, ERROR_INVALID_ARGUMENT
	}
	var gpuInstance nvmlGpuInstance
	ret := nvmlDeviceCreateGpuInstance(device, info.Id, &gpuInstance)
	return gpuInstance, ret
}

// nvml.DeviceCreateGpuInstanceWithPlacement()
func (l *library) DeviceCreateGpuInstanceWithPlacement(device Device, info *GpuInstanceProfileInfo, placement *GpuInstancePlacement) (GpuInstance, Return) {
	return device.CreateGpuInstanceWithPlacement(info, placement)
}

func (device nvmlDevice) CreateGpuInstanceWithPlacement(info *GpuInstanceProfileInfo, placement *GpuInstancePlacement) (GpuInstance, Return) {
	if info == nil {
		return nil, ERROR_INVALID_ARGUMENT
	}
	var gpuInstance nvmlGpuInstance
	ret := nvmlDeviceCreateGpuInstanceWithPlacement(device, info.Id, placement, &gpuInstance)
	return gpuInstance, ret
}

// nvml.GpuInstanceDestroy()
func (l *library) GpuInstanceDestroy(gpuInstance GpuInstance) Return {
	return gpuInstance.Destroy()
}

func (gpuInstance nvmlGpuInstance) Destroy() Return {
	return nvmlGpuInstanceDestroy(gpuInstance)
}

// nvml.DeviceGetGpuInstances()
func (l *library) DeviceGetGpuInstances(device Device, info *GpuInstanceProfileInfo) ([]GpuInstance, Return) {
	return device.GetGpuInstances(info)
}

func (device nvmlDevice) GetGpuInstances(info *GpuInstanceProfileInfo) ([]GpuInstance, Return) {
	if info == nil {
		return nil, ERROR_INVALID_ARGUMENT
	}
	var count uint32 = info.InstanceCount
	gpuInstances := make([]nvmlGpuInstance, count)
	ret := nvmlDeviceGetGpuInstances(device, info.Id, &gpuInstances[0], &count)
	return convertSlice[nvmlGpuInstance, GpuInstance](gpuInstances[:count]), ret
}

// nvml.DeviceGetGpuInstanceById()
func (l *library) DeviceGetGpuInstanceById(device Device, id int) (GpuInstance, Return) {
	return device.GetGpuInstanceById(id)
}

func (device nvmlDevice) GetGpuInstanceById(id int) (GpuInstance, Return) {
	var gpuInstance nvmlGpuInstance
	ret := nvmlDeviceGetGpuInstanceById(device, uint32(id), &gpuInstance)
	return gpuInstance, ret
}

// nvml.GpuInstanceGetInfo()
func (l *library) GpuInstanceGetInfo(gpuInstance GpuInstance) (GpuInstanceInfo, Return) {
	return gpuInstance.GetInfo()
}

func (gpuInstance nvmlGpuInstance) GetInfo() (GpuInstanceInfo, Return) {
	var info nvmlGpuInstanceInfo
	ret := nvmlGpuInstanceGetInfo(gpuInstance, &info)
	return info.convert(), ret
}

// nvml.GpuInstanceGetComputeInstanceProfileInfo()
func (l *library) GpuInstanceGetComputeInstanceProfileInfo(gpuInstance GpuInstance, profile int, engProfile int) (ComputeInstanceProfileInfo, Return) {
	return gpuInstance.GetComputeInstanceProfileInfo(profile, engProfile)
}

func (gpuInstance nvmlGpuInstance) GetComputeInstanceProfileInfo(profile int, engProfile int) (ComputeInstanceProfileInfo, Return) {
	var info ComputeInstanceProfileInfo
	ret := nvmlGpuInstanceGetComputeInstanceProfileInfo(gpuInstance, uint32(profile), uint32(engProfile), &info)
	return info, ret
}

// nvml.GpuInstanceGetComputeInstanceProfileInfoV()
type ComputeInstanceProfileInfoHandler struct {
	gpuInstance nvmlGpuInstance
	profile     int
	engProfile  int
}

func (handler ComputeInstanceProfileInfoHandler) V1() (ComputeInstanceProfileInfo, Return) {
	return GpuInstanceGetComputeInstanceProfileInfo(handler.gpuInstance, handler.profile, handler.engProfile)
}

func (handler ComputeInstanceProfileInfoHandler) V2() (ComputeInstanceProfileInfo_v2, Return) {
	var info ComputeInstanceProfileInfo_v2
	info.Version = STRUCT_VERSION(info, 2)
	ret := nvmlGpuInstanceGetComputeInstanceProfileInfoV(handler.gpuInstance, uint32(handler.profile), uint32(handler.engProfile), &info)
	return info, ret
}

func (l *library) GpuInstanceGetComputeInstanceProfileInfoV(gpuInstance GpuInstance, profile int, engProfile int) ComputeInstanceProfileInfoHandler {
	return gpuInstance.GetComputeInstanceProfileInfoV(profile, engProfile)
}

func (gpuInstance nvmlGpuInstance) GetComputeInstanceProfileInfoV(profile int, engProfile int) ComputeInstanceProfileInfoHandler {
	return ComputeInstanceProfileInfoHandler{gpuInstance, profile, engProfile}
}

// nvml.GpuInstanceGetComputeInstanceRemainingCapacity()
func (l *library) GpuInstanceGetComputeInstanceRemainingCapacity(gpuInstance GpuInstance, info *ComputeInstanceProfileInfo) (int, Return) {
	return gpuInstance.GetComputeInstanceRemainingCapacity(info)
}

func (gpuInstance nvmlGpuInstance) GetComputeInstanceRemainingCapacity(info *ComputeInstanceProfileInfo) (int, Return) {
	if info == nil {
		return 0, ERROR_INVALID_ARGUMENT
	}
	var count uint32
	ret := nvmlGpuInstanceGetComputeInstanceRemainingCapacity(gpuInstance, info.Id, &count)
	return int(count), ret
}

// nvml.GpuInstanceCreateComputeInstance()
func (l *library) GpuInstanceCreateComputeInstance(gpuInstance GpuInstance, info *ComputeInstanceProfileInfo) (ComputeInstance, Return) {
	return gpuInstance.CreateComputeInstance(info)
}

func (gpuInstance nvmlGpuInstance) CreateComputeInstance(info *ComputeInstanceProfileInfo) (ComputeInstance, Return) {
	if info == nil {
		return nil, ERROR_INVALID_ARGUMENT
	}
	var computeInstance nvmlComputeInstance
	ret := nvmlGpuInstanceCreateComputeInstance(gpuInstance, info.Id, &computeInstance)
	return computeInstance, ret
}

// nvml.ComputeInstanceDestroy()
func (l *library) ComputeInstanceDestroy(computeInstance ComputeInstance) Return {
	return computeInstance.Destroy()
}

func (computeInstance nvmlComputeInstance) Destroy() Return {
	return nvmlComputeInstanceDestroy(computeInstance)
}

// nvml.GpuInstanceGetComputeInstances()
func (l *library) GpuInstanceGetComputeInstances(gpuInstance GpuInstance, info *ComputeInstanceProfileInfo) ([]ComputeInstance, Return) {
	return gpuInstance.GetComputeInstances(info)
}

func (gpuInstance nvmlGpuInstance) GetComputeInstances(info *ComputeInstanceProfileInfo) ([]ComputeInstance, Return) {
	if info == nil {
		return nil, ERROR_INVALID_ARGUMENT
	}
	var count uint32 = info.InstanceCount
	computeInstances := make([]nvmlComputeInstance, count)
	ret := nvmlGpuInstanceGetComputeInstances(gpuInstance, info.Id, &computeInstances[0], &count)
	return convertSlice[nvmlComputeInstance, ComputeInstance](computeInstances[:count]), ret
}

// nvml.GpuInstanceGetComputeInstanceById()
func (l *library) GpuInstanceGetComputeInstanceById(gpuInstance GpuInstance, id int) (ComputeInstance, Return) {
	return gpuInstance.GetComputeInstanceById(id)
}

func (gpuInstance nvmlGpuInstance) GetComputeInstanceById(id int) (ComputeInstance, Return) {
	var computeInstance nvmlComputeInstance
	ret := nvmlGpuInstanceGetComputeInstanceById(gpuInstance, uint32(id), &computeInstance)
	return computeInstance, ret
}

// nvml.ComputeInstanceGetInfo()
func (l *library) ComputeInstanceGetInfo(computeInstance ComputeInstance) (ComputeInstanceInfo, Return) {
	return computeInstance.GetInfo()
}

func (computeInstance nvmlComputeInstance) GetInfo() (ComputeInstanceInfo, Return) {
	var info nvmlComputeInstanceInfo
	ret := nvmlComputeInstanceGetInfo(computeInstance, &info)
	return info.convert(), ret
}

// nvml.DeviceIsMigDeviceHandle()
func (l *library) DeviceIsMigDeviceHandle(device Device) (bool, Return) {
	return device.IsMigDeviceHandle()
}

func (device nvmlDevice) IsMigDeviceHandle() (bool, Return) {
	var isMigDevice uint32
	ret := nvmlDeviceIsMigDeviceHandle(device, &isMigDevice)
	return (isMigDevice != 0), ret
}

// nvml DeviceGetGpuInstanceId()
func (l *library) DeviceGetGpuInstanceId(device Device) (int, Return) {
	return device.GetGpuInstanceId()
}

func (device nvmlDevice) GetGpuInstanceId() (int, Return) {
	var id uint32
	ret := nvmlDeviceGetGpuInstanceId(device, &id)
	return int(id), ret
}

// nvml.DeviceGetComputeInstanceId()
func (l *library) DeviceGetComputeInstanceId(device Device) (int, Return) {
	return device.GetComputeInstanceId()
}

func (device nvmlDevice) GetComputeInstanceId() (int, Return) {
	var id uint32
	ret := nvmlDeviceGetComputeInstanceId(device, &id)
	return int(id), ret
}

// nvml.DeviceGetMaxMigDeviceCount()
func (l *library) DeviceGetMaxMigDeviceCount(device Device) (int, Return) {
	return device.GetMaxMigDeviceCount()
}

func (device nvmlDevice) GetMaxMigDeviceCount() (int, Return) {
	var count uint32
	ret := nvmlDeviceGetMaxMigDeviceCount(device, &count)
	return int(count), ret
}

// nvml.DeviceGetMigDeviceHandleByIndex()
func (l *library) DeviceGetMigDeviceHandleByIndex(device Device, index int) (Device, Return) {
	return device.GetMigDeviceHandleByIndex(index)
}

func (device nvmlDevice) GetMigDeviceHandleByIndex(index int) (Device, Return) {
	var migDevice nvmlDevice
	ret := nvmlDeviceGetMigDeviceHandleByIndex(device, uint32(index), &migDevice)
	return migDevice, ret
}

// nvml.DeviceGetDeviceHandleFromMigDeviceHandle()
func (l *library) DeviceGetDeviceHandleFromMigDeviceHandle(migdevice Device) (Device, Return) {
	return migdevice.GetDeviceHandleFromMigDeviceHandle()
}

func (migDevice nvmlDevice) GetDeviceHandleFromMigDeviceHandle() (Device, Return) {
	var device nvmlDevice
	ret := nvmlDeviceGetDeviceHandleFromMigDeviceHandle(migDevice, &device)
	return device, ret
}

// nvml.DeviceGetBusType()
func (l *library) DeviceGetBusType(device Device) (BusType, Return) {
	return device.GetBusType()
}

func (device nvmlDevice) GetBusType() (BusType, Return) {
	var busType BusType
	ret := nvmlDeviceGetBusType(device, &busType)
	return busType, ret
}

// nvml.DeviceSetDefaultFanSpeed_v2()
func (l *library) DeviceSetDefaultFanSpeed_v2(device Device, fan int) Return {
	return device.SetDefaultFanSpeed_v2(fan)
}

func (device nvmlDevice) SetDefaultFanSpeed_v2(fan int) Return {
	return nvmlDeviceSetDefaultFanSpeed_v2(device, uint32(fan))
}

// nvml.DeviceGetMinMaxFanSpeed()
func (l *library) DeviceGetMinMaxFanSpeed(device Device) (int, int, Return) {
	return device.GetMinMaxFanSpeed()
}

func (device nvmlDevice) GetMinMaxFanSpeed() (int, int, Return) {
	var minSpeed, maxSpeed uint32
	ret := nvmlDeviceGetMinMaxFanSpeed(device, &minSpeed, &maxSpeed)
	return int(minSpeed), int(maxSpeed), ret
}

// nvml.DeviceGetThermalSettings()
func (l *library) DeviceGetThermalSettings(device Device, sensorIndex uint32) (GpuThermalSettings, Return) {
	return device.GetThermalSettings(sensorIndex)
}

func (device nvmlDevice) GetThermalSettings(sensorIndex uint32) (GpuThermalSettings, Return) {
	var pThermalSettings GpuThermalSettings
	ret := nvmlDeviceGetThermalSettings(device, sensorIndex, &pThermalSettings)
	return pThermalSettings, ret
}

// nvml.DeviceGetDefaultEccMode()
func (l *library) DeviceGetDefaultEccMode(device Device) (EnableState, Return) {
	return device.GetDefaultEccMode()
}

func (device nvmlDevice) GetDefaultEccMode() (EnableState, Return) {
	var defaultMode EnableState
	ret := nvmlDeviceGetDefaultEccMode(device, &defaultMode)
	return defaultMode, ret
}

// nvml.DeviceGetPcieSpeed()
func (l *library) DeviceGetPcieSpeed(device Device) (int, Return) {
	return device.GetPcieSpeed()
}

func (device nvmlDevice) GetPcieSpeed() (int, Return) {
	var pcieSpeed uint32
	ret := nvmlDeviceGetPcieSpeed(device, &pcieSpeed)
	return int(pcieSpeed), ret
}

// nvml.DeviceGetGspFirmwareVersion()
func (l *library) DeviceGetGspFirmwareVersion(device Device) (string, Return) {
	return device.GetGspFirmwareVersion()
}

func (device nvmlDevice) GetGspFirmwareVersion() (string, Return) {
	version := make([]byte, GSP_FIRMWARE_VERSION_BUF_SIZE)
	ret := nvmlDeviceGetGspFirmwareVersion(device, &version[0])
	return string(version[:clen(version)]), ret
}

// nvml.DeviceGetGspFirmwareMode()
func (l *library) DeviceGetGspFirmwareMode(device Device) (bool, bool, Return) {
	return device.GetGspFirmwareMode()
}

func (device nvmlDevice) GetGspFirmwareMode() (bool, bool, Return) {
	var isEnabled, defaultMode uint32
	ret := nvmlDeviceGetGspFirmwareMode(device, &isEnabled, &defaultMode)
	return (isEnabled != 0), (defaultMode != 0), ret
}

// nvml.DeviceGetDynamicPstatesInfo()
func (l *library) DeviceGetDynamicPstatesInfo(device Device) (GpuDynamicPstatesInfo, Return) {
	return device.GetDynamicPstatesInfo()
}

func (device nvmlDevice) GetDynamicPstatesInfo() (GpuDynamicPstatesInfo, Return) {
	var pDynamicPstatesInfo GpuDynamicPstatesInfo
	ret := nvmlDeviceGetDynamicPstatesInfo(device, &pDynamicPstatesInfo)
	return pDynamicPstatesInfo, ret
}

// nvml.DeviceSetFanSpeed_v2()
func (l *library) DeviceSetFanSpeed_v2(device Device, fan int, speed int) Return {
	return device.SetFanSpeed_v2(fan, speed)
}

func (device nvmlDevice) SetFanSpeed_v2(fan int, speed int) Return {
	return nvmlDeviceSetFanSpeed_v2(device, uint32(fan), uint32(speed))
}

// nvml.DeviceGetGpcClkVfOffset()
func (l *library) DeviceGetGpcClkVfOffset(device Device) (int, Return) {
	return device.GetGpcClkVfOffset()
}

func (device nvmlDevice) GetGpcClkVfOffset() (int, Return) {
	var offset int32
	ret := nvmlDeviceGetGpcClkVfOffset(device, &offset)
	return int(offset), ret
}

// nvml.DeviceSetGpcClkVfOffset()
func (l *library) DeviceSetGpcClkVfOffset(device Device, offset int) Return {
	return device.SetGpcClkVfOffset(offset)
}

func (device nvmlDevice) SetGpcClkVfOffset(offset int) Return {
	return nvmlDeviceSetGpcClkVfOffset(device, int32(offset))
}

// nvml.DeviceGetMinMaxClockOfPState()
func (l *library) DeviceGetMinMaxClockOfPState(device Device, clockType ClockType, pstate Pstates) (uint32, uint32, Return) {
	return device.GetMinMaxClockOfPState(clockType, pstate)
}

func (device nvmlDevice) GetMinMaxClockOfPState(clockType ClockType, pstate Pstates) (uint32, uint32, Return) {
	var minClockMHz, maxClockMHz uint32
	ret := nvmlDeviceGetMinMaxClockOfPState(device, clockType, pstate, &minClockMHz, &maxClockMHz)
	return minClockMHz, maxClockMHz, ret
}

// nvml.DeviceGetSupportedPerformanceStates()
func (l *library) DeviceGetSupportedPerformanceStates(device Device) ([]Pstates, Return) {
	return device.GetSupportedPerformanceStates()
}

func (device nvmlDevice) GetSupportedPerformanceStates() ([]Pstates, Return) {
	pstates := make([]Pstates, MAX_GPU_PERF_PSTATES)
	ret := nvmlDeviceGetSupportedPerformanceStates(device, &pstates[0], MAX_GPU_PERF_PSTATES)
	for i := 0; i < MAX_GPU_PERF_PSTATES; i++ {
		if pstates[i] == PSTATE_UNKNOWN {
			return pstates[0:i], ret
		}
	}
	return pstates, ret
}

// nvml.DeviceGetTargetFanSpeed()
func (l *library) DeviceGetTargetFanSpeed(device Device, fan int) (int, Return) {
	return device.GetTargetFanSpeed(fan)
}

func (device nvmlDevice) GetTargetFanSpeed(fan int) (int, Return) {
	var targetSpeed uint32
	ret := nvmlDeviceGetTargetFanSpeed(device, uint32(fan), &targetSpeed)
	return int(targetSpeed), ret
}

// nvml.DeviceGetMemClkVfOffset()
func (l *library) DeviceGetMemClkVfOffset(device Device) (int, Return) {
	return device.GetMemClkVfOffset()
}

func (device nvmlDevice) GetMemClkVfOffset() (int, Return) {
	var offset int32
	ret := nvmlDeviceGetMemClkVfOffset(device, &offset)
	return int(offset), ret
}

// nvml.DeviceSetMemClkVfOffset()
func (l *library) DeviceSetMemClkVfOffset(device Device, offset int) Return {
	return device.SetMemClkVfOffset(offset)
}

func (device nvmlDevice) SetMemClkVfOffset(offset int) Return {
	return nvmlDeviceSetMemClkVfOffset(device, int32(offset))
}

// nvml.DeviceGetGpcClkMinMaxVfOffset()
func (l *library) DeviceGetGpcClkMinMaxVfOffset(device Device) (int, int, Return) {
	return device.GetGpcClkMinMaxVfOffset()
}

func (device nvmlDevice) GetGpcClkMinMaxVfOffset() (int, int, Return) {
	var minOffset, maxOffset int32
	ret := nvmlDeviceGetGpcClkMinMaxVfOffset(device, &minOffset, &maxOffset)
	return int(minOffset), int(maxOffset), ret
}

// nvml.DeviceGetMemClkMinMaxVfOffset()
func (l *library) DeviceGetMemClkMinMaxVfOffset(device Device) (int, int, Return) {
	return device.GetMemClkMinMaxVfOffset()
}

func (device nvmlDevice) GetMemClkMinMaxVfOffset() (int, int, Return) {
	var minOffset, maxOffset int32
	ret := nvmlDeviceGetMemClkMinMaxVfOffset(device, &minOffset, &maxOffset)
	return int(minOffset), int(maxOffset), ret
}

// nvml.DeviceGetGpuMaxPcieLinkGeneration()
func (l *library) DeviceGetGpuMaxPcieLinkGeneration(device Device) (int, Return) {
	return device.GetGpuMaxPcieLinkGeneration()
}

func (device nvmlDevice) GetGpuMaxPcieLinkGeneration() (int, Return) {
	var maxLinkGenDevice uint32
	ret := nvmlDeviceGetGpuMaxPcieLinkGeneration(device, &maxLinkGenDevice)
	return int(maxLinkGenDevice), ret
}

// nvml.DeviceGetFanControlPolicy_v2()
func (l *library) DeviceGetFanControlPolicy_v2(device Device, fan int) (FanControlPolicy, Return) {
	return device.GetFanControlPolicy_v2(fan)
}

func (device nvmlDevice) GetFanControlPolicy_v2(fan int) (FanControlPolicy, Return) {
	var policy FanControlPolicy
	ret := nvmlDeviceGetFanControlPolicy_v2(device, uint32(fan), &policy)
	return policy, ret
}

// nvml.DeviceSetFanControlPolicy()
func (l *library) DeviceSetFanControlPolicy(device Device, fan int, policy FanControlPolicy) Return {
	return device.SetFanControlPolicy(fan, policy)
}

func (device nvmlDevice) SetFanControlPolicy(fan int, policy FanControlPolicy) Return {
	return nvmlDeviceSetFanControlPolicy(device, uint32(fan), policy)
}

// nvml.DeviceClearFieldValues()
func (l *library) DeviceClearFieldValues(device Device, values []FieldValue) Return {
	return device.ClearFieldValues(values)
}

func (device nvmlDevice) ClearFieldValues(values []FieldValue) Return {
	valuesCount := len(values)
	return nvmlDeviceClearFieldValues(device, int32(valuesCount), &values[0])
}

// nvml.DeviceGetVgpuCapabilities()
func (l *library) DeviceGetVgpuCapabilities(device Device, capability DeviceVgpuCapability) (bool, Return) {
	return device.GetVgpuCapabilities(capability)
}

func (device nvmlDevice) GetVgpuCapabilities(capability DeviceVgpuCapability) (bool, Return) {
	var capResult uint32
	ret := nvmlDeviceGetVgpuCapabilities(device, capability, &capResult)
	return (capResult != 0), ret
}

// nvml.DeviceGetVgpuSchedulerLog()
func (l *library) DeviceGetVgpuSchedulerLog(device Device) (VgpuSchedulerLog, Return) {
	return device.GetVgpuSchedulerLog()
}

func (device nvmlDevice) GetVgpuSchedulerLog() (VgpuSchedulerLog, Return) {
	var pSchedulerLog VgpuSchedulerLog
	ret := nvmlDeviceGetVgpuSchedulerLog(device, &pSchedulerLog)
	return pSchedulerLog, ret
}

// nvml.DeviceGetVgpuSchedulerState()
func (l *library) DeviceGetVgpuSchedulerState(device Device) (VgpuSchedulerGetState, Return) {
	return device.GetVgpuSchedulerState()
}

func (device nvmlDevice) GetVgpuSchedulerState() (VgpuSchedulerGetState, Return) {
	var pSchedulerState VgpuSchedulerGetState
	ret := nvmlDeviceGetVgpuSchedulerState(device, &pSchedulerState)
	return pSchedulerState, ret
}

// nvml.DeviceSetVgpuSchedulerState()
func (l *library) DeviceSetVgpuSchedulerState(device Device, pSchedulerState *VgpuSchedulerSetState) Return {
	return device.SetVgpuSchedulerState(pSchedulerState)
}

func (device nvmlDevice) SetVgpuSchedulerState(pSchedulerState *VgpuSchedulerSetState) Return {
	return nvmlDeviceSetVgpuSchedulerState(device, pSchedulerState)
}

// nvml.DeviceGetVgpuSchedulerCapabilities()
func (l *library) DeviceGetVgpuSchedulerCapabilities(device Device) (VgpuSchedulerCapabilities, Return) {
	return device.GetVgpuSchedulerCapabilities()
}

func (device nvmlDevice) GetVgpuSchedulerCapabilities() (VgpuSchedulerCapabilities, Return) {
	var pCapabilities VgpuSchedulerCapabilities
	ret := nvmlDeviceGetVgpuSchedulerCapabilities(device, &pCapabilities)
	return pCapabilities, ret
}

// nvml.GpuInstanceGetComputeInstancePossiblePlacements()
func (l *library) GpuInstanceGetComputeInstancePossiblePlacements(gpuInstance GpuInstance, info *ComputeInstanceProfileInfo) ([]ComputeInstancePlacement, Return) {
	return gpuInstance.GetComputeInstancePossiblePlacements(info)
}

func (gpuInstance nvmlGpuInstance) GetComputeInstancePossiblePlacements(info *ComputeInstanceProfileInfo) ([]ComputeInstancePlacement, Return) {
	var count uint32
	ret := nvmlGpuInstanceGetComputeInstancePossiblePlacements(gpuInstance, info.Id, nil, &count)
	if ret != SUCCESS {
		return nil, ret
	}
	if count == 0 {
		return []ComputeInstancePlacement{}, ret
	}
	placementArray := make([]ComputeInstancePlacement, count)
	ret = nvmlGpuInstanceGetComputeInstancePossiblePlacements(gpuInstance, info.Id, &placementArray[0], &count)
	return placementArray, ret
}

// nvml.GpuInstanceCreateComputeInstanceWithPlacement()
func (l *library) GpuInstanceCreateComputeInstanceWithPlacement(gpuInstance GpuInstance, info *ComputeInstanceProfileInfo, placement *ComputeInstancePlacement) (ComputeInstance, Return) {
	return gpuInstance.CreateComputeInstanceWithPlacement(info, placement)
}

func (gpuInstance nvmlGpuInstance) CreateComputeInstanceWithPlacement(info *ComputeInstanceProfileInfo, placement *ComputeInstancePlacement) (ComputeInstance, Return) {
	var computeInstance nvmlComputeInstance
	ret := nvmlGpuInstanceCreateComputeInstanceWithPlacement(gpuInstance, info.Id, placement, &computeInstance)
	return computeInstance, ret
}

// nvml.DeviceGetGpuFabricInfo()
func (l *library) DeviceGetGpuFabricInfo(device Device) (GpuFabricInfo, Return) {
	return device.GetGpuFabricInfo()
}

func (device nvmlDevice) GetGpuFabricInfo() (GpuFabricInfo, Return) {
	var gpuFabricInfo GpuFabricInfo
	ret := nvmlDeviceGetGpuFabricInfo(device, &gpuFabricInfo)
	return gpuFabricInfo, ret
}

// nvml.DeviceSetNvLinkDeviceLowPowerThreshold()
func (l *library) DeviceSetNvLinkDeviceLowPowerThreshold(device Device, info *NvLinkPowerThres) Return {
	return device.SetNvLinkDeviceLowPowerThreshold(info)
}

func (device nvmlDevice) SetNvLinkDeviceLowPowerThreshold(info *NvLinkPowerThres) Return {
	return nvmlDeviceSetNvLinkDeviceLowPowerThreshold(device, info)
}

// nvml.DeviceGetModuleId()
func (l *library) DeviceGetModuleId(device Device) (int, Return) {
	return device.GetModuleId()
}

func (device nvmlDevice) GetModuleId() (int, Return) {
	var moduleID uint32
	ret := nvmlDeviceGetModuleId(device, &moduleID)
	return int(moduleID), ret
}

// nvml.DeviceGetCurrentClocksEventReasons()
func (l *library) DeviceGetCurrentClocksEventReasons(device Device) (uint64, Return) {
	return device.GetCurrentClocksEventReasons()
}

func (device nvmlDevice) GetCurrentClocksEventReasons() (uint64, Return) {
	var clocksEventReasons uint64
	ret := nvmlDeviceGetCurrentClocksEventReasons(device, &clocksEventReasons)
	return clocksEventReasons, ret
}

// nvml.DeviceGetSupportedClocksEventReasons()
func (l *library) DeviceGetSupportedClocksEventReasons(device Device) (uint64, Return) {
	return device.GetSupportedClocksEventReasons()
}

func (device nvmlDevice) GetSupportedClocksEventReasons() (uint64, Return) {
	var supportedClocksEventReasons uint64
	ret := nvmlDeviceGetSupportedClocksEventReasons(device, &supportedClocksEventReasons)
	return supportedClocksEventReasons, ret
}

// nvml.DeviceGetJpgUtilization()
func (l *library) DeviceGetJpgUtilization(device Device) (uint32, uint32, Return) {
	return device.GetJpgUtilization()
}

func (device nvmlDevice) GetJpgUtilization() (uint32, uint32, Return) {
	var utilization, samplingPeriodUs uint32
	ret := nvmlDeviceGetJpgUtilization(device, &utilization, &samplingPeriodUs)
	return utilization, samplingPeriodUs, ret
}

// nvml.DeviceGetOfaUtilization()
func (l *library) DeviceGetOfaUtilization(device Device) (uint32, uint32, Return) {
	return device.GetOfaUtilization()
}

func (device nvmlDevice) GetOfaUtilization() (uint32, uint32, Return) {
	var utilization, samplingPeriodUs uint32
	ret := nvmlDeviceGetOfaUtilization(device, &utilization, &samplingPeriodUs)
	return utilization, samplingPeriodUs, ret
}

// nvml.DeviceGetRunningProcessDetailList()
func (l *library) DeviceGetRunningProcessDetailList(device Device) (ProcessDetailList, Return) {
	return device.GetRunningProcessDetailList()
}

func (device nvmlDevice) GetRunningProcessDetailList() (ProcessDetailList, Return) {
	var plist ProcessDetailList
	ret := nvmlDeviceGetRunningProcessDetailList(device, &plist)
	return plist, ret
}

// nvml.DeviceGetConfComputeMemSizeInfo()
func (l *library) DeviceGetConfComputeMemSizeInfo(device Device) (ConfComputeMemSizeInfo, Return) {
	return device.GetConfComputeMemSizeInfo()
}

func (device nvmlDevice) GetConfComputeMemSizeInfo() (ConfComputeMemSizeInfo, Return) {
	var memInfo ConfComputeMemSizeInfo
	ret := nvmlDeviceGetConfComputeMemSizeInfo(device, &memInfo)
	return memInfo, ret
}

// nvml.DeviceGetConfComputeProtectedMemoryUsage()
func (l *library) DeviceGetConfComputeProtectedMemoryUsage(device Device) (Memory, Return) {
	return device.GetConfComputeProtectedMemoryUsage()
}

func (device nvmlDevice) GetConfComputeProtectedMemoryUsage() (Memory, Return) {
	var memory Memory
	ret := nvmlDeviceGetConfComputeProtectedMemoryUsage(device, &memory)
	return memory, ret
}

// nvml.DeviceGetConfComputeGpuCertificate()
func (l *library) DeviceGetConfComputeGpuCertificate(device Device) (ConfComputeGpuCertificate, Return) {
	return device.GetConfComputeGpuCertificate()
}

func (device nvmlDevice) GetConfComputeGpuCertificate() (ConfComputeGpuCertificate, Return) {
	var gpuCert ConfComputeGpuCertificate
	ret := nvmlDeviceGetConfComputeGpuCertificate(device, &gpuCert)
	return gpuCert, ret
}

// nvml.DeviceGetConfComputeGpuAttestationReport()
func (l *library) DeviceGetConfComputeGpuAttestationReport(device Device) (ConfComputeGpuAttestationReport, Return) {
	return device.GetConfComputeGpuAttestationReport()
}

func (device nvmlDevice) GetConfComputeGpuAttestationReport() (ConfComputeGpuAttestationReport, Return) {
	var gpuAtstReport ConfComputeGpuAttestationReport
	ret := nvmlDeviceGetConfComputeGpuAttestationReport(device, &gpuAtstReport)
	return gpuAtstReport, ret
}

// nvml.DeviceSetConfComputeUnprotectedMemSize()
func (l *library) DeviceSetConfComputeUnprotectedMemSize(device Device, sizeKiB uint64) Return {
	return device.SetConfComputeUnprotectedMemSize(sizeKiB)
}

func (device nvmlDevice) SetConfComputeUnprotectedMemSize(sizeKiB uint64) Return {
	return nvmlDeviceSetConfComputeUnprotectedMemSize(device, sizeKiB)
}

// nvml.DeviceSetPowerManagementLimit_v2()
func (l *library) DeviceSetPowerManagementLimit_v2(device Device, powerValue *PowerValue_v2) Return {
	return device.SetPowerManagementLimit_v2(powerValue)
}

func (device nvmlDevice) SetPowerManagementLimit_v2(powerValue *PowerValue_v2) Return {
	return nvmlDeviceSetPowerManagementLimit_v2(device, powerValue)
}

// nvml.DeviceGetC2cModeInfoV()
type C2cModeInfoHandler struct {
	device nvmlDevice
}

func (handler C2cModeInfoHandler) V1() (C2cModeInfo_v1, Return) {
	var c2cModeInfo C2cModeInfo_v1
	ret := nvmlDeviceGetC2cModeInfoV(handler.device, &c2cModeInfo)
	return c2cModeInfo, ret
}

func (l *library) DeviceGetC2cModeInfoV(device Device) C2cModeInfoHandler {
	return device.GetC2cModeInfoV()
}

func (device nvmlDevice) GetC2cModeInfoV() C2cModeInfoHandler {
	return C2cModeInfoHandler{device}
}

// nvml.DeviceGetLastBBXFlushTime()
func (l *library) DeviceGetLastBBXFlushTime(device Device) (uint64, uint, Return) {
	return device.GetLastBBXFlushTime()
}

func (device nvmlDevice) GetLastBBXFlushTime() (uint64, uint, Return) {
	var timestamp uint64
	var durationUs uint
	ret := nvmlDeviceGetLastBBXFlushTime(device, &timestamp, &durationUs)
	return timestamp, durationUs, ret
}

// nvml.DeviceGetNumaNodeId()
func (l *library) DeviceGetNumaNodeId(device Device) (int, Return) {
	return device.GetNumaNodeId()
}

func (device nvmlDevice) GetNumaNodeId() (int, Return) {
	var node uint32
	ret := nvmlDeviceGetNumaNodeId(device, &node)
	return int(node), ret
}

// nvml.DeviceGetPciInfoExt()
func (l *library) DeviceGetPciInfoExt(device Device) (PciInfoExt, Return) {
	return device.GetPciInfoExt()
}

func (device nvmlDevice) GetPciInfoExt() (PciInfoExt, Return) {
	var pciInfo PciInfoExt
	ret := nvmlDeviceGetPciInfoExt(device, &pciInfo)
	return pciInfo, ret
}

// nvml.DeviceGetGpuFabricInfoV()
type GpuFabricInfoHandler struct {
	device nvmlDevice
}

func (handler GpuFabricInfoHandler) V1() (GpuFabricInfo, Return) {
	return handler.device.GetGpuFabricInfo()
}

func (handler GpuFabricInfoHandler) V2() (GpuFabricInfo_v2, Return) {
	var info GpuFabricInfoV
	info.Version = STRUCT_VERSION(info, 2)
	ret := nvmlDeviceGetGpuFabricInfoV(handler.device, &info)
	return GpuFabricInfo_v2(info), ret
}

func (l *library) DeviceGetGpuFabricInfoV(device Device) GpuFabricInfoHandler {
	return device.GetGpuFabricInfoV()
}

func (device nvmlDevice) GetGpuFabricInfoV() GpuFabricInfoHandler {
	return GpuFabricInfoHandler{device}
}

// nvml.DeviceGetProcessesUtilizationInfo()
func (l *library) DeviceGetProcessesUtilizationInfo(device Device) (ProcessesUtilizationInfo, Return) {
	return device.GetProcessesUtilizationInfo()
}

func (device nvmlDevice) GetProcessesUtilizationInfo() (ProcessesUtilizationInfo, Return) {
	var processesUtilInfo ProcessesUtilizationInfo
	ret := nvmlDeviceGetProcessesUtilizationInfo(device, &processesUtilInfo)
	return processesUtilInfo, ret
}

// nvml.DeviceGetVgpuHeterogeneousMode()
func (l *library) DeviceGetVgpuHeterogeneousMode(device Device) (VgpuHeterogeneousMode, Return) {
	return device.GetVgpuHeterogeneousMode()
}

func (device nvmlDevice) GetVgpuHeterogeneousMode() (VgpuHeterogeneousMode, Return) {
	var heterogeneousMode VgpuHeterogeneousMode
	ret := nvmlDeviceGetVgpuHeterogeneousMode(device, &heterogeneousMode)
	return heterogeneousMode, ret
}

// nvml.DeviceSetVgpuHeterogeneousMode()
func (l *library) DeviceSetVgpuHeterogeneousMode(device Device, heterogeneousMode VgpuHeterogeneousMode) Return {
	return device.SetVgpuHeterogeneousMode(heterogeneousMode)
}

func (device nvmlDevice) SetVgpuHeterogeneousMode(heterogeneousMode VgpuHeterogeneousMode) Return {
	ret := nvmlDeviceSetVgpuHeterogeneousMode(device, &heterogeneousMode)
	return ret
}

// nvml.DeviceGetVgpuTypeSupportedPlacements()
func (l *library) DeviceGetVgpuTypeSupportedPlacements(device Device, vgpuTypeId VgpuTypeId) (VgpuPlacementList, Return) {
	return device.GetVgpuTypeSupportedPlacements(vgpuTypeId)
}

func (device nvmlDevice) GetVgpuTypeSupportedPlacements(vgpuTypeId VgpuTypeId) (VgpuPlacementList, Return) {
	return vgpuTypeId.GetSupportedPlacements(device)
}

func (vgpuTypeId nvmlVgpuTypeId) GetSupportedPlacements(device Device) (VgpuPlacementList, Return) {
	var placementList VgpuPlacementList
	ret := nvmlDeviceGetVgpuTypeSupportedPlacements(nvmlDeviceHandle(device), vgpuTypeId, &placementList)
	return placementList, ret
}

// nvml.DeviceGetVgpuTypeCreatablePlacements()
func (l *library) DeviceGetVgpuTypeCreatablePlacements(device Device, vgpuTypeId VgpuTypeId) (VgpuPlacementList, Return) {
	return device.GetVgpuTypeCreatablePlacements(vgpuTypeId)
}

func (device nvmlDevice) GetVgpuTypeCreatablePlacements(vgpuTypeId VgpuTypeId) (VgpuPlacementList, Return) {
	return vgpuTypeId.GetCreatablePlacements(device)
}

func (vgpuTypeId nvmlVgpuTypeId) GetCreatablePlacements(device Device) (VgpuPlacementList, Return) {
	var placementList VgpuPlacementList
	ret := nvmlDeviceGetVgpuTypeCreatablePlacements(nvmlDeviceHandle(device), vgpuTypeId, &placementList)
	return placementList, ret
}

// nvml.DeviceSetVgpuCapabilities()
func (l *library) DeviceSetVgpuCapabilities(device Device, capability DeviceVgpuCapability, state EnableState) Return {
	return device.SetVgpuCapabilities(capability, state)
}

func (device nvmlDevice) SetVgpuCapabilities(capability DeviceVgpuCapability, state EnableState) Return {
	ret := nvmlDeviceSetVgpuCapabilities(device, capability, state)
	return ret
}

// nvml.DeviceGetVgpuInstancesUtilizationInfo()
func (l *library) DeviceGetVgpuInstancesUtilizationInfo(device Device) (VgpuInstancesUtilizationInfo, Return) {
	return device.GetVgpuInstancesUtilizationInfo()
}

func (device nvmlDevice) GetVgpuInstancesUtilizationInfo() (VgpuInstancesUtilizationInfo, Return) {
	var vgpuUtilInfo VgpuInstancesUtilizationInfo
	ret := nvmlDeviceGetVgpuInstancesUtilizationInfo(device, &vgpuUtilInfo)
	return vgpuUtilInfo, ret
}

// nvml.DeviceGetVgpuProcessesUtilizationInfo()
func (l *library) DeviceGetVgpuProcessesUtilizationInfo(device Device) (VgpuProcessesUtilizationInfo, Return) {
	return device.GetVgpuProcessesUtilizationInfo()
}

func (device nvmlDevice) GetVgpuProcessesUtilizationInfo() (VgpuProcessesUtilizationInfo, Return) {
	var vgpuProcUtilInfo VgpuProcessesUtilizationInfo
	ret := nvmlDeviceGetVgpuProcessesUtilizationInfo(device, &vgpuProcUtilInfo)
	return vgpuProcUtilInfo, ret
}

// nvml.DeviceGetSramEccErrorStatus()
func (l *library) DeviceGetSramEccErrorStatus(device Device) (EccSramErrorStatus, Return) {
	return device.GetSramEccErrorStatus()
}

func (device nvmlDevice) GetSramEccErrorStatus() (EccSramErrorStatus, Return) {
	var status EccSramErrorStatus
	ret := nvmlDeviceGetSramEccErrorStatus(device, &status)
	return status, ret
}

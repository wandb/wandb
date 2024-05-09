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

// EventData includes an interface type for Device instead of nvmlDevice
type EventData struct {
	Device            Device
	EventType         uint64
	EventData         uint64
	GpuInstanceId     uint32
	ComputeInstanceId uint32
}

func (e EventData) convert() nvmlEventData {
	out := nvmlEventData{
		Device:            e.Device.(nvmlDevice),
		EventType:         e.EventType,
		EventData:         e.EventData,
		GpuInstanceId:     e.GpuInstanceId,
		ComputeInstanceId: e.ComputeInstanceId,
	}
	return out
}

func (e nvmlEventData) convert() EventData {
	out := EventData{
		Device:            e.Device,
		EventType:         e.EventType,
		EventData:         e.EventData,
		GpuInstanceId:     e.GpuInstanceId,
		ComputeInstanceId: e.ComputeInstanceId,
	}
	return out
}

// nvml.EventSetCreate()
func (l *library) EventSetCreate() (EventSet, Return) {
	var Set nvmlEventSet
	ret := nvmlEventSetCreate(&Set)
	return Set, ret
}

// nvml.EventSetWait()
func (l *library) EventSetWait(set EventSet, timeoutms uint32) (EventData, Return) {
	return set.Wait(timeoutms)
}

func (set nvmlEventSet) Wait(timeoutms uint32) (EventData, Return) {
	var data nvmlEventData
	ret := nvmlEventSetWait(set, &data, timeoutms)
	return data.convert(), ret
}

// nvml.EventSetFree()
func (l *library) EventSetFree(set EventSet) Return {
	return set.Free()
}

func (set nvmlEventSet) Free() Return {
	return nvmlEventSetFree(set)
}

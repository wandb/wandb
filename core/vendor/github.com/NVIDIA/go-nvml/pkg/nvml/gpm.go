// Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
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

// GpmMetricsGetType includes interface types for GpmSample instead of nvmlGpmSample
type GpmMetricsGetType struct {
	Version    uint32
	NumMetrics uint32
	Sample1    GpmSample
	Sample2    GpmSample
	Metrics    [98]GpmMetric
}

func (g *GpmMetricsGetType) convert() *nvmlGpmMetricsGetType {
	out := &nvmlGpmMetricsGetType{
		Version:    g.Version,
		NumMetrics: g.NumMetrics,
		Sample1:    g.Sample1.(nvmlGpmSample),
		Sample2:    g.Sample2.(nvmlGpmSample),
	}
	for i := range g.Metrics {
		out.Metrics[i] = g.Metrics[i]
	}
	return out
}

func (g *nvmlGpmMetricsGetType) convert() *GpmMetricsGetType {
	out := &GpmMetricsGetType{
		Version:    g.Version,
		NumMetrics: g.NumMetrics,
		Sample1:    g.Sample1,
		Sample2:    g.Sample2,
	}
	for i := range g.Metrics {
		out.Metrics[i] = g.Metrics[i]
	}
	return out
}

// nvml.GpmMetricsGet()
type GpmMetricsGetVType struct {
	metricsGet *GpmMetricsGetType
}

func (l *library) GpmMetricsGetV(metricsGet *GpmMetricsGetType) GpmMetricsGetVType {
	return GpmMetricsGetVType{metricsGet}
}

// nvmlGpmMetricsGetStub is a stub function that can be overridden for testing.
var nvmlGpmMetricsGetStub = nvmlGpmMetricsGet

func (metricsGetV GpmMetricsGetVType) V1() Return {
	metricsGetV.metricsGet.Version = 1
	return gpmMetricsGet(metricsGetV.metricsGet)
}

func (l *library) GpmMetricsGet(metricsGet *GpmMetricsGetType) Return {
	metricsGet.Version = GPM_METRICS_GET_VERSION
	return gpmMetricsGet(metricsGet)
}

func gpmMetricsGet(metricsGet *GpmMetricsGetType) Return {
	nvmlMetricsGet := metricsGet.convert()
	ret := nvmlGpmMetricsGetStub(nvmlMetricsGet)
	*metricsGet = *nvmlMetricsGet.convert()
	return ret
}

// nvml.GpmSampleFree()
func (l *library) GpmSampleFree(gpmSample GpmSample) Return {
	return gpmSample.Free()
}

func (gpmSample nvmlGpmSample) Free() Return {
	return nvmlGpmSampleFree(gpmSample)
}

// nvml.GpmSampleAlloc()
func (l *library) GpmSampleAlloc() (GpmSample, Return) {
	var gpmSample nvmlGpmSample
	ret := nvmlGpmSampleAlloc(&gpmSample)
	return gpmSample, ret
}

// nvml.GpmSampleGet()
func (l *library) GpmSampleGet(device Device, gpmSample GpmSample) Return {
	return gpmSample.Get(device)
}

func (device nvmlDevice) GpmSampleGet(gpmSample GpmSample) Return {
	return gpmSample.Get(device)
}

func (gpmSample nvmlGpmSample) Get(device Device) Return {
	return nvmlGpmSampleGet(nvmlDeviceHandle(device), gpmSample)
}

// nvml.GpmQueryDeviceSupport()
type GpmSupportV struct {
	device nvmlDevice
}

func (l *library) GpmQueryDeviceSupportV(device Device) GpmSupportV {
	return device.GpmQueryDeviceSupportV()
}

func (device nvmlDevice) GpmQueryDeviceSupportV() GpmSupportV {
	return GpmSupportV{device}
}

func (gpmSupportV GpmSupportV) V1() (GpmSupport, Return) {
	var gpmSupport GpmSupport
	gpmSupport.Version = 1
	ret := nvmlGpmQueryDeviceSupport(gpmSupportV.device, &gpmSupport)
	return gpmSupport, ret
}

func (l *library) GpmQueryDeviceSupport(device Device) (GpmSupport, Return) {
	return device.GpmQueryDeviceSupport()
}

func (device nvmlDevice) GpmQueryDeviceSupport() (GpmSupport, Return) {
	var gpmSupport GpmSupport
	gpmSupport.Version = GPM_SUPPORT_VERSION
	ret := nvmlGpmQueryDeviceSupport(device, &gpmSupport)
	return gpmSupport, ret
}

// nvml.GpmMigSampleGet()
func (l *library) GpmMigSampleGet(device Device, gpuInstanceId int, gpmSample GpmSample) Return {
	return gpmSample.MigGet(device, gpuInstanceId)
}

func (device nvmlDevice) GpmMigSampleGet(gpuInstanceId int, gpmSample GpmSample) Return {
	return gpmSample.MigGet(device, gpuInstanceId)
}

func (gpmSample nvmlGpmSample) MigGet(device Device, gpuInstanceId int) Return {
	return nvmlGpmMigSampleGet(nvmlDeviceHandle(device), uint32(gpuInstanceId), gpmSample)
}

// nvml.GpmQueryIfStreamingEnabled()
func (l *library) GpmQueryIfStreamingEnabled(device Device) (uint32, Return) {
	return device.GpmQueryIfStreamingEnabled()
}

func (device nvmlDevice) GpmQueryIfStreamingEnabled() (uint32, Return) {
	var state uint32
	ret := nvmlGpmQueryIfStreamingEnabled(device, &state)
	return state, ret
}

// nvml.GpmSetStreamingEnabled()
func (l *library) GpmSetStreamingEnabled(device Device, state uint32) Return {
	return device.GpmSetStreamingEnabled(state)
}

func (device nvmlDevice) GpmSetStreamingEnabled(state uint32) Return {
	return nvmlGpmSetStreamingEnabled(device, state)
}

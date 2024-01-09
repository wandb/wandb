//go:build linux && !libwandb_core

package monitor

import (
	"fmt"
	"strings"
	"sync"

	"github.com/shirou/gopsutil/v3/process"

	"github.com/NVIDIA/go-nvml/pkg/nvml"

	"github.com/wandb/wandb/core/pkg/service"
)

type GPUNvidia struct {
	name                   string
	Metrics                map[string][]float64
	settings               *service.Settings
	mutex                  sync.RWMutex
	nvmlInit               nvml.Return
	DeviceGetCount         func() (int, nvml.Return)
	DeviceGetHandleByIndex func(int) (Device, nvml.Return)
}

func NewGPUNvidia(settings *service.Settings) *GPUNvidia {
	gpu := &GPUNvidia{
		name:     "gpu",
		Metrics:  map[string][]float64{},
		settings: settings,
	}

	gpu.DeviceGetCount = nvml.DeviceGetCount
	gpu.DeviceGetHandleByIndex = func(index int) (Device, nvml.Return) {
		device, ret := nvml.DeviceGetHandleByIndex(index)
		return Device(device), ret
	}

	return gpu
}

func (g *GPUNvidia) Name() string { return g.name }

type Device interface {
	GetComputeRunningProcesses() ([]nvml.ProcessInfo, nvml.Return)
	GetGraphicsRunningProcesses() ([]nvml.ProcessInfo, nvml.Return)
	GetName() (string, nvml.Return)
	GetMemoryInfo() (nvml.Memory, nvml.Return)
	GetUtilizationRates() (nvml.Utilization, nvml.Return)
	GetPowerUsage() (uint32, nvml.Return)
	GetTemperature(nvml.TemperatureSensors) (uint32, nvml.Return)
	GetEnforcedPowerLimit() (uint32, nvml.Return)
}

func (g *GPUNvidia) gpuInUseByProcess(device Device) bool {
	pid := int32(g.settings.GetXStatsPid().GetValue())

	proc, err := process.NewProcess(pid)
	if err != nil {
		// user process does not exist
		return false
	}

	ourPids := make(map[int32]struct{})
	// add user process pid
	ourPids[pid] = struct{}{}

	// find user process's children
	childProcs, err := proc.Children()
	if err == nil {
		for _, childProc := range childProcs {
			ourPids[childProc.Pid] = struct{}{}
		}
	}

	computeProcesses, ret := device.GetComputeRunningProcesses()
	if ret != nvml.SUCCESS {
		return false
	}
	graphicsProcesses, ret := device.GetGraphicsRunningProcesses()
	if ret != nvml.SUCCESS {
		return false
	}
	pidsUsingDevice := make(map[int32]struct{})
	for _, p := range computeProcesses {
		pidsUsingDevice[int32(p.Pid)] = struct{}{}
	}
	for _, p := range graphicsProcesses {
		pidsUsingDevice[int32(p.Pid)] = struct{}{}
	}

	intersectionCount := 0
	for pid := range pidsUsingDevice {
		if _, exists := ourPids[pid]; exists {
			intersectionCount++
		}
	}

	return intersectionCount > 0
}

func (g *GPUNvidia) SampleMetrics() {
	g.mutex.RLock()
	defer g.mutex.RUnlock()

	// we would only call this method if NVML is available
	if g.nvmlInit != nvml.SUCCESS {
		return
	}

	count, ret := g.DeviceGetCount()
	if ret != nvml.SUCCESS {
		return
	}

	for di := 0; di < count; di++ {
		device, ret := g.DeviceGetHandleByIndex(di)
		if ret != nvml.SUCCESS {
			return
		}

		// gpu in use by process?
		gpuInUseByProcess := g.gpuInUseByProcess(device)

		// device utilization
		utilization, ret := device.GetUtilizationRates()
		if ret == nvml.SUCCESS {
			// gpu utilization rate
			key := fmt.Sprintf("gpu.%d.gpu", di)
			g.Metrics[key] = append(
				g.Metrics[key],
				float64(utilization.Gpu),
			)
			// gpu utilization rate (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.gpu", di)
				g.Metrics[keyProc] = append(g.Metrics[keyProc], g.Metrics[key][len(g.Metrics[key])-1])
			}

			// memory utilization rate
			key = fmt.Sprintf("gpu.%d.memory", di)
			g.Metrics[key] = append(
				g.Metrics[key],
				float64(utilization.Memory),
			)
			// memory utilization rate (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.memory", di)
				g.Metrics[keyProc] = append(g.Metrics[keyProc], g.Metrics[key][len(g.Metrics[key])-1])
			}
		}

		memoryInfo, ret := device.GetMemoryInfo()
		if ret == nvml.SUCCESS {
			// memory allocated
			key := fmt.Sprintf("gpu.%d.memoryAllocated", di)
			g.Metrics[key] = append(
				g.Metrics[key],
				float64(memoryInfo.Used)/float64(memoryInfo.Total)*100,
			)
			// memory allocated (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.memoryAllocated", di)
				g.Metrics[keyProc] = append(g.Metrics[keyProc], g.Metrics[key][len(g.Metrics[key])-1])
			}

			// memory allocated (bytes)
			key = fmt.Sprintf("gpu.%d.memoryAllocatedBytes", di)
			g.Metrics[key] = append(
				g.Metrics[key],
				float64(memoryInfo.Used),
			)
			// memory allocated (bytes) (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.memoryAllocatedBytes", di)
				g.Metrics[keyProc] = append(g.Metrics[keyProc], g.Metrics[key][len(g.Metrics[key])-1])
			}
		}

		temperature, ret := device.GetTemperature(nvml.TEMPERATURE_GPU)
		if ret == nvml.SUCCESS {
			// gpu temperature
			key := fmt.Sprintf("gpu.%d.temp", di)
			g.Metrics[key] = append(
				g.Metrics[key],
				float64(temperature),
			)
			// gpu temperature (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.temp", di)
				g.Metrics[keyProc] = append(g.Metrics[keyProc], g.Metrics[key][len(g.Metrics[key])-1])
			}
		}

		// gpu power usage (W)
		powerUsage, ret := device.GetPowerUsage()
		if ret != nvml.SUCCESS {
			return
		}
		key := fmt.Sprintf("gpu.%d.powerWatts", di)
		g.Metrics[key] = append(
			g.Metrics[key],
			float64(powerUsage)/1000,
		)
		// gpu power usage (W) (if in use by process)
		if gpuInUseByProcess {
			keyProc := fmt.Sprintf("gpu.process.%d.powerWatts", di)
			g.Metrics[keyProc] = append(g.Metrics[keyProc], g.Metrics[key][len(g.Metrics[key])-1])
		}

		// gpu power limit (W)
		powerLimit, ret := device.GetEnforcedPowerLimit()
		if ret != nvml.SUCCESS {
			return
		}
		key = fmt.Sprintf("gpu.%d.enforcedPowerLimitWatts", di)
		g.Metrics[key] = append(
			g.Metrics[key],
			float64(powerLimit)/1000,
		)
		// gpu power limit (W) (if in use by process)
		if gpuInUseByProcess {
			keyProc := fmt.Sprintf("gpu.process.%d.enforcedPowerLimitWatts", di)
			g.Metrics[keyProc] = append(g.Metrics[keyProc], g.Metrics[key][len(g.Metrics[key])-1])
		}

		// gpu power usage (%)
		key = fmt.Sprintf("gpu.%d.powerPercent", di)
		g.Metrics[key] = append(
			g.Metrics[key],
			float64(powerUsage)/float64(powerLimit)*100,
		)
		// gpu power usage (%) (if in use by process)
		if gpuInUseByProcess {
			keyProc := fmt.Sprintf("gpu.process.%d.powerPercent", di)
			g.Metrics[keyProc] = append(g.Metrics[keyProc], g.Metrics[key][len(g.Metrics[key])-1])
		}
	}
}

func (g *GPUNvidia) AggregateMetrics() map[string]float64 {
	g.mutex.RLock()
	defer g.mutex.RUnlock()

	aggregates := make(map[string]float64)
	for metric, samples := range g.Metrics {
		if len(samples) > 0 {
			aggregates[metric] = Average(samples)
		}
	}
	return aggregates
}

func (g *GPUNvidia) ClearMetrics() {
	g.mutex.RLock()
	defer g.mutex.RUnlock()

	g.Metrics = map[string][]float64{}
}

func (g *GPUNvidia) IsAvailable() bool {
	defer func() {
		if r := recover(); r != nil {
			g.nvmlInit = nvml.ERROR_UNINITIALIZED
		}
	}()
	g.nvmlInit = nvml.Init()
	return g.nvmlInit == nvml.SUCCESS
}

func (g *GPUNvidia) Close() {
	nvml.Shutdown()
}

func (g *GPUNvidia) Probe() *service.MetadataRequest {
	if g.nvmlInit != nvml.SUCCESS {
		return nil
	}

	info := service.MetadataRequest{
		GpuNvidia: []*service.GpuNvidiaInfo{},
	}

	count, ret := g.DeviceGetCount()
	if ret != nvml.SUCCESS {
		return nil
	}

	info.GpuCount = uint32(count)
	names := make([]string, count)

	for di := 0; di < count; di++ {
		device, ret := g.DeviceGetHandleByIndex(di)
		gpuInfo := &service.GpuNvidiaInfo{}
		if ret == nvml.SUCCESS {
			name, ret := device.GetName()
			if ret == nvml.SUCCESS {
				gpuInfo.Name = name
				names[di] = name
			}
			memoryInfo, ret := device.GetMemoryInfo()
			if ret == nvml.SUCCESS {
				gpuInfo.MemoryTotal = memoryInfo.Total
			}
		}
		info.GpuNvidia = append(info.GpuNvidia, gpuInfo)
	}

	info.GpuType = "[" + strings.Join(names, ", ") + "]"

	return &info
}

//go:build linux && !libwandb_core

package monitor

import (
	"fmt"
	"strings"
	"sync"

	"github.com/shirou/gopsutil/v4/process"

	"github.com/NVIDIA/go-nvml/pkg/nvml"

	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/pkg/service"
)

type GPUNvidia struct {
	name     string
	metrics  map[string][]float64
	settings *settings.Settings
	mutex    sync.RWMutex
	nvmlInit nvml.Return
}

func NewGPUNvidia(settings *settings.Settings) *GPUNvidia {
	gpu := &GPUNvidia{
		name:     "gpu",
		metrics:  map[string][]float64{},
		settings: settings,
	}

	return gpu
}

func (g *GPUNvidia) Name() string { return g.name }

func (g *GPUNvidia) gpuInUseByProcess(device nvml.Device) bool {
	pid := int32(g.settings.GetXStatsPid())

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
	g.mutex.Lock()
	defer g.mutex.Unlock()

	// we would only call this method if NVML is available
	if g.nvmlInit != nvml.SUCCESS {
		return
	}

	count, ret := nvml.DeviceGetCount()
	if ret != nvml.SUCCESS {
		return
	}

	for di := 0; di < count; di++ {
		device, ret := nvml.DeviceGetHandleByIndex(di)
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
			g.metrics[key] = append(
				g.metrics[key],
				float64(utilization.Gpu),
			)
			// gpu utilization rate (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.gpu", di)
				g.metrics[keyProc] = append(g.metrics[keyProc], g.metrics[key][len(g.metrics[key])-1])
			}

			// memory utilization rate
			key = fmt.Sprintf("gpu.%d.memory", di)
			g.metrics[key] = append(
				g.metrics[key],
				float64(utilization.Memory),
			)
			// memory utilization rate (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.memory", di)
				g.metrics[keyProc] = append(g.metrics[keyProc], g.metrics[key][len(g.metrics[key])-1])
			}
		}

		memoryInfo, ret := device.GetMemoryInfo()
		if ret == nvml.SUCCESS {
			// memory allocated
			key := fmt.Sprintf("gpu.%d.memoryAllocated", di)
			g.metrics[key] = append(
				g.metrics[key],
				float64(memoryInfo.Used)/float64(memoryInfo.Total)*100,
			)
			// memory allocated (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.memoryAllocated", di)
				g.metrics[keyProc] = append(g.metrics[keyProc], g.metrics[key][len(g.metrics[key])-1])
			}

			// memory allocated (bytes)
			key = fmt.Sprintf("gpu.%d.memoryAllocatedBytes", di)
			g.metrics[key] = append(
				g.metrics[key],
				float64(memoryInfo.Used),
			)
			// memory allocated (bytes) (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.memoryAllocatedBytes", di)
				g.metrics[keyProc] = append(g.metrics[keyProc], g.metrics[key][len(g.metrics[key])-1])
			}
		}

		temperature, ret := device.GetTemperature(nvml.TEMPERATURE_GPU)
		if ret == nvml.SUCCESS {
			// gpu temperature
			key := fmt.Sprintf("gpu.%d.temp", di)
			g.metrics[key] = append(
				g.metrics[key],
				float64(temperature),
			)
			// gpu temperature (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.temp", di)
				g.metrics[keyProc] = append(g.metrics[keyProc], g.metrics[key][len(g.metrics[key])-1])
			}
		}

		// gpu power usage (W)
		powerUsage, ret := device.GetPowerUsage()
		if ret != nvml.SUCCESS {
			return
		}
		key := fmt.Sprintf("gpu.%d.powerWatts", di)
		g.metrics[key] = append(
			g.metrics[key],
			float64(powerUsage)/1000,
		)
		// gpu power usage (W) (if in use by process)
		if gpuInUseByProcess {
			keyProc := fmt.Sprintf("gpu.process.%d.powerWatts", di)
			g.metrics[keyProc] = append(g.metrics[keyProc], g.metrics[key][len(g.metrics[key])-1])
		}

		// gpu power limit (W)
		powerLimit, ret := device.GetEnforcedPowerLimit()
		if ret != nvml.SUCCESS {
			return
		}
		key = fmt.Sprintf("gpu.%d.enforcedPowerLimitWatts", di)
		g.metrics[key] = append(
			g.metrics[key],
			float64(powerLimit)/1000,
		)
		// gpu power limit (W) (if in use by process)
		if gpuInUseByProcess {
			keyProc := fmt.Sprintf("gpu.process.%d.enforcedPowerLimitWatts", di)
			g.metrics[keyProc] = append(g.metrics[keyProc], g.metrics[key][len(g.metrics[key])-1])
		}

		// gpu power usage (%)
		key = fmt.Sprintf("gpu.%d.powerPercent", di)
		g.metrics[key] = append(
			g.metrics[key],
			float64(powerUsage)/float64(powerLimit)*100,
		)
		// gpu power usage (%) (if in use by process)
		if gpuInUseByProcess {
			keyProc := fmt.Sprintf("gpu.process.%d.powerPercent", di)
			g.metrics[keyProc] = append(g.metrics[keyProc], g.metrics[key][len(g.metrics[key])-1])
		}
	}
}

func (g *GPUNvidia) AggregateMetrics() map[string]float64 {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	aggregates := make(map[string]float64)
	for metric, samples := range g.metrics {
		if len(samples) > 0 {
			aggregates[metric] = Average(samples)
		}
	}
	return aggregates
}

func (g *GPUNvidia) ClearMetrics() {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	g.metrics = map[string][]float64{}
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
	err := nvml.Shutdown()
	if err != nvml.SUCCESS {
		return
	}
}

func (g *GPUNvidia) Probe() *service.MetadataRequest {
	if g.nvmlInit != nvml.SUCCESS {
		return nil
	}

	info := service.MetadataRequest{
		GpuNvidia: []*service.GpuNvidiaInfo{},
	}

	count, ret := nvml.DeviceGetCount()
	if ret != nvml.SUCCESS {
		return nil
	}

	info.GpuCount = uint32(count)
	names := make([]string, count)

	for di := 0; di < count; di++ {
		device, ret := nvml.DeviceGetHandleByIndex(di)
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

//go:build linux && amd64

package monitor

import (
	"fmt"
	"github.com/shirou/gopsutil/v3/process"
	"sync"
	"time"

	"github.com/NVIDIA/go-nvml/pkg/nvml"

	"github.com/wandb/wandb/nexus/pkg/service"
)

type GPUNvidia struct {
	name     string
	metrics  map[string][]float64
	settings *service.Settings
	mutex    sync.RWMutex
	nvmlInit nvml.Return
}

func NewGPUNvidia(settings *service.Settings) *GPUNvidia {
	gpu := &GPUNvidia{
		name:     "gpu",
		metrics:  map[string][]float64{},
		settings: settings,
	}

	return gpu
}

func (g *GPUNvidia) Name() string { return g.name }

func (g *GPUNvidia) gpuInUseByProcess(device nvml.Device) bool {
	pid := int32(g.settings.XStatsPid.GetValue())

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
	g.mutex.RLock()
	defer g.mutex.RUnlock()

	aggregates := make(map[string]float64)
	for metric, samples := range g.metrics {
		if len(samples) > 0 {
			aggregates[metric] = Average(samples)
		}
	}
	return aggregates
}

func (g *GPUNvidia) ClearMetrics() {
	g.mutex.RLock()
	defer g.mutex.RUnlock()

	g.metrics = map[string][]float64{}
}

func (g *GPUNvidia) IsAvailable() bool {
	start := time.Now()
	g.nvmlInit = nvml.Init()
	elapsed := time.Since(start)
	fmt.Println("nvml.Init() took", elapsed)

	if g.nvmlInit == nvml.SUCCESS {
		return true
	}
	return false
}

func (g *GPUNvidia) Close() {
	start := time.Now()
	ret := nvml.Shutdown()
	elapsed := time.Since(start)
	fmt.Println("nvml.Shutdown() took", elapsed)
	if ret != nvml.SUCCESS {
		return
	}
	fmt.Println("nvml.Shutdown() successful")
}

func (g *GPUNvidia) Probe() map[string]map[string]interface{} {
	info := make(map[string]map[string]interface{})
	// todo: add GPU info
	return info
}

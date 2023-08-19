//go:build linux && amd64

package monitor

import (
	"fmt"
	"log"
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

func (g *GPUNvidia) SampleMetrics() {
	g.mutex.RLock()
	defer g.mutex.RUnlock()

	// we would only call this method if nvml is available
	if g.nvmlInit != nvml.SUCCESS {
		return
	}

	start := time.Now()
	count, ret := nvml.DeviceGetCount()
	elapsed := time.Since(start)
	fmt.Println("nvml.DeviceGetCount() took", elapsed)
	if ret != nvml.SUCCESS {
		log.Fatalf("Unable to get device count: %v", nvml.ErrorString(ret))
	}

	start = time.Now()
	for di := 0; di < count; di++ {
		device, ret := nvml.DeviceGetHandleByIndex(di)
		if ret != nvml.SUCCESS {
			log.Fatalf("Unable to get device at index %d: %v", di, nvml.ErrorString(ret))
		}

		start = time.Now()
		processInfos, ret := device.GetComputeRunningProcesses()
		elapsed = time.Since(start)
		fmt.Println("nvml.DeviceGetComputeRunningProcesses() took", elapsed)
		if ret != nvml.SUCCESS {
			log.Fatalf("Unable to get process info for device at index %d: %v", di, nvml.ErrorString(ret))
		}
		fmt.Printf("Found %d processes on device %d\n", len(processInfos), di)
		for pi, processInfo := range processInfos {
			fmt.Printf("\t[%2d] ProcessInfo: %+v\n", pi, processInfo)
		}

		// device utilization
		start = time.Now()
		utilization, ret := device.GetUtilizationRates()
		elapsed = time.Since(start)
		fmt.Println("nvml.DeviceGetUtilizationRates() took", elapsed)
		if ret != nvml.SUCCESS {
			log.Fatalf("Unable to get utilization for device at index %d: %v", di, nvml.ErrorString(ret))
		}
		// gpu utilization rate
		key := fmt.Sprintf("gpu.%d.gpu", di)
		g.metrics[key] = append(
			g.metrics[key],
			float64(utilization.Gpu),
		)
		// memory utilization rate
		if ret != nvml.SUCCESS {
			log.Fatalf("Unable to get memory info for device at index %d: %v", di, nvml.ErrorString(ret))
		}
		key = fmt.Sprintf("gpu.%d.memory", di)
		g.metrics[key] = append(
			g.metrics[key],
			float64(utilization.Memory),
		)

		// memory allocated
		memoryInfo, ret := device.GetMemoryInfo()
		if ret != nvml.SUCCESS {
			log.Fatalf("Unable to get memory info for device at index %d: %v", di, nvml.ErrorString(ret))
		}
		key = fmt.Sprintf("gpu.%d.memoryAllocated", di)
		g.metrics[key] = append(
			g.metrics[key],
			float64(memoryInfo.Used)/float64(memoryInfo.Total)*100,
		)
		// memory allocated (bytes)
		key = fmt.Sprintf("gpu.%d.memoryAllocatedBytes", di)
		g.metrics[key] = append(
			g.metrics[key],
			float64(memoryInfo.Used),
		)

		// gpu temperature
		temperature, ret := device.GetTemperature(nvml.TEMPERATURE_GPU)
		if ret != nvml.SUCCESS {
			log.Fatalf("Unable to get temperature for device at index %d: %v", di, nvml.ErrorString(ret))
		}
		key = fmt.Sprintf("gpu.%d.temp", di)
		g.metrics[key] = append(
			g.metrics[key],
			float64(temperature),
		)

		// gpu power usage (W)
		powerUsage, ret := device.GetPowerUsage()
		if ret != nvml.SUCCESS {
			log.Fatalf("Unable to get power usage for device at index %d: %v", di, nvml.ErrorString(ret))
		}
		key = fmt.Sprintf("gpu.%d.powerWatts", di)
		g.metrics[key] = append(
			g.metrics[key],
			float64(powerUsage)/1000,
		)

		// gpu power limit (W)
		powerLimit, ret := device.GetEnforcedPowerLimit()
		if ret != nvml.SUCCESS {
			log.Fatalf("Unable to get power limit for device at index %d: %v", di, nvml.ErrorString(ret))
		}
		key = fmt.Sprintf("gpu.%d.powerLimitWatts", di)
		g.metrics[key] = append(
			g.metrics[key],
			float64(powerLimit)/1000,
		)

		// gpu power usage (%)
		key = fmt.Sprintf("gpu.%d.powerPercent", di)
		g.metrics[key] = append(
			g.metrics[key],
			float64(powerUsage)/float64(powerLimit)*100,
		)
	}
	elapsed = time.Since(start)
	fmt.Println("nvml.DeviceGetHandleByIndex() took", elapsed)
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

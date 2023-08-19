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
	c.mutex.RLock()
	defer c.mutex.RUnlock()

	// we would only call this method if nvml is available
	if g.nvmlInit == nil {
		return
	}

	start := time.Now()
	ret := nvml.Init()
	elapsed := time.Since(start)
	fmt.Println("nvml.Init() took", elapsed)
	if ret != nvml.SUCCESS {
		log.Fatalf("Unable to initialize NVML: %v", nvml.ErrorString(ret))
	}
	//defer func() {
	//	start = time.Now()
	//	ret := nvml.Shutdown()
	//	elapsed = time.Since(start)
	//	fmt.Println("nvml.Shutdown() took", elapsed)
	//	if ret != nvml.SUCCESS {
	//		log.Fatalf("Unable to shut down NVML: %v", nvml.ErrorString(ret))
	//	}
	//}()

	start = time.Now()
	count, ret := nvml.DeviceGetCount()
	elapsed = time.Since(start)
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

		processInfos, ret := device.GetComputeRunningProcesses()
		if ret != nvml.SUCCESS {
			log.Fatalf("Unable to get process info for device at index %d: %v", di, nvml.ErrorString(ret))
		}
		fmt.Printf("Found %d processes on device %d\n", len(processInfos), di)
		for pi, processInfo := range processInfos {
			fmt.Printf("\t[%2d] ProcessInfo: %+v\n", pi, processInfo)
		}
	}
	elapsed = time.Since(start)
	fmt.Println("nvml.DeviceGetHandleByIndex() took", elapsed)
}

func (g *GPUNvidia) AggregateMetrics() map[string]float64 {
	c.mutex.RLock()
	defer c.mutex.RUnlock()

	aggregates := make(map[string]float64)
	for metric, samples := range c.metrics {
		if len(samples) > 0 {
			aggregates[metric] = Average(samples)
		}
	}
	return aggregates
}

func (g *GPUNvidia) ClearMetrics() {
	c.mutex.RLock()
	defer c.mutex.RUnlock()

	c.metrics = map[string][]float64{}
}

func (g *GPUNvidia) IsAvailable() bool {
	g.nvmlInit = nvml.Init()

	if g.nvmlInit == nvml.SUCCESS {
		return true
	}
	return false
}

func (g *GPUNvidia) Close() {
	ret := nvml.Shutdown()
	if ret != nvml.SUCCESS {
		// log.Debug("Unable to shut down NVML: %v", nvml.ErrorString(ret))
	}
}

func (g *GPUNvidia) Probe() map[string]map[string]interface{} {
	info := make(map[string]map[string]interface{})
	// todo: add GPU info
	return info
}

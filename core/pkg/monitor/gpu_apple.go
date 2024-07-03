package monitor

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sync"

	"github.com/wandb/segmentio-encoding/json"
	"github.com/wandb/wandb/core/pkg/service"
)

func getExecPath() (string, error) {
	ex, err := os.Executable()
	if err != nil {
		return "", err
	}
	exDirPath := filepath.Dir(ex)
	exPath := filepath.Join(exDirPath, "apple_gpu_stats")

	if _, err := os.Stat(exPath); os.IsNotExist(err) {
		return "", err
	}
	return exPath, nil
}

type GPUApple struct {
	name        string
	metrics     map[string][]float64
	mutex       sync.RWMutex
	settings    *service.Settings
	isAvailable bool
	exPath      string
}

func NewGPUApple(settings *service.Settings) *GPUApple {
	gpu := &GPUApple{
		name:     "gpu",
		metrics:  map[string][]float64{},
		settings: settings,
	}

	if exPath, err := getExecPath(); err == nil {
		gpu.isAvailable = true
		gpu.exPath = exPath
	}

	return gpu
}

func (g *GPUApple) parseStats() (map[string]interface{}, error) {
	rawStats, err := exec.Command(g.exPath).Output()
	if err != nil {
		return nil, err
	}
	stats := make(map[string]interface{})
	err = json.Unmarshal(rawStats, &stats)
	if err != nil {
		return nil, err
	}
	return stats, nil
}

func (g *GPUApple) Name() string { return g.name }

//gocyclo:ignore
func (g *GPUApple) SampleMetrics() {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	stats, err := g.parseStats()
	if err != nil {
		return
	}
	// TODO: add more metrics to g.metrics,
	//  such as render or tiler utilization

	// GPU + Neural Engine Total Power (W)
	if powerUsage, ok := stats["gpuPower"]; ok {
		key := fmt.Sprintf("gpu.%d.powerWatts", 0)
		g.metrics[key] = append(
			g.metrics[key],
			powerUsage.(float64),
		)
	}

	// System Power (W)
	if systemPower, ok := stats["systemPower"]; ok {
		key := "system.powerWatts"
		g.metrics[key] = append(
			g.metrics[key],
			systemPower.(float64),
		)
	}

	// recover count
	if recoveryCount, ok := stats["recoveryCount"]; ok {
		key := "gpu.0.recoveryCount"
		g.metrics[key] = append(
			g.metrics[key],
			recoveryCount.(float64), // it's an int actually
		)
	}

	// gpu utilization (%)
	if gpuUtilization, ok := stats["utilization"]; ok {
		key := fmt.Sprintf("gpu.%d.gpu", 0)
		g.metrics[key] = append(
			g.metrics[key],
			gpuUtilization.(float64),
		)
	}

	// memory allocated (bytes)
	if allocatedMemory, ok := stats["allocatedSystemMemory"]; ok {
		key := fmt.Sprintf("gpu.%d.memoryAllocatedBytes", 0)
		g.metrics[key] = append(
			g.metrics[key],
			allocatedMemory.(float64),
		)
	}

	// memory in use (bytes)
	if inUseMemory, ok := stats["inUseSystemMemory"]; ok {
		key := fmt.Sprintf("gpu.%d.memoryUsed", 0)
		g.metrics[key] = append(
			g.metrics[key],
			inUseMemory.(float64),
		)
	}

	// temperature (C)
	var nMeasurements int
	var temperature float64

	tempKeys := []string{
		"m1Gpu1",
		"m1Gpu2",
		"m1Gpu3",
		"m1Gpu4",
		"m2Gpu1",
		"m2Gpu2",
		"m3Gpu1",
		"m3Gpu2",
		"m3Gpu3",
		"m3Gpu4",
		"m3Gpu5",
		"m3Gpu6",
		"m3Gpu7",
		"m3Gpu8",
	}

	for _, mXGpuN := range tempKeys {
		if temp, ok := stats[mXGpuN]; ok {
			if temp.(float64) > 0 {
				temperature += temp.(float64)
				nMeasurements++
			}
		}
	}

	if nMeasurements > 0 {
		key := fmt.Sprintf("gpu.%d.temp", 0)
		g.metrics[key] = append(
			g.metrics[key],
			temperature/float64(nMeasurements),
		)
	}
}

func (g *GPUApple) AggregateMetrics() map[string]float64 {
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

func (g *GPUApple) ClearMetrics() {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	clear(g.metrics)
}

func (g *GPUApple) IsAvailable() bool {
	return g.isAvailable
}

func (g *GPUApple) Probe() *service.MetadataRequest {
	if !g.IsAvailable() {
		return nil
	}
	stats, err := g.parseStats()
	if err != nil {
		return nil
	}

	info := service.MetadataRequest{
		GpuApple: &service.GpuAppleInfo{},
	}

	if gpuType, ok := stats["name"]; ok {
		info.GpuApple.GpuType = gpuType.(string)
	}
	if vendor, ok := stats["vendor"]; ok {
		info.GpuApple.Vendor = vendor.(string)
	}
	if cores, ok := stats["cores"]; ok {
		info.GpuApple.Cores = uint32(cores.(float64))
	}

	return &info
}

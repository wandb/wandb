package monitor

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sync"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
	isAvailable bool
	exPath      string
}

func NewGPUApple() *GPUApple {
	gpu := &GPUApple{
		name:    "gpu",
		metrics: map[string][]float64{},
	}

	if exPath, err := getExecPath(); err == nil {
		gpu.isAvailable = true
		gpu.exPath = exPath
	}

	return gpu
}

func (g *GPUApple) parseStats() (map[string]any, error) {
	rawStats, err := exec.Command(g.exPath).Output()
	if err != nil {
		return nil, err
	}

	var stats map[string]any
	err = json.Unmarshal(rawStats, &stats)
	if err != nil {
		return nil, err
	}

	return stats, nil
}

func (g *GPUApple) Name() string { return g.name }

//gocyclo:ignore
func (g *GPUApple) SampleMetrics() error {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	stats, err := g.parseStats()
	if err != nil {
		return err
	}
	// TODO: add more metrics to g.metrics,
	//  such as render or tiler utilization

	// GPU + Neural Engine Total Power (W)
	if powerUsage, ok := queryMapNumber(stats, "gpuPower"); ok {
		key := fmt.Sprintf("gpu.%d.powerWatts", 0)
		g.metrics[key] = append(g.metrics[key], powerUsage)
	}

	// System Power (W)
	if systemPower, ok := queryMapNumber(stats, "systemPower"); ok {
		key := "system.powerWatts"
		g.metrics[key] = append(g.metrics[key], systemPower)
	}

	// recover count
	if recoveryCount, ok := queryMapNumber(stats, "recoveryCount"); ok {
		key := "gpu.0.recoveryCount"
		g.metrics[key] = append(g.metrics[key], recoveryCount)
	}

	// gpu utilization (%)
	if gpuUtilization, ok := queryMapNumber(stats, "utilization"); ok {
		key := fmt.Sprintf("gpu.%d.gpu", 0)
		g.metrics[key] = append(g.metrics[key], gpuUtilization)
	}

	// memory allocated (bytes)
	if allocatedMemory, ok := queryMapNumber(stats, "allocatedSystemMemory"); ok {
		key := fmt.Sprintf("gpu.%d.memoryAllocatedBytes", 0)
		g.metrics[key] = append(g.metrics[key], allocatedMemory)
	}

	// memory in use (bytes)
	if inUseMemory, ok := queryMapNumber(stats, "inUseSystemMemory"); ok {
		key := fmt.Sprintf("gpu.%d.memoryUsed", 0)
		g.metrics[key] = append(g.metrics[key], inUseMemory)
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
		if temp, ok := queryMapNumber(stats, mXGpuN); ok {
			if temp > 0 {
				temperature += temp
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

	return nil
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

func (g *GPUApple) Probe() *spb.MetadataRequest {
	if !g.IsAvailable() {
		return nil
	}
	stats, err := g.parseStats()
	if err != nil {
		return nil
	}

	info := spb.MetadataRequest{
		GpuApple: &spb.GpuAppleInfo{},
	}

	if gpuType, ok := queryMapString(stats, "name"); ok {
		info.GpuApple.GpuType = gpuType
	}
	if vendor, ok := queryMapString(stats, "vendor"); ok {
		info.GpuApple.Vendor = vendor
	}
	if cores, ok := queryMapNumber(stats, "cores"); ok {
		info.GpuApple.Cores = uint32(cores)
	}

	return &info
}

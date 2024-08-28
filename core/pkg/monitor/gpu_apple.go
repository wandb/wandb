package monitor

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

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
	isAvailable bool
	exPath      string
}

func NewGPUApple() *GPUApple {
	gpu := &GPUApple{name: "gpu"}

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
func (g *GPUApple) Sample() (map[string]any, error) {
	stats, err := g.parseStats()
	if err != nil {
		return nil, err
	}
	// TODO: add more metrics, such as render or tiler utilization

	metrics := make(map[string]any)

	// GPU + Neural Engine Total Power (W)
	if powerUsage, ok := queryMapNumber(stats, "gpuPower"); ok {
		metrics[fmt.Sprintf("gpu.%d.powerWatts", 0)] = powerUsage
	}

	// System Power (W)
	if systemPower, ok := queryMapNumber(stats, "systemPower"); ok {
		metrics["system.powerWatts"] = systemPower
	}

	// recover count
	if recoveryCount, ok := queryMapNumber(stats, "recoveryCount"); ok {
		metrics["gpu.0.recoveryCount"] = recoveryCount
	}

	// gpu utilization (%)
	if gpuUtilization, ok := queryMapNumber(stats, "utilization"); ok {
		metrics["gpu.0.gpu"] = gpuUtilization
	}

	// memory allocated (bytes)
	if allocatedMemory, ok := queryMapNumber(stats, "allocatedSystemMemory"); ok {
		metrics["gpu.0.memoryAllocatedBytes"] = allocatedMemory
	}

	// memory in use (bytes)
	if inUseMemory, ok := queryMapNumber(stats, "inUseSystemMemory"); ok {
		metrics["gpu.0.memoryUsed"] = inUseMemory
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
		metrics["gpu.%d.temp"] = temperature / float64(nMeasurements)
	}

	return metrics, nil
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

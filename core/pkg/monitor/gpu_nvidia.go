//go:build linux && !libwandb_core

package monitor

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sync"

	"github.com/wandb/wandb/core/pkg/service"
)

func getExecPath() (string, error) {
	ex, err := os.Executable()
	if err != nil {
		return "", err
	}
	exDirPath := filepath.Dir(ex)
	exPath := filepath.Join(exDirPath, "nvidia_gpu_stats")

	if _, err := os.Stat(exPath); os.IsNotExist(err) {
		return "", err
	}
	return exPath, nil
}

type GPUNvidia struct {
	name     string
	metrics  map[string][]float64
	settings *service.Settings
	mutex    sync.RWMutex
	cmd      *exec.Cmd
}

func NewGPUNvidia(settings *service.Settings) *GPUNvidia {
	gpu := &GPUNvidia{
		name:     "gpu",
		metrics:  map[string][]float64{},
		settings: settings,
	}

	if exPath, err := getExecPath(); err != nil {
		return gpu
	}

	// Define the command and its arguments
	samplingInterval := defaultSamplingInterval.Seconds()
	if settings.XStatsSampleRateSeconds.GetValue() > 0 {
		samplingInterval = settings.XStatsSampleRateSeconds.GetValue()
	}

	cmd := exec.Command(
		exPath,
		fmt.Sprintf("-s=%fs", samplingInterval),
		fmt.Sprintf("-pid=%d", g.settings.XStatsPid.GetValue()),
	)

	// Get a pipe to read from the command's stdout
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return
	}

	// Start the command
	if err := cmd.Start(); err != nil {
		return
	}

	// Start goroutine to read and process output
	go func() {
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			line := scanner.Text()

			// Try to parse the line as JSON
			var data map[string]interface{}
			if err := json.Unmarshal([]byte(line), &data); err != nil {
				fmt.Printf("Error parsing JSON: %v\n", err)
				continue
			}

			// Process the JSON data
			fmt.Printf("Received JSON: %+v\n", data)
		}

		if err := scanner.Err(); err != nil {
			fmt.Printf("Error reading stdout: %v\n", err)
		}
	}()

	return gpu
}

func (g *GPUNvidia) Name() string { return g.name }

func (g *GPUNvidia) SampleMetrics() {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	g.metrics = map[string][]float64{}
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
	// TODO: fixme
	return true
}

func (g *GPUNvidia) Close() {
	// semd signal to close
	if g.cmd != nil {
		g.cmd.Process.Signal(os.Interrupt)
	}
}

func (g *GPUNvidia) Probe() *service.MetadataRequest {
	info := service.MetadataRequest{
		GpuNvidia: []*service.GpuNvidiaInfo{},
	}

	// count, ret := nvml.DeviceGetCount()
	// if ret != nvml.SUCCESS {
	// 	return nil
	// }

	// info.GpuCount = uint32(count)
	// names := make([]string, count)

	// for di := 0; di < count; di++ {
	// 	device, ret := nvml.DeviceGetHandleByIndex(di)
	// 	gpuInfo := &service.GpuNvidiaInfo{}
	// 	if ret == nvml.SUCCESS {
	// 		name, ret := device.GetName()
	// 		if ret == nvml.SUCCESS {
	// 			gpuInfo.Name = name
	// 			names[di] = name
	// 		}
	// 		memoryInfo, ret := device.GetMemoryInfo()
	// 		if ret == nvml.SUCCESS {
	// 			gpuInfo.MemoryTotal = memoryInfo.Total
	// 		}
	// 	}
	// 	info.GpuNvidia = append(info.GpuNvidia, gpuInfo)
	// }

	// info.GpuType = "[" + strings.Join(names, ", ") + "]"

	return &info
}

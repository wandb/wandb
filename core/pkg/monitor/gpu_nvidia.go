//go:build linux && !libwandb_core

package monitor

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"

	"github.com/wandb/wandb/core/pkg/service"
)

func getCmdPath() (string, error) {
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

func isRunning(cmd *exec.Cmd) bool {
	if cmd.Process == nil {
		return false
	}

	process, err := os.FindProcess(cmd.Process.Pid)
	if err != nil {
		return false
	}

	err = process.Signal(syscall.Signal(0))
	return err == nil
}

type GPUNvidia struct {
	name     string
	sample   map[string]any
	metrics  map[string][]any
	settings *service.Settings
	mutex    sync.RWMutex
	cmd      *exec.Cmd
}

func NewGPUNvidia(settings *service.Settings) *GPUNvidia {
	gpu := &GPUNvidia{
		name:     "gpu",
		sample:   map[string]any{},
		metrics:  map[string][]any{},
		settings: settings,
	}

	exPath, err := getCmdPath()
	if err != nil {
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
		fmt.Sprintf("-pid=%d", settings.XStatsPid.GetValue()),
	)
	gpu.cmd = cmd

	// Get a pipe to read from the command's stdout
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return gpu
	}

	// Start the command
	if err := cmd.Start(); err != nil {
		return gpu
	}

	// Start goroutine to read and process output
	go func() {
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			line := scanner.Text()

			// Try to parse the line as JSON
			var data map[string]any
			if err := json.Unmarshal([]byte(line), &data); err != nil {
				continue
			}

			// Process the JSON data
			gpu.mutex.Lock()
			for key, value := range data {
				gpu.sample[key] = value
			}
			gpu.mutex.Unlock()
		}

		if err := scanner.Err(); err != nil {
			return
		}
	}()

	return gpu
}

func (g *GPUNvidia) Name() string { return g.name }

func (g *GPUNvidia) SampleMetrics() {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	if !isRunning(g.cmd) {
		return
	}

	// do not sample if the last timestamp is the same
	if len(g.sample) > 0 &&
		len(g.metrics) > 0 &&
		g.sample["_timestamp"] == g.metrics["_timestamp"][len(g.metrics["_timestamp"])-1] {
		return
	}

	for key, value := range g.sample {
		g.metrics[key] = append(g.metrics[key], value)
	}
}

func (g *GPUNvidia) AggregateMetrics() map[string]float64 {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	aggregates := make(map[string]float64)
	for metric, samples := range g.metrics {
		if len(samples) > 0 {
			// can cast to float64? then calculate average and store
			if _, ok := samples[0].(float64); ok {
				floatSamples := make([]float64, len(samples))
				for i, v := range samples {
					floatSamples[i] = v.(float64)
				}
				aggregates[metric] = Average(floatSamples)
			}
		}
	}
	return aggregates
}

func (g *GPUNvidia) ClearMetrics() {
	g.mutex.Lock()
	defer g.mutex.Unlock()

	g.metrics = map[string][]any{}
}

func (g *GPUNvidia) IsAvailable() bool {
	return isRunning(g.cmd)
}

func (g *GPUNvidia) Close() {
	// semd signal to close
	if isRunning(g.cmd) {
		g.cmd.Process.Signal(os.Interrupt)
	}
}

func (g *GPUNvidia) Probe() *service.MetadataRequest {
	if !g.IsAvailable() || len(g.sample) == 0 {
		return nil
	}

	info := service.MetadataRequest{
		GpuNvidia: []*service.GpuNvidiaInfo{},
	}

	// count, ret := nvml.DeviceGetCount()
	// if ret != nvml.SUCCESS {
	// 	return nil
	// }

	if count, ok := g.sample["gpu.count"].(float64); ok {
		info.GpuCount = uint32(count)
	} else {
		return nil
	}

	names := make([]string, info.GpuCount)

	for di := 0; di < int(info.GpuCount); di++ {

		gpuInfo := &service.GpuNvidiaInfo{}
		name := fmt.Sprintf("gpu.%d.name", di)
		if v, ok := g.sample[name]; ok {
			gpuInfo.Name = v.(string)
			names[di] = gpuInfo.Name
		}

		memTotal := fmt.Sprintf("gpu.%d.memoryTotal", di)
		if v, ok := g.sample[memTotal]; ok {
			gpuInfo.MemoryTotal = uint64(v.(float64))
		}

		info.GpuNvidia = append(info.GpuNvidia, gpuInfo)

	}

	info.GpuType = "[" + strings.Join(names, ", ") + "]"

	return &info
}

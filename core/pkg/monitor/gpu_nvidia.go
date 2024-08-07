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
	"time"

	"github.com/wandb/wandb/core/pkg/service"
)

// getCmdPath returns the path to the nvidia_gpu_stats program.
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

// isRunning checks if the command is running by sending a signal to the process
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
	sample   map[string]any   // latest reading from nvidia_gpu_stats command
	metrics  map[string][]any // all readings
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

	samplingInterval := defaultSamplingInterval.Seconds()
	if settings.XStatsSampleRateSeconds.GetValue() > 0 {
		samplingInterval = settings.XStatsSampleRateSeconds.GetValue()
	}

	// we will use nvidia_gpu_stats to get GPU stats
	gpu.cmd = exec.Command(
		exPath,
		// monitor for GPU usage for this pid and its children
		fmt.Sprintf("--pid=%d", settings.XStatsPid.GetValue()),
		// pid of the current process. nvidia_gpu_stats will exit when this process exits
		fmt.Sprintf("--ppid=%d", os.Getpid()),
		// sampling interval in seconds
		fmt.Sprintf("--interval=%f", samplingInterval),
	)

	// get a pipe to read from the command's stdout
	stdout, err := gpu.cmd.StdoutPipe()
	if err != nil {
		return gpu
	}

	if err := gpu.cmd.Start(); err != nil {
		return gpu
	}

	// read and process nvidia_gpu_stats output in a separate goroutine.
	// nvidia_gpu_stats outputs JSON data for each GPU every sampling interval.
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
	currentTimestamp, ok := g.sample["_timestamp"]
	if !ok {
		return
	}
	lastTimestamps, ok := g.metrics["_timestamp"]
	if ok && len(lastTimestamps) > 0 && lastTimestamps[len(lastTimestamps)-1] == currentTimestamp {
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
		// skip metrics that start with "_", some of which are internal metrics
		// TODO: other metrics lack aggregation on the frontend; could be added in the future.
		if strings.HasPrefix(metric, "_") {
			continue
		}
		if len(samples) > 0 {
			// can cast to float64? then calculate average and store
			if _, ok := samples[0].(float64); ok {
				floatSamples := make([]float64, len(samples))
				for i, v := range samples {
					if f, ok := v.(float64); ok {
						floatSamples[i] = f
					}
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
	// send signal to close
	if isRunning(g.cmd) {
		if err := g.cmd.Process.Signal(os.Kill); err != nil {
			return
		}
	}
}

func (g *GPUNvidia) Probe() *service.MetadataRequest {
	if !g.IsAvailable() {
		return nil
	}

	// wait for the first sample
	for {
		g.mutex.RLock()
		_, ok := g.sample["_gpu.count"]
		g.mutex.RUnlock()
		if ok {
			break
		}
		// sleep for a while
		time.Sleep(100 * time.Millisecond)
	}

	info := service.MetadataRequest{
		GpuNvidia: []*service.GpuNvidiaInfo{},
	}

	if count, ok := g.sample["_gpu.count"].(float64); ok {
		info.GpuCount = uint32(count)
	} else {
		return nil
	}

	// no GPU found, so close the GPU monitor
	if info.GpuCount == 0 {
		g.Close()
		return nil
	}

	if v, ok := g.sample["cuda_version"]; ok {
		info.CudaVersion = v.(string)
	}

	names := make([]string, info.GpuCount)

	for di := 0; di < int(info.GpuCount); di++ {

		gpuInfo := &service.GpuNvidiaInfo{}
		name := fmt.Sprintf("_gpu.%d.name", di)
		if v, ok := g.sample[name]; ok {
			if v, ok := v.(string); ok {
				gpuInfo.Name = v
				names[di] = gpuInfo.Name
			}
		}

		memTotal := fmt.Sprintf("_gpu.%d.memoryTotal", di)
		if v, ok := g.sample[memTotal]; ok {
			if v, ok := v.(float64); ok {
				gpuInfo.MemoryTotal = uint64(v)
			}
		}

		info.GpuNvidia = append(info.GpuNvidia, gpuInfo)

	}

	info.GpuType = "[" + strings.Join(names, ", ") + "]"

	return &info
}

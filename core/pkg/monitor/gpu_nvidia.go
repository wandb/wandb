//go:build linux

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

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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

// isRunning checks if the command is running by sending a signal to the process.
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

// GPUNvidia monitors NVIDIA GPU stats using the nvidia_gpu_stats command.
type GPUNvidia struct {
	name             string
	sample           map[string]any // latest reading from nvidia_gpu_stats command
	pid              int32          // pid of the process to monitor
	samplingInterval float64        // sampling interval in seconds
	lastTimestamp    float64        // last reported timestamp
	mutex            sync.RWMutex
	cmdPath          string
	cmd              *exec.Cmd
	logger           *observability.CoreLogger
	waitOnce         sync.Once
}

// NewGPUNvidia creates a new GPUNvidia instance configured to monitor NVIDIA GPUs.
//
// If cmdPath is empty, it will use the default nvidia_gpu_stats path.
func NewGPUNvidia(
	logger *observability.CoreLogger,
	pid int32,
	samplingInterval float64,
	cmdPath string,
) *GPUNvidia {
	g := &GPUNvidia{
		name:             "gpu",
		sample:           map[string]any{},
		pid:              pid,
		samplingInterval: samplingInterval,
		logger:           logger,
	}

	if cmdPath == "" {
		var err error
		cmdPath, err = getCmdPath()
		if err != nil {
			return nil
		}
	}
	g.cmdPath = cmdPath

	if samplingInterval == 0 {
		samplingInterval = defaultSamplingInterval.Seconds()
	}

	// We will use nvidia_gpu_stats to get GPU stats.
	g.cmd = exec.Command(
		g.cmdPath,
		// Monitor for GPU usage for this pid and its children.
		fmt.Sprintf("--pid=%d", pid),
		// PID of the current process. nvidia_gpu_stats will exit when this process exits.
		fmt.Sprintf("--ppid=%d", os.Getpid()),
		// Sampling interval in seconds.
		fmt.Sprintf("--interval=%f", samplingInterval),
	)

	// Get a pipe to read from the command's stdout.
	stdout, err := g.cmd.StdoutPipe()
	if err != nil {
		g.logger.CaptureError(
			fmt.Errorf("monitor: %v: error getting stdout pipe: %v for command: %v", g.name, err, g.cmd),
		)
		return nil
	}

	if err := g.cmd.Start(); err != nil {
		g.logger.CaptureError(
			fmt.Errorf("monitor: %v: error starting command %v: %v", g.name, g.cmd, err),
		)
		return nil
	}

	// Read and process nvidia_gpu_stats output in a separate goroutine.
	// nvidia_gpu_stats outputs JSON data for each GPU every sampling interval.
	go func() {
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			line := scanner.Text()

			// Try to parse the line as JSON.
			var data map[string]any
			if err := json.Unmarshal([]byte(line), &data); err != nil {
				g.logger.CaptureError(
					fmt.Errorf("monitor: %v: error parsing JSON %v: %v", g.name, line, err),
				)
				continue
			}

			// Process the JSON data.
			g.mutex.Lock()
			for key, value := range data {
				g.sample[key] = value
			}
			g.mutex.Unlock()
		}

		// If we reach here, the scanner has finished reading from the pipe
		// and the command has exited. We must ensure that the command is waited
		// for to avoid zombie processes.
		g.waitWithTimeout(5 * time.Second)
	}()

	return g
}

// waitWithTimeout waits for the process to exit, but times out after the given duration.
func (g *GPUNvidia) waitWithTimeout(timeout time.Duration) {
	// Channel to receive the result of cmd.Wait()
	done := make(chan error, 1)

	// Wait for the process to exit
	go func() {
		g.waitOnce.Do(func() {
			done <- g.cmd.Wait()
		})
	}()

	select {
	case <-done:
	case <-time.After(timeout):
		// Timeout occurred
		g.logger.CaptureError(fmt.Errorf("monitor: %v: timeout waiting for process to exit", g.name))
	}
}

// Name returns the name of the asset.
func (g *GPUNvidia) Name() string { return g.name }

// Sample returns the latest collected GPU metrics.
func (g *GPUNvidia) Sample() (map[string]any, error) {
	if !isRunning(g.cmd) {
		// Do not log error if the command is not running.
		return nil, nil
	}

	g.mutex.RLock()
	defer g.mutex.RUnlock()

	// Do not sample if the last timestamp is the same.
	currentTimestamp, ok := g.sample["_timestamp"]
	if !ok {
		return nil, nil
	}

	if g.lastTimestamp == currentTimestamp {
		return nil, nil
	}

	ts, ok := currentTimestamp.(float64)
	if !ok {
		return nil, fmt.Errorf("invalid timestamp: %v", currentTimestamp)
	}
	g.lastTimestamp = ts

	metrics := make(map[string]any)

	for metric, value := range g.sample {
		// Skip metrics that start with "_", some of which are internal metrics.
		// TODO: Other metrics lack aggregation on the frontend; could be added in the future.
		if strings.HasPrefix(metric, "_") {
			continue
		}
		if v, ok := value.(float64); ok {
			metrics[metric] = v
		}
	}

	return metrics, nil
}

// IsAvailable checks if the GPUNvidia monitor is available.
func (g *GPUNvidia) IsAvailable() bool {
	if g.cmdPath == "" {
		return false
	}
	return isRunning(g.cmd)
}

// Close terminates the GPUNvidia monitor and cleans up resources.
func (g *GPUNvidia) Close() {
	if !g.IsAvailable() {
		return
	}
	// Send signal to the process to exit.
	_ = g.cmd.Process.Signal(os.Kill)
	// We must ensure that the command is waited for to avoid zombie processes.
	g.waitWithTimeout(5 * time.Second)
}

// Probe gathers metadata about the GPU hardware.
func (g *GPUNvidia) Probe() *spb.MetadataRequest {
	if !g.IsAvailable() {
		return nil
	}

	// Wait for the first sample, but no more than 5 seconds.
	startTime := time.Now()
	for {
		g.mutex.RLock()
		_, ok := g.sample["_gpu.count"]
		g.mutex.RUnlock()
		if ok {
			break // Successfully got a sample.
		}
		if time.Since(startTime) > 5*time.Second {
			// Just give up if we don't get a sample in 5 seconds.
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}

	info := spb.MetadataRequest{
		GpuNvidia: []*spb.GpuNvidiaInfo{},
	}

	g.mutex.RLock()
	defer g.mutex.RUnlock()

	if count, ok := g.sample["_gpu.count"].(float64); ok {
		info.GpuCount = uint32(count)
	} else {
		return nil
	}

	// No GPU found, so close the GPU monitor.
	if info.GpuCount == 0 {
		g.Close()
		return nil
	}

	if v, ok := g.sample["cuda_version"]; ok {
		if s, ok := v.(string); ok {
			info.CudaVersion = s
		}
	}

	names := make([]string, info.GpuCount)

	for di := 0; di < int(info.GpuCount); di++ {

		gpuInfo := &spb.GpuNvidiaInfo{}
		nameKey := fmt.Sprintf("_gpu.%d.name", di)
		if v, ok := g.sample[nameKey]; ok {
			if s, ok := v.(string); ok {
				gpuInfo.Name = s
				names[di] = gpuInfo.Name
			}
		}

		memTotalKey := fmt.Sprintf("_gpu.%d.memoryTotal", di)
		if v, ok := g.sample[memTotalKey]; ok {
			if f, ok := v.(float64); ok {
				gpuInfo.MemoryTotal = uint64(f)
			}
		}

		cudaCoresKey := fmt.Sprintf("_gpu.%d.cudaCores", di)
		if v, ok := g.sample[cudaCoresKey]; ok {
			// cudaCores defaults to 0 if the corresponding NVML query fails
			// in nvidia_gpu_stats.
			if f, ok := v.(float64); ok && f > 0 {
				gpuInfo.CudaCores = uint32(f)
			}
		}

		architectureKey := fmt.Sprintf("_gpu.%d.architecture", di)
		if v, ok := g.sample[architectureKey]; ok {
			if s, ok := v.(string); ok {
				gpuInfo.Architecture = s
			}
		}

		info.GpuNvidia = append(info.GpuNvidia, gpuInfo)
	}

	if len(names) > 0 {
		info.GpuType = "[" + strings.Join(names, ", ") + "]"
	}

	return &info
}

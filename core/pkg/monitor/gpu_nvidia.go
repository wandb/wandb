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

	"github.com/wandb/wandb/core/pkg/observability"
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
	name             string
	sample           map[string]any // latest reading from nvidia_gpu_stats command
	pid              int32          // pid of the process to monitor
	samplingInterval float64        // sampling interval in seconds
	lastTimestamp    float64        // last reported timestamp
	mutex            sync.RWMutex
	cmd              *exec.Cmd
	logger           *observability.CoreLogger
}

func NewGPUNvidia(logger *observability.CoreLogger, pid int32, samplingInterval float64) *GPUNvidia {
	g := &GPUNvidia{
		name:             "gpu",
		sample:           map[string]any{},
		pid:              pid,
		samplingInterval: samplingInterval,
		logger:           logger,
	}

	exPath, err := getCmdPath()
	if err != nil {
		return g
	}

	if samplingInterval == 0 {
		samplingInterval = defaultSamplingInterval.Seconds()
	}

	// we will use nvidia_gpu_stats to get GPU stats
	g.cmd = exec.Command(
		exPath,
		// monitor for GPU usage for this pid and its children
		fmt.Sprintf("--pid=%d", pid),
		// pid of the current process. nvidia_gpu_stats will exit when this process exits
		fmt.Sprintf("--ppid=%d", os.Getpid()),
		// sampling interval in seconds
		fmt.Sprintf("--interval=%f", samplingInterval),
	)

	// get a pipe to read from the command's stdout
	stdout, err := g.cmd.StdoutPipe()
	if err != nil {
		g.logger.CaptureError(
			fmt.Errorf("monitor: %v: error getting stdout pipe: %v for command: %v", g.name, err, g.cmd),
		)
		return nil
	}

	if err := g.cmd.Start(); err != nil {
		// this is a relevant error, so we will report it to sentry
		g.logger.CaptureError(
			fmt.Errorf("monitor: %v: error starting command %v: %v", g.name, g.cmd, err),
		)
		return nil
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
				g.logger.CaptureError(
					fmt.Errorf("monitor: %v: error parsing JSON %v: %v", g.name, line, err),
				)
				continue
			}

			// Process the JSON data
			g.mutex.Lock()
			for key, value := range data {
				g.sample[key] = value
			}
			g.mutex.Unlock()
		}

		if err := scanner.Err(); err != nil {
			return
		}
	}()

	return g
}

func (g *GPUNvidia) Name() string { return g.name }

func (g *GPUNvidia) Sample() (map[string]any, error) {
	if !isRunning(g.cmd) {
		// do not log error if the command is not running
		return nil, nil
	}

	// do not sample if the last timestamp is the same
	currentTimestamp, ok := g.sample["_timestamp"]
	if !ok {
		return nil, nil
	}

	if g.lastTimestamp == currentTimestamp {
		return nil, nil
	}

	if _, ok := currentTimestamp.(float64); !ok {
		return nil, fmt.Errorf("invalid timestamp: %v", currentTimestamp)
	}
	g.lastTimestamp = currentTimestamp.(float64)

	metrics := make(map[string]any)

	for metric, value := range g.sample {
		// skip metrics that start with "_", some of which are internal metrics
		// TODO: other metrics lack aggregation on the frontend; could be added in the future.
		if strings.HasPrefix(metric, "_") {
			continue
		}
		if value, ok := value.(float64); ok {
			metrics[metric] = value
		}
	}

	return metrics, nil
}

func (g *GPUNvidia) IsAvailable() bool {
	exPath, err := getCmdPath()
	if err != nil || exPath == "" {
		return false
	}
	return isRunning(g.cmd)
}

func (g *GPUNvidia) Close() {
	// send signal to close
	if g.IsAvailable() {
		if err := g.cmd.Process.Signal(os.Kill); err != nil {
			return
		}
	}
}

func (g *GPUNvidia) Probe() *spb.MetadataRequest {
	if !g.IsAvailable() {
		return nil
	}

	// Wait for the first sample, but no more than 5 seconds
	startTime := time.Now()
	for {
		g.mutex.RLock()
		_, ok := g.sample["_gpu.count"]
		g.mutex.RUnlock()
		if ok {
			break // Successfully got a sample
		}
		if time.Since(startTime) > 5*time.Second {
			// just give up if we don't get a sample in 5 seconds
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}

	info := spb.MetadataRequest{
		GpuNvidia: []*spb.GpuNvidiaInfo{},
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

		gpuInfo := &spb.GpuNvidiaInfo{}
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

		cudaCores := fmt.Sprintf("_gpu.%d.cudaCores", di)
		if v, ok := g.sample[cudaCores]; ok {
			if v, ok := v.(float64); ok {
				gpuInfo.CudaCores = uint32(v)
			}
		}

		architechture := fmt.Sprintf("_gpu.%d.architecture", di)
		if v, ok := g.sample[architechture]; ok {
			if v, ok := v.(string); ok {
				gpuInfo.Architecture = v
			}
		}

		info.GpuNvidia = append(info.GpuNvidia, gpuInfo)

	}

	info.GpuType = "[" + strings.Join(names, ", ") + "]"

	return &info
}

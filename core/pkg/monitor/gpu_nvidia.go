//go:build linux && !libwandb_core

package monitor

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
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

type GPUInfo struct {
	Architecture            string  `json:"architecture,omitempty" marshal:"-"`
	Brand                   string  `json:"brand,omitempty" marshal:"-"`
	CudaCores               int     `json:"cudaCores,omitempty" marshal:"-"`
	EncoderUtilization      int     `json:"encoderUtilization,omitempty" marshal:"-"`
	EnforcedPowerLimitWatts float64 `json:"enforcedPowerLimitWatts"`
	GPU                     int     `json:"gpu"`
	GraphicsClock           int     `json:"graphicsClock,omitempty" marshal:"-"`
	MaxPcieLinkGen          int     `json:"maxPcieLinkGen,omitempty" marshal:"-"`
	MaxPcieLinkWidth        int     `json:"maxPcieLinkWidth,omitempty" marshal:"-"`
	Memory                  int     `json:"memory"`
	MemoryAllocated         float64 `json:"memoryAllocated"`
	MemoryAllocatedBytes    int     `json:"memoryAllocatedBytes"`
	MemoryClock             int     `json:"memoryClock,omitempty" marshal:"-"`
	MemoryTotal             int     `json:"memoryTotal,omitempty" marshal:"-"`
	Name                    string  `json:"name,omitempty" marshal:"-"`
	PcieLinkGen             int     `json:"pcieLinkGen,omitempty" marshal:"-"`
	PcieLinkSpeed           int     `json:"pcieLinkSpeed,omitempty" marshal:"-"`
	PcieLinkWidth           int     `json:"pcieLinkWidth,omitempty" marshal:"-"`
	PowerPercent            float64 `json:"powerPercent"`
	PowerWatts              float64 `json:"powerWatts"`
	Temp                    int     `json:"temp"`
}

type GPUData struct {
	Timestamp   float64            `json:"timestamp"`
	CudaVersion string             `json:"cuda_version"`
	GPUs        map[string]GPUInfo `json:"-"`
	GPUCount    int                `json:"gpu.count"`
}

func (d *GPUData) UnmarshalJSON(data []byte) error {
	var rawMap map[string]interface{}
	if err := json.Unmarshal(data, &rawMap); err != nil {
		return err
	}

	d.GPUs = make(map[string]GPUInfo)

	for key, value := range rawMap {
		switch key {
		case "timestamp":
			if f, ok := value.(float64); ok {
				d.Timestamp = f
			}
		case "cuda_version":
			if s, ok := value.(string); ok {
				d.CudaVersion = s
			}
		case "gpu.count":
			if f, ok := value.(float64); ok {
				d.GPUCount = int(f)
			}
		default:
			if strings.HasPrefix(key, "gpu.") && strings.Count(key, ".") == 2 {
				parts := strings.Split(key, ".")
				gpuIndex := parts[1]
				field := parts[2]

				if _, exists := d.GPUs[gpuIndex]; !exists {
					d.GPUs[gpuIndex] = GPUInfo{}
				}

				gpuInfo := d.GPUs[gpuIndex]
				setValue(&gpuInfo, field, value)
				d.GPUs[gpuIndex] = gpuInfo
			}
		}
	}

	return nil
}

func (d GPUData) MarshalJSON() ([]byte, error) {
	rawMap := make(map[string]interface{})

	for gpuIndex, gpuInfo := range d.GPUs {
		v := reflect.ValueOf(gpuInfo)
		t := v.Type()
		for i := 0; i < v.NumField(); i++ {
			field := t.Field(i)
			if field.Tag.Get("marshal") == "-" {
				continue // Skip this field
			}
			value := v.Field(i).Interface()
			key := fmt.Sprintf("gpu.%s.%s", gpuIndex, field.Tag.Get("json"))
			rawMap[key] = value
		}
	}

	return json.Marshal(rawMap)
}

func setValue(gpuInfo *GPUInfo, field string, value interface{}) {
	v := reflect.ValueOf(gpuInfo).Elem()
	f := v.FieldByNameFunc(func(s string) bool {
		return strings.EqualFold(s, field)
	})

	if f.IsValid() {
		switch f.Kind() {
		case reflect.String:
			f.SetString(value.(string))
		case reflect.Int:
			f.SetInt(int64(value.(float64)))
		case reflect.Float64:
			f.SetFloat(value.(float64))
		}
	}
}

type GPUNvidia struct {
	name     string
	sample   *GPUData         // latest reading from nvidia_gpu_stats command
	metrics  map[string][]any // all readings
	settings *service.Settings
	mutex    sync.RWMutex
	cmd      *exec.Cmd
}

func NewGPUNvidia(settings *service.Settings) *GPUNvidia {
	gpu := &GPUNvidia{
		name:     "gpu",
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
			var data GPUData
			err := json.Unmarshal([]byte(line), &data)
			if err != nil {
				fmt.Println("Error parsing JSON:", err)
			}

			// Process the JSON data
			gpu.mutex.Lock()
			gpu.sample = &data
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

	// Check if the last timestamp is the same
	currentTimestamp := g.sample.Timestamp
	lastTimestamps, ok := g.metrics["_timestamp"]
	if ok && len(lastTimestamps) > 0 && lastTimestamps[len(lastTimestamps)-1] == currentTimestamp {
		return
	}

	// Add timestamp
	g.metrics["_timestamp"] = append(g.metrics["_timestamp"], currentTimestamp)

	// Add GPU specific metrics
	for gpuIndex, gpuInfo := range g.sample.GPUs {
		v := reflect.ValueOf(gpuInfo)
		t := v.Type()
		for i := 0; i < v.NumField(); i++ {
			field := t.Field(i)
			value := v.Field(i).Interface()
			if field.Tag.Get("marshal") == "-" {
				continue // Skip this field
			}
			key := fmt.Sprintf("gpu.%s.%s", gpuIndex, field.Tag.Get("json"))

			// Convert value to float64
			var floatValue float64
			switch v := value.(type) {
			case int:
				floatValue = float64(v)
			case float64:
				floatValue = v
			case string:
				floatValue, _ = strconv.ParseFloat(v, 64)
			default:
				// Skip fields that can't be converted to float64
				continue
			}

			g.metrics[key] = append(g.metrics[key], floatValue)
		}
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

func (g *GPUNvidia) waitForFirstSample() error {
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		g.mutex.RLock()
		sampleExists := g.sample != nil
		g.mutex.RUnlock()

		if sampleExists {
			return nil
		}

		if !isRunning(g.cmd) {
			return errors.New("command stopped running before first sample")
		}

		time.Sleep(100 * time.Millisecond)
	}
	return errors.New("timeout waiting for first sample")
}

func (g *GPUNvidia) Probe() *service.MetadataRequest {
	if !g.IsAvailable() {
		return nil
	}

	// wait for the first sample
	if err := g.waitForFirstSample(); err != nil {
		return nil
	}

	info := service.MetadataRequest{
		GpuNvidia: []*service.GpuNvidiaInfo{},
	}

	info.GpuCount = uint32(g.sample.GPUCount)

	// no GPU found, so close the GPU monitor
	if info.GpuCount == 0 {
		g.Close()
		return nil
	}

	info.CudaVersion = g.sample.CudaVersion

	names := make([]string, info.GpuCount)

	for di := 0; di < int(info.GpuCount); di++ {
		gpuInfo := &service.GpuNvidiaInfo{}
		gpuInfo.Name = g.sample.GPUs[strconv.Itoa(di)].Name
		names[di] = gpuInfo.Name
		gpuInfo.MemoryTotal = uint64(g.sample.GPUs[strconv.Itoa(di)].MemoryTotal)

		info.GpuNvidia = append(info.GpuNvidia, gpuInfo)
	}

	info.GpuType = "[" + strings.Join(names, ", ") + "]"

	return &info
}

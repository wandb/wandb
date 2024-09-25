//go:build linux

package monitor

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// NeuronMonitorConfig represents the configuration for the neuron-monitor command.
type NeuronMonitorConfig struct {
	Period         string                `json:"period"`
	NeuronRuntimes []NeuronRuntimeConfig `json:"neuron_runtimes"`
	SystemMetrics  []SystemMetricConfig  `json:"system_metrics"`
}

type NeuronRuntimeConfig struct {
	TagFilter string         `json:"tag_filter"`
	Metrics   []MetricConfig `json:"metrics"`
}

type SystemMetricConfig struct {
	Type string `json:"type"`
}

type MetricConfig struct {
	Type string `json:"type"`
}

// NeuronCoreMemoryUsage represents the memory usage breakdown for a neuron core.
type NeuronCoreMemoryUsage struct {
	Constants             int `json:"constants"`
	ModelCode             int `json:"model_code"`
	ModelSharedScratchpad int `json:"model_shared_scratchpad"`
	RuntimeMemory         int `json:"runtime_memory"`
	Tensors               int `json:"tensors"`
}

// HostMemoryUsage represents the memory usage breakdown on the host.
type HostMemoryUsage struct {
	ApplicationMemory int `json:"application_memory"`
	Constants         int `json:"constants"`
	DmaBuffers        int `json:"dma_buffers"`
	Tensors           int `json:"tensors"`
}

// TrainiumStats represents the stats returned by the neuron-monitor command.
//
// NeuroncoreUtilization: per neuron core utilization
// HostTotalMemoryUsage: total memory usage in bytes
// NeuronDeviceTotalMemoryUsage: total memory usage on neuron device in bytes
// HostMemoryUsage: host memory usage breakdown
// NeuroncoreMemoryUsage: per neuron core memory usage breakdown
type TrainiumStats struct {
	NeuroncoreUtilization        map[int]float64               `json:"neuroncore_utilization"`
	HostTotalMemoryUsage         int                           `json:"host_total_memory_usage"`
	NeuronDeviceTotalMemoryUsage int                           `json:"neuron_device_total_memory_usage"`
	HostMemoryUsage              HostMemoryUsage               `json:"host_memory_usage"`
	NeuroncoreMemoryUsage        map[int]NeuronCoreMemoryUsage `json:"neuroncore_memory_usage"`
}

// Trainium is a monitor for AWS Trainium devices.
//
// Uses the neuron-monitor command to get stats.
type Trainium struct {
	name                    string
	pid                     int32
	samplingInterval        float64
	neuronMonitorConfigPath string
	mutex                   sync.RWMutex
	cmd                     *exec.Cmd
	logger                  *observability.CoreLogger
	rawStats                map[string]any
	shutdownEvent           chan struct{}
	isRunning               bool
}

// getCmdPath returns the path to the neuron-monitor command.
func getNeuronMonitorCmdPath() (string, error) {
	// try to find the command in the PATH
	exPath, err := exec.LookPath("neuron-monitor")
	if err == nil {
		return exPath, nil
	}
	// try the default path
	exPath = "/opt/aws/neuron/bin/neuron-monitor"
	if _, err := os.Stat(exPath); os.IsNotExist(err) {
		return "", err
	}
	return exPath, nil
}

func NewTrainium(
	logger *observability.CoreLogger,
	pid int32,
	samplingInterval float64,
	neuronMonitorConfigPath string,
) *Trainium {
	t := &Trainium{
		name:                    "trainium",
		pid:                     pid,
		samplingInterval:        samplingInterval,
		neuronMonitorConfigPath: neuronMonitorConfigPath,
		logger:                  logger,
		shutdownEvent:           make(chan struct{}),
	}

	// check if the neuron-monitor command is available
	if _, err := getNeuronMonitorCmdPath(); err != nil {
		return nil
	}

	if t.samplingInterval == 0 {
		t.samplingInterval = 1.0
	}

	// neuron-monitor requires a JSON config file.
	// we provide an option to supply a custom config file path
	// in case the default temp file path is not writable.
	if t.neuronMonitorConfigPath == "" {
		t.neuronMonitorConfigPath = filepath.Join(os.TempDir(), "neuron_monitor_config.json")
		err := t.writeNeuronMonitorConfig(t.neuronMonitorConfigPath)
		if err != nil {
			return nil
		}
	}

	err := t.Start()
	if err != nil {
		return nil
	}

	return t
}

// writeNeuronMonitorConfig writes the neuron-monitor config to a file.
func (t *Trainium) writeNeuronMonitorConfig(neuronMonitorConfigPath string) error {
	config := NeuronMonitorConfig{
		Period: fmt.Sprintf("%ds", int(t.samplingInterval)),
		NeuronRuntimes: []NeuronRuntimeConfig{
			{
				TagFilter: ".*",
				Metrics: []MetricConfig{
					{Type: "neuroncore_counters"},
					{Type: "memory_used"},
					{Type: "neuron_runtime_vcpu_usage"},
				},
			},
		},
		SystemMetrics: []SystemMetricConfig{
			{Type: "vcpu_usage"},
			{Type: "memory_info"},
			{Type: "neuron_hw_counters"},
		},
	}

	jsonData, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal config: %v", err)
	}

	err = os.WriteFile(neuronMonitorConfigPath, jsonData, 0644)
	if err != nil {
		return fmt.Errorf("failed to write config file: %v", err)
	}

	return nil
}

func (t *Trainium) SetRawStats(rawStats map[string]any) {
	t.mutex.Lock()
	t.rawStats = rawStats
	t.mutex.Unlock()
}

func (t *Trainium) SetRunningState(running bool) {
	t.isRunning = running
}

// Start executes the neuron-monitor command and reads its output in a separate goroutine.
//
// The output is expected to be JSON. It is parsed and stored in the rawStats field.
func (t *Trainium) Start() error {
	if t.isRunning {
		return fmt.Errorf("Trainium monitor is already running")
	}

	exPath, err := getNeuronMonitorCmdPath()
	if err != nil {
		return fmt.Errorf("failed to get command path: %v", err)
	}

	t.cmd = exec.Command(exPath, "-c", t.neuronMonitorConfigPath)

	stdout, err := t.cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("failed to get stdout pipe: %v", err)
	}

	if err := t.cmd.Start(); err != nil {
		return fmt.Errorf("failed to start command: %v", err)
	}

	t.SetRunningState(true)

	go func() {
		scanner := bufio.NewScanner(stdout)
		for {
			select {
			case <-t.shutdownEvent:
				return
			default:
				if scanner.Scan() {
					rawStats := make(map[string]any)
					if err := json.Unmarshal(scanner.Bytes(), &rawStats); err != nil {
						t.logger.CaptureError(fmt.Errorf("trainium: failed to parse JSON: %v", err))
						continue
					}
					t.SetRawStats(rawStats)
				}
			}
		}
	}()

	return nil
}

// isMatchingEntry checks if an entry in neuronRuntimeData should be saved.
//
// Checks if the pid in the entry matches the pid of the process.
// If not (as in the case of multi-process training with torchrun),
// checks if the LOCAL_RANK environment variable is set.
//
// TODO: add matching by neuron_runtime_tag
func (t *Trainium) isMatchingEntry(entry map[string]any) bool {
	entryPid, ok := entry["pid"].(float64)
	if !ok {
		return false
	}
	return int32(entryPid) == t.pid || os.Getenv("LOCAL_RANK") != ""
}

// Sample returns the latest stats from the neuron-monitor command.
//
// The stats are parsed into a TrainiumStats struct, flattened and returned as a map.
//
//gocyclo:ignore
func (t *Trainium) Sample() (map[string]any, error) {
	if !t.isRunning {
		return nil, nil
	}

	t.mutex.RLock()
	rawStats := t.rawStats
	t.mutex.RUnlock()

	neuronRuntimeData, ok := rawStats["neuron_runtime_data"].([]any)
	if !ok || len(neuronRuntimeData) == 0 {
		return nil, nil
	}

	var matchingEntry map[string]any
	for _, entry := range neuronRuntimeData {
		if entryMap, ok := entry.(map[string]any); ok {
			if t.isMatchingEntry(entryMap) {
				matchingEntry = entryMap
				break
			}
		}
	}

	if matchingEntry == nil {
		return nil, nil
	}

	report, ok := matchingEntry["report"].(map[string]any)
	if !ok {
		return nil, nil
	}

	neuroncoreCounters, ok := report["neuroncore_counters"].(map[string]any)
	if !ok {
		return nil, nil
	}

	neuronCoresInUse, ok := neuroncoreCounters["neuroncores_in_use"].(map[string]any)
	if !ok {
		return nil, nil
	}

	neuroncoreUtilization := make(map[int]float64)
	for k, v := range neuronCoresInUse {
		coreID, _ := strconv.Atoi(k)
		if coreData, ok := v.(map[string]any); ok {
			if utilization, ok := coreData["neuroncore_utilization"].(float64); ok {
				neuroncoreUtilization[coreID] = utilization
			}
		}
	}

	memoryUsed, ok := report["memory_used"].(map[string]any)
	if !ok {
		return nil, nil
	}

	neuronRuntimeUsedBytes, ok := memoryUsed["neuron_runtime_used_bytes"].(map[string]any)
	if !ok {
		return nil, nil
	}

	hostTotalMemoryUsage, _ := neuronRuntimeUsedBytes["host"].(float64)
	neuronDeviceTotalMemoryUsage, _ := neuronRuntimeUsedBytes["neuron_device"].(float64)

	usageBreakdown, ok := neuronRuntimeUsedBytes["usage_breakdown"].(map[string]any)
	if !ok {
		return nil, nil
	}

	var hostMemoryUsage HostMemoryUsage
	if hostUsage, ok := usageBreakdown["host"].(map[string]any); ok {
		jsonBytes, err := json.Marshal(hostUsage)
		if err == nil {
			err = json.Unmarshal(jsonBytes, &hostMemoryUsage)
		}
		if err != nil {
			t.logger.CaptureError(fmt.Errorf("trainium: failed to unmarshal host memory usage: %v", err))
		}
	}

	neuroncoreMemoryUsage := make(map[int]NeuronCoreMemoryUsage)
	if ncMemUsage, ok := usageBreakdown["neuroncore_memory_usage"].(map[string]any); ok {
		for k, v := range ncMemUsage {
			coreID, _ := strconv.Atoi(k)
			jsonBytes, err := json.Marshal(v)
			if err == nil {
				var coreUsage NeuronCoreMemoryUsage
				err = json.Unmarshal(jsonBytes, &coreUsage)
				if err == nil {
					neuroncoreMemoryUsage[coreID] = coreUsage
				}
			}
			if err != nil {
				t.logger.CaptureError(fmt.Errorf("trainium: failed to unmarshal neuroncore memory usage: %v", err))
			}
		}
	}

	// When the training script is executed with torchrun,
	// we only want to keep the relevant LOCAL_RANK stats
	localRank := os.Getenv("LOCAL_RANK")
	if localRank != "" {
		localRankInt, _ := strconv.Atoi(localRank)
		neuroncoreUtilization = map[int]float64{localRankInt: neuroncoreUtilization[localRankInt]}
		neuroncoreMemoryUsage = map[int]NeuronCoreMemoryUsage{localRankInt: neuroncoreMemoryUsage[localRankInt]}
	}

	stats := TrainiumStats{
		NeuroncoreUtilization:        neuroncoreUtilization,
		HostTotalMemoryUsage:         int(hostTotalMemoryUsage),
		NeuronDeviceTotalMemoryUsage: int(neuronDeviceTotalMemoryUsage),
		HostMemoryUsage:              hostMemoryUsage,
		NeuroncoreMemoryUsage:        neuroncoreMemoryUsage,
	}

	return t.flattenStats(stats), nil
}

// flattenStats recursively flattens the stats into a map.
//
// Keys are prepended with "trn." to be recognized by the frontend.
func (t *Trainium) flattenStats(sample TrainiumStats) map[string]any {
	flattened := make(map[string]any)

	var flatten func(string, any)
	flatten = func(key string, value any) {
		switch v := value.(type) {
		case int:
			flattened[key] = float64(v)
		case float64:
			flattened[key] = v
		case map[int]float64:
			for k, vv := range v {
				flatten(fmt.Sprintf("%d.%s", k, key), vv)
			}
		case map[int]NeuronCoreMemoryUsage:
			for k, vv := range v {
				flatten(fmt.Sprintf("%d.%s", k, key), vv)
			}
		case HostMemoryUsage, NeuronCoreMemoryUsage:
			jsonBytes, _ := json.Marshal(v)
			var subMap map[string]any
			err := json.Unmarshal(jsonBytes, &subMap)
			if err != nil {
				t.logger.CaptureError(fmt.Errorf("trainium: failed to unmarshal submap: %v", err))
				return
			}
			for subKey, subValue := range subMap {
				flatten(fmt.Sprintf("%s.%s", key, subKey), subValue)
			}
		}
	}

	flatten("neuroncore_utilization", sample.NeuroncoreUtilization)
	flatten("host_total_memory_usage", sample.HostTotalMemoryUsage)
	flatten("neuron_device_total_memory_usage", sample.NeuronDeviceTotalMemoryUsage)
	flatten("host_memory_usage", sample.HostMemoryUsage)
	flatten("neuroncore_memory_usage", sample.NeuroncoreMemoryUsage)

	// Prepend "trn." to each key. This is necessary for the frontend to recognize the keys.
	result := make(map[string]any, len(flattened))
	for k, v := range flattened {
		newKey := "trn." + k
		result[newKey] = v
	}

	return result
}

func (t *Trainium) Name() string {
	return t.name
}

func (t *Trainium) IsAvailable() bool {
	_, err := getNeuronMonitorCmdPath()
	return err == nil
}

// Close stops the neuron-monitor command and sets isRunning to false.
func (t *Trainium) Close() {
	if !t.isRunning {
		return
	}

	close(t.shutdownEvent)
	if t.cmd != nil && t.cmd.Process != nil {
		err := t.cmd.Process.Kill()
		if err != nil {
			t.logger.CaptureError(fmt.Errorf("trainium: failed to kill process: %v", err))
		}
	}
	t.SetRunningState(false)
}

func (t *Trainium) Probe() *spb.MetadataRequest {
	if !t.IsAvailable() {
		return nil
	}

	info := &spb.MetadataRequest{
		Trainium: &spb.TrainiumInfo{
			Name:   t.name,
			Vendor: "AWS",
		},
	}

	// Wait for the first sample, but no more than 5 seconds.
	startTime := time.Now()
	for {
		t.mutex.RLock()
		_, ok := t.rawStats["neuron_hardware_info"]
		t.mutex.RUnlock()
		if ok {
			break // Successfully got a sample
		}
		if time.Since(startTime) > 5*time.Second {
			// just give up if we don't get a sample in 5 seconds
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}

	neuronHardwareInfo, ok := t.rawStats["neuron_hardware_info"].(map[string]any)
	if !ok {
		return nil
	}

	neuronDeviceCount, ok := neuronHardwareInfo["neuron_device_count"].(uint32)
	if ok {
		info.Trainium.NeuronDeviceCount = neuronDeviceCount
	}
	neuroncorePerDeviceCount, ok := neuronHardwareInfo["neuroncore_per_device_count"].(uint32)
	if ok {
		info.Trainium.NeuroncorePerDeviceCount = neuroncorePerDeviceCount
	}

	return info
}

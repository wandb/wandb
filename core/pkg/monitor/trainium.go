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

	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

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

type NeuronCoreMemoryUsage struct {
	Constants             int `json:"constants"`
	ModelCode             int `json:"model_code"`
	ModelSharedScratchpad int `json:"model_shared_scratchpad"`
	RuntimeMemory         int `json:"runtime_memory"`
	Tensors               int `json:"tensors"`
}

type HostMemoryUsage struct {
	ApplicationMemory int `json:"application_memory"`
	Constants         int `json:"constants"`
	DmaBuffers        int `json:"dma_buffers"`
	Tensors           int `json:"tensors"`
}

type Stats struct {
	NeuroncoreUtilization        map[int]float64               `json:"neuroncore_utilization"`
	HostTotalMemoryUsage         int                           `json:"host_total_memory_usage"`
	NeuronDeviceTotalMemoryUsage int                           `json:"neuron_device_total_memory_usage"`
	HostMemoryUsage              HostMemoryUsage               `json:"host_memory_usage"`
	NeuroncoreMemoryUsage        map[int]NeuronCoreMemoryUsage `json:"neuroncore_memory_usage"`
}

type Trainium struct {
	name                    string
	pid                     int32
	samplingInterval        float64
	neuronMonitorConfigPath string
	lastTimestamp           float64
	mutex                   sync.RWMutex
	cmd                     *exec.Cmd
	logger                  *observability.CoreLogger
	rawSamples              [][]byte
	shutdownEvent           chan struct{}
	isRunning               bool
}

func getCmdPath() (string, error) {
	// exPath := "/opt/aws/neuron/bin/neuron-monitor"
	exPath := "/Users/dimaduev/dev/sdk/trn.py"
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
		rawSamples:              make([][]byte, 0, 10),
		shutdownEvent:           make(chan struct{}),
	}

	if t.samplingInterval == 0 {
		t.samplingInterval = 1.0
	}

	if t.neuronMonitorConfigPath == "" {
		t.neuronMonitorConfigPath = filepath.Join(os.TempDir(), "neuron_monitor_config.json")
		// write the config file to disk
		err := t.writeNeuronMonitorConfig(t.neuronMonitorConfigPath)
		fmt.Println(t.neuronMonitorConfigPath)
		if err != nil {
			return nil
		}
	}

	err := t.Start()
	fmt.Println("Start: ", err)
	if err != nil {
		return nil
	}

	return t
}

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

func (t *Trainium) Start() error {
	if t.isRunning {
		return fmt.Errorf("Trainium monitor is already running")
	}

	exPath, err := getCmdPath()
	fmt.Println(exPath)
	if err != nil {
		return fmt.Errorf("failed to get command path: %v", err)
	}
	fmt.Println("exPath", exPath)

	t.cmd = exec.Command(exPath, "-c", t.neuronMonitorConfigPath)
	fmt.Println("t.cmd", t.cmd)

	stdout, err := t.cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("failed to get stdout pipe: %v", err)
	}

	if err := t.cmd.Start(); err != nil {
		return fmt.Errorf("failed to start command: %v", err)
	}

	t.isRunning = true

	go func() {
		scanner := bufio.NewScanner(stdout)
		for {
			select {
			case <-t.shutdownEvent:
				return
			default:
				if scanner.Scan() {
					fmt.Println("OLOLO")
					t.mutex.Lock()
					t.rawSamples = append(t.rawSamples, scanner.Bytes())
					t.mutex.Unlock()
				}
			}
		}
	}()

	return nil
}

func (t *Trainium) isMatchingEntry(entry map[string]any) bool {
	entryPid, ok := entry["pid"].(float64)
	if !ok {
		return false
	}
	return int32(entryPid) == t.pid || os.Getenv("LOCAL_RANK") != ""
}

func (t *Trainium) Sample() (map[string]any, error) {
	if !t.isRunning {
		return nil, nil
	}

	var rawStats map[string]any
	err := json.Unmarshal(t.rawSamples[len(t.rawSamples)-1], &rawStats)
	if err != nil {
		return nil, fmt.Errorf("error parsing JSON: %v", err)
	}

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
		json.Unmarshal([]byte(fmt.Sprintf("%v", hostUsage)), &hostMemoryUsage)
	}

	neuroncoreMemoryUsage := make(map[int]NeuronCoreMemoryUsage)
	if ncMemUsage, ok := usageBreakdown["neuroncore_memory_usage"].(map[string]any); ok {
		for k, v := range ncMemUsage {
			coreID, _ := strconv.Atoi(k)
			var coreUsage NeuronCoreMemoryUsage
			json.Unmarshal([]byte(fmt.Sprintf("%v", v)), &coreUsage)
			neuroncoreMemoryUsage[coreID] = coreUsage
		}
	}

	stats := Stats{
		NeuroncoreUtilization:        neuroncoreUtilization,
		HostTotalMemoryUsage:         int(hostTotalMemoryUsage),
		NeuronDeviceTotalMemoryUsage: int(neuronDeviceTotalMemoryUsage),
		HostMemoryUsage:              hostMemoryUsage,
		NeuroncoreMemoryUsage:        neuroncoreMemoryUsage,
	}

	return t.flattenStats(stats), nil
}

func (t *Trainium) flattenStats(sample Stats) map[string]any {
	flattened := make(map[string]any)

	var flatten func(string, interface{})
	flatten = func(key string, value interface{}) {
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
			json.Unmarshal(jsonBytes, &subMap)
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

	return flattened
}

func (t *Trainium) Name() string {
	return t.name
}

func (t *Trainium) IsAvailable() bool {
	_, err := getCmdPath()
	fmt.Println("IsAvailable", err)
	return err == nil
}

func (t *Trainium) Close() {
	if t == nil || !t.isRunning {
		return
	}

	close(t.shutdownEvent)
	if t.cmd != nil && t.cmd.Process != nil {
		t.cmd.Process.Kill()
	}
	t.isRunning = false
}

func (t *Trainium) Probe() *spb.MetadataRequest {
	if t == nil || !t.IsAvailable() {
		return nil
	}

	info := &spb.MetadataRequest{
		// GpuNvidia: []*spb.GpuNvidiaInfo{},
	}

	// Wait for the first sample
	for start := time.Now(); time.Since(start) < 5*time.Second; {
		if len(t.rawSamples) > 0 {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}

	return info
}

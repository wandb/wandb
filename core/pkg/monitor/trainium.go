package monitor

import (
	"bufio"
	"context"
	"fmt"
	"os/exec"
	"sync"
	"time"

	"github.com/wandb/wandb/core/pkg/service"
)

const (
	NeuronMonitorDefaultConfig string = `{
		"period": "1s",
		"neuron_runtimes": [
			{
				"tag_filter": ".*",
				"metrics": [
					{"type": "neuroncore_counters"},
					{"type": "memory_used"},
					{"type": "neuron_runtime_vcpu_usage"}
				]
			}
		],
		"system_metrics": [
			{"type": "vcpu_usage"},
			{"type": "memory_info"},
			{"type": "neuron_hw_counters"}
		]
	}`
	// TODO: add `which`
	NeuronLsCommand   string = "/opt/aws/neuron/bin/neuron-ls -j"
	NeuronMonitorPath string = "/opt/aws/neuron/bin/neuron-monitor"
)

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

// type NeuronCoreStats struct {
// 	Name                    string
// 	Samples                 []Stats
// 	NeuronMonitorConfigPath string
// }

type Trainium struct {
	name       string
	settings   *service.Settings
	metrics    map[string][]float64
	rawSamples []string
	// GetStatsFunc func() (Stats, error)
	mutex sync.RWMutex
}

func NewTrainium(settings *service.Settings) *Trainium {
	t := &Trainium{
		name:       "trainium",
		settings:   settings,
		metrics:    make(map[string][]float64),
		rawSamples: make([]string, 0),
		// this is done this way to be able to mock the function in tests
		// GetStatsFunc: getStats,
	}
	return t
}

func (t *Trainium) Name() string { return t.name }

func (t *Trainium) SampleMetrics() {
	t.mutex.Lock()
	defer t.mutex.Unlock()

	if len(t.rawSamples) == 0 {
		return
	}


}

func (t *Trainium) AggregateMetrics() map[string]float64 {
	t.mutex.Lock()
	defer t.mutex.Unlock()

	return map[string]float64{}
}

func (t *Trainium) ClearMetrics() {
	t.mutex.Lock()
	defer t.mutex.Unlock()

	t.metrics = make(map[string][]float64)
}

func (t *Trainium) IsAvailable() bool {
	// only run neuron-monitor if it's not running already and if it is available
	go runNeuronMonitor(&t.mutex, t.rawSamples)
	return true
}

func (t *Trainium) Probe() *service.MetadataRequest {
	return nil
}

// func getStats() (Stats, error) {
// 	return Stats{}, nil
// }

func runNeuronMonitor(mutex *sync.RWMutex, rawSamples []string) error {
	// t.WriteNeuronMonitorConfig()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// cmd := exec.CommandContext(ctx, NeuronMonitorPath, "-c", neuronMonitorConfigPath)
	// TODO: dev only
	cmd := exec.CommandContext(ctx, "python", "/Users/dimaduev/dev/sdk/trn.py")
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("neuron-monitor failed: %v", err)
	}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("neuron-monitor failed: %v", err)
	}

	scanner := bufio.NewScanner(stdout)

	for {
		if ctx.Err() != nil {
			cmd.Process.Kill()
			cmd.Wait()
			break
		}

		if !scanner.Scan() {
			time.Sleep(100 * time.Millisecond)
			continue
		}

		mutex.Lock()
		rawSamples = append(rawSamples, scanner.Text())
		mutex.Unlock()
		fmt.Println(rawSamples)
	}

	return nil
}

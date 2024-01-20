package monitor

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
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
	NeuronLsDefaultPath string = "/opt/aws/neuron/bin/neuron-ls"
	// NeuronMonitorDefaultPath string = "/opt/aws/neuron/bin/neuron-monitor"
	// TODO: dev only
	NeuronMonitorDefaultPath string = "/Users/dimaduev/dev/sdk/trn.py"
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
	ctx       context.Context
	cancel    context.CancelFunc
	wg        sync.WaitGroup
	name      string
	settings  *service.Settings
	metrics   map[string][]float64
	rawSample string
	// GetStatsFunc func() (Stats, error)
	mutex             sync.RWMutex
	neuronLsPath      string
	neuronMonitorPath string
}

func NewTrainium(settings *service.Settings) *Trainium {
	ctx, cancel := context.WithCancel(context.Background())

	t := &Trainium{
		ctx:      ctx,
		cancel:   cancel,
		wg:       sync.WaitGroup{},
		name:     "trainium",
		settings: settings,
		metrics:  make(map[string][]float64),
		// this is done this way to be able to mock the function in tests
		// GetStatsFunc: getStats,
	}

	if _, err := os.Stat(NeuronLsDefaultPath); os.IsNotExist(err) {
		// If the file doesn't exist, try finding the command in PATH
		if path, err := exec.LookPath("neuron-ls"); err == nil {
			t.neuronLsPath = path
		}
	} else {
		t.neuronLsPath = NeuronLsDefaultPath
	}

	if _, err := os.Stat(NeuronMonitorDefaultPath); os.IsNotExist(err) {
		// If the file doesn't exist, try finding the command in PATH
		if path, err := exec.LookPath("neuron-monitor"); err == nil {
			t.neuronMonitorPath = path
		}
	} else {
		t.neuronMonitorPath = NeuronMonitorDefaultPath
	}

	return t
}

func (t *Trainium) Name() string { return t.name }

func (t *Trainium) SampleMetrics() {
	if t.rawSample == "" {
		return
	}

	t.mutex.Lock()
	defer t.mutex.Unlock()

	var sample map[string]interface{}
	err := json.Unmarshal([]byte(t.rawSample), &sample)
	if err != nil {
		fmt.Println(err)
	}
	fmt.Println(sample)
	fmt.Println()
	t.rawSample = ""
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
	if t.neuronMonitorPath == "" {
		return false
	}
	// otherwise, run neuron-monitor
	t.wg.Add(1)
	go func() {
		err := t.runNeuronMonitor()
		if err != nil {
			fmt.Println(err)
		}
		t.wg.Done()
	}()
	return true
}

func (t *Trainium) Close() error {
	t.cancel()
	t.wg.Wait()
	return nil
}

func (t *Trainium) Probe() *service.MetadataRequest {
	return nil
}

// func getStats() (Stats, error) {
// 	return Stats{}, nil
// }

func (t *Trainium) runNeuronMonitor() error {
	// t.WriteNeuronMonitorConfig()

	// cmd := exec.CommandContext(ctx, NeuronMonitorPath, "-c", neuronMonitorConfigPath)
	// TODO: dev only
	cmd := exec.CommandContext(t.ctx, "python", "/Users/dimaduev/dev/sdk/trn.py")
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("neuron-monitor failed: %v", err)
	}

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("neuron-monitor failed: %v", err)
	}

	scanner := bufio.NewScanner(stdout)

	for {
		fmt.Println("scanning")
		if t.ctx.Err() != nil {
			err := cmd.Process.Kill()
			if err != nil {
				return fmt.Errorf("neuron-monitor failed: %v", err)
			}
			err = cmd.Wait()
			if err != nil {
				return fmt.Errorf("neuron-monitor failed: %v", err)
			}
			break
		}

		if !scanner.Scan() {
			time.Sleep(300 * time.Millisecond)
			continue
		}

		t.mutex.Lock()
		t.rawSample = scanner.Text()
		t.mutex.Unlock()
	}

	return nil
}

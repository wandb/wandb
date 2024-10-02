//go:build linux && !libwandb_core

package monitor_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/pkg/monitor"
)

func TestTrainiumSample(t *testing.T) {
	t.Setenv("LOCAL_RANK", "0")

	trainium := monitor.Trainium{}

	// mock data
	rawStats := map[string]interface{}{
		"neuron_runtime_data": []interface{}{
			map[string]interface{}{
				"pid": float64(1337),
				"report": map[string]interface{}{
					"neuroncore_counters": map[string]interface{}{
						"neuroncores_in_use": map[string]interface{}{
							"0": map[string]interface{}{
								"neuroncore_utilization": 1.3631567613356375,
							},
						},
					},
					"memory_used": map[string]interface{}{
						"neuron_runtime_used_bytes": map[string]interface{}{
							"host":          float64(610705408),
							"neuron_device": float64(102298328),
							"usage_breakdown": map[string]interface{}{
								"host": map[string]interface{}{
									"application_memory": float64(609656832),
									"constants":          float64(0),
									"dma_buffers":        float64(1048576),
									"tensors":            float64(0),
								},
								"neuroncore_memory_usage": map[string]interface{}{
									"0": map[string]interface{}{
										"constants":               float64(196608),
										"model_code":              float64(101125344),
										"model_shared_scratchpad": float64(0),
										"runtime_memory":          float64(0),
										"tensors":                 float64(943608),
									},
								},
							},
						},
					},
				},
			},
		},
	}
	trainium.SetRawStats(rawStats)
	trainium.SetRunningState(true)

	sample, err := trainium.Sample()

	assert.NoError(t, err)
	assert.NotNil(t, sample)

	// Check for some expected keys and values
	assert.Equal(t, float64(610705408), sample["trn.host_total_memory_usage"])
	assert.Equal(t, float64(102298328), sample["trn.neuron_device_total_memory_usage"])
	assert.Equal(t, float64(609656832), sample["trn.host_memory_usage.application_memory"])

	// Check that keys are properly prefixed with "trn."
	for key := range sample {
		assert.True(t, len(key) > 4 && key[:4] == "trn.")
	}
}

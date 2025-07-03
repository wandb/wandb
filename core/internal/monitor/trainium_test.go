//go:build linux && !libwandb_core

package monitor_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/monitor"
)

func TestTrainiumSample(t *testing.T) {
	t.Setenv("LOCAL_RANK", "0")

	trainium := monitor.Trainium{}

	// mock data
	rawStats := map[string]any{
		"neuron_runtime_data": []any{
			map[string]any{
				"pid": float64(1337),
				"report": map[string]any{
					"neuroncore_counters": map[string]any{
						"neuroncores_in_use": map[string]any{
							"0": map[string]any{
								"neuroncore_utilization": 1.3631567613356375,
							},
						},
					},
					"memory_used": map[string]any{
						"neuron_runtime_used_bytes": map[string]any{
							"host":          float64(610705408),
							"neuron_device": float64(102298328),
							"usage_breakdown": map[string]any{
								"host": map[string]any{
									"application_memory": float64(609656832),
									"constants":          float64(0),
									"dma_buffers":        float64(1048576),
									"tensors":            float64(0),
								},
								"neuroncore_memory_usage": map[string]any{
									"0": map[string]any{
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

	metrics := make(map[string]any)
	for _, item := range sample.Item {
		metrics[item.Key], _ = simplejsonext.UnmarshalString(item.ValueJson)
	}

	// Check for some expected keys and values
	assert.Equal(t, float64(610705408), metrics["trn.host_total_memory_usage"])
	assert.Equal(t, float64(102298328), metrics["trn.neuron_device_total_memory_usage"])
	assert.Equal(t, float64(609656832), metrics["trn.host_memory_usage.application_memory"])

	// Check that keys are properly prefixed with "trn."
	for _, item := range sample.Item {
		assert.True(t, len(item.Key) > 4 && item.Key[:4] == "trn.")
	}
}

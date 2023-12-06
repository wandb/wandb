package monitor_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/nexus/pkg/monitor"
)

func TestNewGPUAMD(t *testing.T) {
	gpu := monitor.NewGPUAMD(nil)
	assert.NotNil(t, gpu)
	assert.Equal(t, "gpu", gpu.Name())
	assert.Len(t, gpu.Samples(), 0)
}

func TestGPUAMD_ParseStats(t *testing.T) {
	gpu := monitor.NewGPUAMD(nil)
	stats := map[string]interface{}{
		"GPU use (%)":                        "0",
		"GPU memory use (%)":                 "0",
		"Temperature (Sensor memory) (C)":    "43.0",
		"Average Graphics Package Power (W)": "89.0",
		"Max Graphics Package Power (W)":     "560.0",
	}
	parsedStats := gpu.ParseStats(stats)

	expected := monitor.Stats{
		monitor.GPU:             0,
		monitor.MemoryAllocated: 0,
		monitor.Temp:            43,
		monitor.PowerWatts:      89,
		// monitor.PowerPercent:    0,
	}

	assert.Equal(t, expected, parsedStats)
}

func TestGPUAMD_SampleMetrics(t *testing.T) {
	gpu := monitor.NewGPUAMD(nil)
	if !gpu.IsAvailable() {
		t.Skip("ROCm SMI command not found. Skipping test.")
	}

	gpu.SampleMetrics()
	assert.Len(t, gpu.Samples(), 1)
}

func TestGPUAMD_AggregateMetrics(t *testing.T) {
	gpu := monitor.NewGPUAMD(nil)
	if !gpu.IsAvailable() {
		t.Skip("ROCm SMI command not found. Skipping test.")
	}

	gpu.SampleMetrics()
	aggregates := gpu.AggregateMetrics()
	assert.NotNil(t, aggregates)
}

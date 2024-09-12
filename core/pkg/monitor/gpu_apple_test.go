//go:build darwin

package monitor_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/pkg/monitor"
)

const mockGPUStatsOutput = `{"m1Gpu1":57.583431243896484,"m3Gpu6":0,"m3Gpu2":0,"m3Gpu5":0,"vendor":"sppci_vendor_Apple","PC10":0,"m1Gpu3":55.276527404785156,"vram":"Unknown","recoveryCount":0,"m3Gpu7":0,"m1Gpu2":58.314537048339844,"cores":24,"gpuPowerPMVR":8.4271249771118164,"tilerUtilization":0,"m2Gpu2":0,"systemPower":19.567802429199219,"m1Gpu4":55.203269958496094,"m3Gpu4":0,"gpuCurrent":0,"PC22":0,"inUseSystemMemory":698499072,"m2Gpu1":0,"m3Gpu1":0,"renderUtilization":0,"PC20":0,"PC40":0,"PC12":0,"m3Gpu8":0,"m3Gpu3":0,"allocatedSystemMemory":3188637696,"name":"Apple M1 Max","utilization":29,"gpuPowerPGTR":0,"gpuVoltage":0,"gpuPower":0,"gpuPowerPG0R":0}`

func TestGPUAppleSample(t *testing.T) {
	tmpDir := t.TempDir()
	execPath := filepath.Join(tmpDir, "apple_gpu_stats")
	err := os.WriteFile(execPath, []byte("#!/bin/sh\necho '"+mockGPUStatsOutput+"'"), 0755)
	require.NoError(t, err)

	defer os.Remove(execPath)

	gpu := monitor.GPUApple{ExecPath: execPath}

	sample, err := gpu.Sample()
	require.NoError(t, err)

	assert.Equal(t, 0.0, sample["gpu.0.powerWatts"])
	assert.Equal(t, 19.567802429199219, sample["system.powerWatts"])
	assert.Equal(t, float64(0), sample["gpu.0.recoveryCount"])
	assert.Equal(t, float64(29), sample["gpu.0.gpu"])
	assert.Equal(t, float64(3188637696), sample["gpu.0.memoryAllocatedBytes"])
	assert.Equal(t, float64(698499072), sample["gpu.0.memoryUsed"])
	assert.InDelta(t, 56.59444141387939, sample["gpu.0.temp"], 0.00001) // Average of m1Gpu1, m1Gpu2, m1Gpu3, m1Gpu4
}

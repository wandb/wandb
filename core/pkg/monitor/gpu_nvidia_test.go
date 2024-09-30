//go:build linux

package monitor_test

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/pkg/monitor"
)

func TestGPUNvidiaSampleProbe(t *testing.T) {
	// Create a temporary directory to hold the fake binary.
	tempDir, err := os.MkdirTemp("", "monitor_test")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Create the fake nvidia_gpu_stats binary.
	fakeBinaryPath := filepath.Join(tempDir, "nvidia_gpu_stats")
	fakeJSONOutput := `{"_gpu.0.architecture":"Turing","_gpu.0.brand":"Nvidia","_gpu.0.cudaCores":2560,"_gpu.0.maxPcieLinkGen":3,"_gpu.0.maxPcieLinkWidth":16,"_gpu.0.memoryTotal":16106127360,"_gpu.0.pcieLinkGen":1,"_gpu.0.pcieLinkSpeed":2500000000,"_gpu.0.pcieLinkWidth":16,"_gpu.count":1,"_timestamp":1727467878.0665624,"cuda_version":"12.2","gpu.0.correctedMemoryErrors":0,"gpu.0.enforcedPowerLimitWatts":70.0,"gpu.0.gpu":0,"gpu.0.memory":0,"gpu.0.memoryAllocated":1.6800944010416665,"gpu.0.memoryAllocatedBytes":270598144,"gpu.0.memoryClock":405,"_gpu.0.name":"Tesla T4","gpu.0.powerPercent":17.87,"gpu.0.powerWatts":12.509,"gpu.0.smClock":300,"gpu.0.temp":59,"gpu.0.uncorrectedMemoryErrors":0}` + "\n"

	if err := createFakeBinary(fakeBinaryPath, fakeJSONOutput); err != nil {
		t.Fatalf("Failed to create fake binary: %v", err)
	}

	// Set up the logger.
	logger := observability.NewNoOpLogger()

	// Use the fake binary path in the NewGPUNvidia function.
	pid := int32(os.Getpid())
	samplingInterval := 0.1 // Set a short interval for the test.

	gpuMonitor := monitor.NewGPUNvidia(logger, pid, samplingInterval, fakeBinaryPath)
	if gpuMonitor == nil {
		t.Fatal("Failed to create GPUNvidia monitor")
	}
	defer gpuMonitor.Close()

	// Wait for the monitor to collect data.
	time.Sleep(500 * time.Millisecond)

	// Test the Sample method.
	metrics, err := gpuMonitor.Sample()
	if err != nil {
		t.Fatalf("Sample returned error: %v", err)
	}
	if len(metrics) == 0 {
		t.Fatal("Sample returned no metrics")
	}

	// Check for expected metrics.
	expectedMetrics := []string{
		"gpu.0.correctedMemoryErrors",
		"gpu.0.enforcedPowerLimitWatts",
		"gpu.0.gpu",
		"gpu.0.memory",
		"gpu.0.memoryAllocated",
		"gpu.0.memoryAllocatedBytes",
		"gpu.0.memoryClock",
		"gpu.0.powerPercent",
		"gpu.0.powerWatts",
		"gpu.0.smClock",
		"gpu.0.temp",
		"gpu.0.uncorrectedMemoryErrors",
	}

	for _, metric := range expectedMetrics {
		if _, ok := metrics[metric]; !ok {
			t.Errorf("Metric %s not found in metrics", metric)
		}
	}

	// Test the Probe method.
	metadata := gpuMonitor.Probe()
	if metadata == nil {
		t.Fatal("Probe returned nil metadata")
	}
	if metadata.GpuCount != 1 {
		t.Errorf("Expected GpuCount to be 1, got %d", metadata.GpuCount)
	}
	if metadata.CudaVersion != "12.2" {
		t.Errorf("Expected CudaVersion to be '12.2', got '%s'", metadata.CudaVersion)
	}
	if len(metadata.GpuNvidia) != 1 {
		t.Errorf("Expected 1 GpuNvidia entry, got %d", len(metadata.GpuNvidia))
	}
	if metadata.GpuType != "[Tesla T4]" {
		t.Errorf("Expected GpuType to be '[Tesla T4]', got '%s'", metadata.GpuType)
	}
}

// createFakeBinary creates a fake nvidia_gpu_stats binary that outputs the provided JSON.
func createFakeBinary(path, output string) error {
	// For simplicity, we'll create a shell script that echoes the output.
	scriptContent := "#!/bin/sh\n"
	scriptContent += "while true; do\n"
	scriptContent += "  echo '" + output + "'\n"
	scriptContent += "  sleep 0.1\n"
	scriptContent += "done\n"

	if err := os.WriteFile(path, []byte(scriptContent), 0755); err != nil {
		return err
	}
	return nil
}

//go:build linux

package monitor

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/wandb/wandb/core/pkg/monitor/tpuproto"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/local"
)

const (
	// googleTPUVendorID is the PCI vendor ID assigned to Google TPUs.
	googleTPUVendorID = "0x1ae0"
)

// MetricName represents a TPU metric name for querying on the gRPC server exposed by the TPU runtime.
type MetricName string

const (
	// grpcAddr is the gRPC server address for the TPU runtime.
	//
	// See https://github.com/dmitryduev/cloud-accelerator-diagnostics/tree/main/tpu_info for more details.
	grpcAddr = "localhost:8431"
	// TOTAL_MEMORY is the total High Bandwidth Memory in bytes.
	TOTAL_MEMORY MetricName = "tpu.runtime.hbm.memory.total.bytes"
	// MEMORY_USAGE is the current High Bandwidth Memory usage in bytes.
	MEMORY_USAGE MetricName = "tpu.runtime.hbm.memory.usage.bytes"
	// DUTY_CYCLE_PCT is the TensorCore duty cycle percentage.
	DUTY_CYCLE_PCT MetricName = "tpu.runtime.tensorcore.dutycycle.percent"
)

// TPUChip represents TPU chip specifications.
type TPUChip struct {
	name           string // The name of the TPU chip (e.g., "v2", "v3").
	hbmGiB         int    // High Bandwidth Memory in GiB
	devicesPerChip int    // Number of devices per chip
}

// TPU represents a TPU asset with gRPC connection and client.
type TPU struct {
	// Name of the TPU asset used to identify the asset in the metadata.
	name string

	// gRPC client connection and client for runtime metrics.
	//
	// TPU runtime metrics are exposed via a gRPC server running on a Google Cloud TPU VM.
	conn   *grpc.ClientConn
	client tpuproto.RuntimeMetricServiceClient

	// TPU chip specifications.
	chip *TPUChip

	// Total number of TPU devices detected.
	count int
}

// NewTPU creates a new TPU instance by detecting local TPU chips and initializing the gRPC connection.
func NewTPU() *TPU {
	t := &TPU{name: "tpu"}

	chip, count := getLocalTPUChips()
	if chip == nil {
		return nil
	}
	t.chip = chip
	t.count = count

	conn, err := grpc.NewClient(grpcAddr, grpc.WithTransportCredentials(local.NewCredentials()))
	if err != nil {
		return nil
	}
	client := tpuproto.NewRuntimeMetricServiceClient(conn)
	t.conn = conn
	t.client = client

	return t
}

func (t *TPU) Name() string {
	return t.name
}

// Sample returns TPU metrics such as memory usage in % and in bytes, and duty cycle.
func (t *TPU) Sample() (map[string]any, error) {
	if t.client == nil || t.chip == nil {
		return nil, nil
	}

	// Total memory per TPU core [bytes]
	totals, err := t.getMetrics(TOTAL_MEMORY)
	if err != nil {
		return nil, err
	}
	// Memory usage per TPU core [bytes]
	usages, err := t.getMetrics(MEMORY_USAGE)
	if err != nil {
		return nil, err
	}
	// Duty cycle per TPU device [%]
	dutyCycles, err := t.getMetrics(DUTY_CYCLE_PCT)
	if err != nil {
		return nil, err
	}

	// See below for the expected number of metrics per chip
	if len(totals) != len(usages) || len(usages) != len(dutyCycles)*t.chip.devicesPerChip {
		return nil, fmt.Errorf("tpu: metrics not found for all chips")
	}

	memoryUsages := make(map[int64]int64)
	for _, usage := range usages {
		deviceID := usage.GetAttribute().GetValue().GetIntAttr()
		memoryUsage := usage.GetGauge().GetAsInt()
		memoryUsages[deviceID] = memoryUsage
	}

	totalMemories := make(map[int64]int64)
	for _, total := range totals {
		deviceID := total.GetAttribute().GetValue().GetIntAttr()
		totalMemory := total.GetGauge().GetAsInt()
		totalMemories[deviceID] = totalMemory
	}

	// Duty cycle is measured per chip; distribute it to each device (core) in the chip.
	dutyCyclesPerCore := make(map[int64]float64)
	for _, duty := range dutyCycles {
		chipID := duty.GetAttribute().GetValue().GetIntAttr()
		dutyCycle := duty.GetGauge().GetAsDouble()
		dutyCyclesPerCore[chipID*int64(t.chip.devicesPerChip)] = dutyCycle
		dutyCyclesPerCore[chipID*int64(t.chip.devicesPerChip)+1] = dutyCycle
	}

	data := make(map[string]any)

	for deviceID := int64(0); deviceID < int64(t.count); deviceID++ {
		memoryUsage, ok := memoryUsages[deviceID]
		if !ok {
			continue
		}

		totalMemory, ok := totalMemories[deviceID]
		if !ok {
			continue
		}

		dutyCycle, ok := dutyCyclesPerCore[deviceID]
		if !ok {
			continue
		}

		// Memory usage [%]
		memoryUsageKey := fmt.Sprintf("%s.%d.memoryUsage", t.Name(), deviceID)
		// Memory usage [bytes]
		memoryUsageBytesKey := fmt.Sprintf("%s.%d.memoryUsageBytes", t.Name(), deviceID)
		// Duty cycle [%]
		dutyCycleKey := fmt.Sprintf("%s.%d.dutyCycle", t.Name(), deviceID)

		data[memoryUsageKey] = float64(memoryUsage) / float64(totalMemory) * 100
		data[memoryUsageBytesKey] = memoryUsage
		data[dutyCycleKey] = dutyCycle
	}

	return data, nil
}

func (t *TPU) IsAvailable() bool {
	return t.chip != nil
}

// Close closes the gRPC connection and releases resources.
func (t *TPU) Close() {
	if t.conn != nil {
		t.conn.Close()
		t.conn = nil
		t.client = nil
	}
}

// getLocalTPUChips scans the PCI devices to detect local TPU chips and
// returns the most common chip type and the total count.
func getLocalTPUChips() (*TPUChip, int) {
	devices, err := filepath.Glob("/sys/bus/pci/devices/*")
	if err != nil {
		return nil, 0
	}

	counter := make(map[*TPUChip]int)

	for _, pciPath := range devices {
		vendorPath := filepath.Join(pciPath, "vendor")
		data, err := os.ReadFile(vendorPath)
		if err != nil {
			continue
		}
		vendorId := strings.TrimSpace(string(data))
		if vendorId != googleTPUVendorID {
			continue
		}

		devicePath := filepath.Join(pciPath, "device")
		data, err = os.ReadFile(devicePath)
		if err != nil {
			continue
		}
		deviceId := strings.TrimSpace(string(data))

		subsystemPath := filepath.Join(pciPath, "subsystem_device")
		data, err = os.ReadFile(subsystemPath)
		if err != nil {
			continue
		}
		subsystemId := strings.TrimSpace(string(data))

		chipType, err := tpuChipFromPCIDeviceID(deviceId, subsystemId)
		if err != nil {
			continue
		}

		counter[chipType]++
	}

	if len(counter) == 0 {
		return nil, 0
	}

	var mostCommonChip *TPUChip
	var maxCount int
	for chip, count := range counter {
		if count > maxCount {
			mostCommonChip = chip
			maxCount = count
		}
	}
	return mostCommonChip, maxCount
}

func tpuChipFromPCIDeviceID(deviceId, subsystemId string) (*TPUChip, error) {
	switch deviceId {
	case "0x0027":
		switch subsystemId {
		case "0x004e":
			return &TPUChip{name: "v2", hbmGiB: 8, devicesPerChip: 2}, nil
		case "0x004f":
			return &TPUChip{name: "v3", hbmGiB: 16, devicesPerChip: 2}, nil
		}
	case "0x005e":
		return &TPUChip{name: "v4", hbmGiB: 32, devicesPerChip: 1}, nil
	case "0x0063":
		return &TPUChip{name: "v5e", hbmGiB: 16, devicesPerChip: 1}, nil
	case "0x0062":
		return &TPUChip{name: "v5p", hbmGiB: 95, devicesPerChip: 1}, nil
	}

	return nil, fmt.Errorf("unknown TPU chip")
}

// getMetrics retrieves metrics from the TPU runtime gRPC service for the given metric name.
func (t *TPU) getMetrics(metricName MetricName) ([]*tpuproto.Metric, error) {
	req := &tpuproto.MetricRequest{MetricName: string(metricName)}

	resp, err := t.client.GetRuntimeMetric(context.Background(), req)
	if err != nil {
		return nil, err
	}
	metrics := resp.Metric.Metrics

	return metrics, nil
}

// Probe returns the TPU metadata.
func (t *TPU) Probe() *spb.MetadataRequest {
	if t.chip == nil {
		return nil
	}

	return &spb.MetadataRequest{
		Tpu: &spb.TPUInfo{
			Name:           t.chip.name,
			Count:          uint32(t.count),
			HbmGib:         uint32(t.chip.hbmGiB),
			DevicesPerChip: uint32(t.chip.devicesPerChip),
		},
	}
}

// getSupportedMetrics retrieves the list of supported metrics from the TPU runtime gRPC service.
func (t *TPU) getSupportedMetrics() (*tpuproto.ListSupportedMetricsResponse, error) {
	ListSupportedMetricsRequest := &tpuproto.ListSupportedMetricsRequest{}
	resp, err := t.client.ListSupportedMetrics(context.Background(), ListSupportedMetricsRequest)
	if err != nil {
		return nil, err
	}

	return resp, nil
}

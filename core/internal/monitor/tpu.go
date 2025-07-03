//go:build linux

package monitor

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/wandb/wandb/core/internal/monitor/tpuproto"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/local"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// TPUMetricName represents a TPU metric name for querying on the gRPC server exposed by the TPU runtime.
type TPUMetricName string

const (
	// googleTPUVendorID is the PCI vendor ID assigned to Google TPUs.
	googleTPUVendorID = "0x1ae0"

	// grpcAddr is the gRPC server address for the TPU runtime.
	//
	// See https://github.com/google/cloud-accelerator-diagnostics/tree/main/tpu_info for more details.
	grpcAddr = "localhost:8431"

	// TPUTotalMemory is the total High Bandwidth Memory in bytes.
	TPUTotalMemory TPUMetricName = "tpu.runtime.hbm.memory.total.bytes"
	// TPUMemoryUsage is the current High Bandwidth Memory usage in bytes.
	TPUMemoryUsage TPUMetricName = "tpu.runtime.hbm.memory.usage.bytes"
	// TPUDutyCyclePct is the TensorCore duty cycle percentage.
	TPUDutyCyclePct TPUMetricName = "tpu.runtime.tensorcore.dutycycle.percent"
)

// TPUChip represents TPU chip specifications.
type TPUChip struct {
	Name           string // The name of the TPU chip (e.g., "v2", "v3").
	HbmGiB         int    // High Bandwidth Memory in GiB
	DevicesPerChip int    // Number of devices per chip
}

type RuntimeMetricServiceClient interface {
	GetRuntimeMetric(ctx context.Context, in *tpuproto.MetricRequest, opts ...grpc.CallOption) (*tpuproto.MetricResponse, error)
}

// TPU represents a TPU resource with gRPC connection and client.
//
// This code is based on Google's Cloud Accelerator Diagnostics project:
// https://github.com/google/cloud-accelerator-diagnostics.
type TPU struct {
	// gRPC client connection and client for runtime metrics.
	//
	// TPU runtime metrics are exposed via a gRPC server running on a Google Cloud TPU VM.
	conn   *grpc.ClientConn
	client RuntimeMetricServiceClient

	// TPU chip specifications.
	chip TPUChip

	// Total number of TPU devices detected.
	count int
}

// NewTPU creates a new TPU instance by detecting local TPU chips and initializing the gRPC connection.
func NewTPU() *TPU {
	t := &TPU{}

	chip, count := getLocalTPUChips()
	if count == 0 {
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

func (t *TPU) SetChip(chip TPUChip, count int) {
	t.chip = chip
	t.count = count
}

func (t *TPU) SetClient(client RuntimeMetricServiceClient) {
	t.client = client
}

// Sample returns TPU metrics such as memory usage in % and in bytes, and duty cycle.
func (t *TPU) Sample() (*spb.StatsRecord, error) {
	if t.client == nil {
		return nil, fmt.Errorf("TPU client is not initialized")
	}

	// Total memory per TPU core [bytes]
	totals, err := t.getMetrics(TPUTotalMemory)
	if err != nil {
		return nil, err
	}
	// Memory usage per TPU core [bytes]
	usages, err := t.getMetrics(TPUMemoryUsage)
	if err != nil {
		return nil, err
	}
	// Duty cycle per TPU device [%]
	dutyCycles, err := t.getMetrics(TPUDutyCyclePct)
	if err != nil {
		return nil, err
	}

	// Map to store all unique device IDs we encounter
	deviceIDs := make(map[int64]bool)

	// Collect all device IDs from memory usage metrics
	memoryUsages := make(map[int64]int64)
	for _, usage := range usages {
		deviceID := usage.GetAttribute().GetValue().GetIntAttr()
		memoryUsage := usage.GetGauge().GetAsInt()
		memoryUsages[deviceID] = memoryUsage
		deviceIDs[deviceID] = true
	}

	totalMemories := make(map[int64]int64)
	for _, total := range totals {
		deviceID := total.GetAttribute().GetValue().GetIntAttr()
		totalMemory := total.GetGauge().GetAsInt()
		totalMemories[deviceID] = totalMemory
		deviceIDs[deviceID] = true
	}

	dutyCyclesPerCore := make(map[int64]float64)
	for _, duty := range dutyCycles {
		deviceID := duty.GetAttribute().GetValue().GetIntAttr()
		dutyCycle := duty.GetGauge().GetAsDouble()
		if t.chip.DevicesPerChip == 2 {
			// For v2/v3 chips, distribute duty cycle to both devices
			dutyCyclesPerCore[deviceID*2] = dutyCycle
			dutyCyclesPerCore[deviceID*2+1] = dutyCycle
		} else {
			// For v4+ chips, 1:1 mapping between devices and duty cycles
			dutyCyclesPerCore[deviceID] = dutyCycle
		}
	}

	metrics := make(map[string]any)

	for deviceID := range deviceIDs {
		// Memory usage [%]
		memoryUsageKey := fmt.Sprintf("tpu.%d.memoryUsage", deviceID)
		// Memory usage [bytes]
		memoryUsageBytesKey := fmt.Sprintf("tpu.%d.memoryUsageBytes", deviceID)
		// Duty cycle [%]
		dutyCycleKey := fmt.Sprintf("tpu.%d.dutyCycle", deviceID)

		if memoryUsage, ok := memoryUsages[deviceID]; ok {
			metrics[memoryUsageBytesKey] = memoryUsage
			if totalMemory, ok := totalMemories[deviceID]; ok {
				metrics[memoryUsageKey] = float64(memoryUsage) / float64(totalMemory) * 100
			}
		}

		if dutyCycle, ok := dutyCyclesPerCore[deviceID]; ok {
			metrics[dutyCycleKey] = dutyCycle
		}
	}

	if len(metrics) == 0 {
		return nil, fmt.Errorf("no metrics available")
	}

	return marshal(metrics, timestamppb.Now()), nil
}

// Close closes the gRPC connection and releases resources.
func (t *TPU) Close() {
	if t.conn != nil {
		_ = t.conn.Close()
		t.conn = nil
		t.client = nil
	}
}

// getLocalTPUChips scans the PCI devices to detect local TPU chips and
// returns the most common chip type and the total count.
func getLocalTPUChips() (TPUChip, int) {
	devices, err := filepath.Glob("/sys/bus/pci/devices/*")
	if err != nil {
		return TPUChip{}, 0
	}

	counter := make(map[TPUChip]int)

	for _, pciPath := range devices {
		vendorPath := filepath.Join(pciPath, "vendor")
		data, err := os.ReadFile(vendorPath)
		if err != nil {
			continue
		}
		vendorID := strings.TrimSpace(string(data))
		if vendorID != googleTPUVendorID {
			continue
		}

		devicePath := filepath.Join(pciPath, "device")
		data, err = os.ReadFile(devicePath)
		if err != nil {
			continue
		}
		deviceID := strings.TrimSpace(string(data))

		subsystemPath := filepath.Join(pciPath, "subsystem_device")
		data, err = os.ReadFile(subsystemPath)
		if err != nil {
			continue
		}
		subsystemID := strings.TrimSpace(string(data))

		chipType, err := tpuChipFromPCIDeviceID(deviceID, subsystemID)
		if err != nil {
			continue
		}

		counter[chipType]++
	}

	if len(counter) == 0 {
		return TPUChip{}, 0
	}

	var mostCommonChip TPUChip
	var maxCount int
	for chip, count := range counter {
		if count > maxCount {
			mostCommonChip = chip
			maxCount = count
		}
	}
	return mostCommonChip, maxCount
}

func tpuChipFromPCIDeviceID(deviceID, subsystemID string) (TPUChip, error) {
	switch deviceID {
	case "0x0027":
		switch subsystemID {
		case "0x004e":
			return TPUChip{Name: "v2", HbmGiB: 8, DevicesPerChip: 2}, nil
		case "0x004f":
			return TPUChip{Name: "v3", HbmGiB: 16, DevicesPerChip: 2}, nil
		}
	case "0x005e":
		return TPUChip{Name: "v4", HbmGiB: 32, DevicesPerChip: 1}, nil
	case "0x0063":
		return TPUChip{Name: "v5e", HbmGiB: 16, DevicesPerChip: 1}, nil
	case "0x0062":
		return TPUChip{Name: "v5p", HbmGiB: 95, DevicesPerChip: 1}, nil
	case "0x006f":
		return TPUChip{Name: "v6e", HbmGiB: 32, DevicesPerChip: 1}, nil
	}

	return TPUChip{}, fmt.Errorf("unknown TPU chip")
}

// getMetrics retrieves metrics from the TPU runtime gRPC service for the given metric name.
func (t *TPU) getMetrics(metricName TPUMetricName) ([]*tpuproto.Metric, error) {
	req := &tpuproto.MetricRequest{MetricName: string(metricName)}

	resp, err := t.client.GetRuntimeMetric(context.Background(), req)
	if err != nil {
		return nil, err
	}
	metrics := resp.Metric.Metrics

	return metrics, nil
}

// Probe returns the TPU metadata.
func (t *TPU) Probe(_ context.Context) *spb.EnvironmentRecord {
	if t.count == 0 {
		return nil
	}

	return &spb.EnvironmentRecord{
		Tpu: &spb.TPUInfo{
			Name:           t.chip.Name,
			Count:          uint32(t.count),
			HbmGib:         uint32(t.chip.HbmGiB),
			DevicesPerChip: uint32(t.chip.DevicesPerChip),
		},
	}
}

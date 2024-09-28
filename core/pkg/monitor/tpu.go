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
	googleTPUVendorID = "0x1ae0"
)

type MetricName string

const (
	TOTAL_MEMORY   MetricName = "tpu.runtime.hbm.memory.total.bytes"
	MEMORY_USAGE   MetricName = "tpu.runtime.hbm.memory.usage.bytes"
	DUTY_CYCLE_PCT MetricName = "tpu.runtime.tensorcore.dutycycle.percent"
)

// Usage represents usage measurements for a TPU device.
type Usage struct {
	DeviceID     int
	MemoryUsage  int64
	TotalMemory  int64
	DutyCyclePct float64
}

// TPUChip represents TPU chip specifications.
type TPUChip struct {
	name           string
	hbmGib         int // High Bandwidth Memory in GiB
	devicesPerChip int // Number of devices per chip
}

// TPU represents a TPU asset with gRPC connection and client.
type TPU struct {
	name   string
	conn   *grpc.ClientConn
	client tpuproto.RuntimeMetricServiceClient
	chip   *TPUChip
	count  int
}

func NewTPU() *TPU {
	t := &TPU{name: "tpu"}

	// Get TPU chip information
	chip, count := getLocalTPUChips()
	if chip == nil {
		return nil
	}

	t.chip = chip
	t.count = count

	// Initialize gRPC connection and client
	addr := "localhost:8431"
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(local.NewCredentials()))
	if err != nil {
		return nil
	}
	client := tpuproto.NewRuntimeMetricServiceClient(conn)

	t.conn = conn
	t.client = client

	return t
}

func (t *TPU) getSupportedMetrics() (*tpuproto.ListSupportedMetricsResponse, error) {
	ListSupportedMetricsRequest := &tpuproto.ListSupportedMetricsRequest{}
	resp, err := t.client.ListSupportedMetrics(context.Background(), ListSupportedMetricsRequest)
	if err != nil {
		return nil, err
	}

	return resp, nil
}

func (t *TPU) Name() string {
	return t.name
}

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

	// Duty cycle is always measured per-chip, while memory is measured per-core.
	// We need to multiplex the duty cycle value for each core in the chip.
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

		data[memoryUsageKey] = memoryUsage / totalMemory * 100
		data[memoryUsageBytesKey] = memoryUsage
		data[dutyCycleKey] = dutyCycle
	}

	return data, nil
}

func (t *TPU) IsAvailable() bool {
	return t.chip != nil
}

func (t *TPU) Close() {
	if t.conn != nil {
		t.conn.Close()
		t.conn = nil
		t.client = nil
	}
}

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
			return &TPUChip{name: "v2", hbmGib: 8, devicesPerChip: 2}, nil
		case "0x004f":
			return &TPUChip{name: "v3", hbmGib: 16, devicesPerChip: 2}, nil
		}
	case "0x005e":
		return &TPUChip{name: "v4", hbmGib: 32, devicesPerChip: 1}, nil
	case "0x0063":
		return &TPUChip{name: "v5e", hbmGib: 16, devicesPerChip: 1}, nil
	case "0x0062":
		return &TPUChip{name: "v5p", hbmGib: 95, devicesPerChip: 1}, nil
	}

	return nil, fmt.Errorf("unknown TPU chip")
}

func (t *TPU) getMetrics(metricName MetricName) ([]*tpuproto.Metric, error) {
	req := &tpuproto.MetricRequest{MetricName: string(metricName)}

	resp, err := t.client.GetRuntimeMetric(context.Background(), req)
	if err != nil {
		return nil, err
	}
	metrics := resp.Metric.Metrics

	return metrics, nil
}

func (t *TPU) Probe() *spb.MetadataRequest {
	if t.chip == nil {
		return nil
	}

	return &spb.MetadataRequest{
		Tpu: &spb.TPUInfo{
			Name:           t.chip.name,
			Count:          uint32(t.count),
			HbmGib:         uint32(t.chip.hbmGib),
			DevicesPerChip: uint32(t.chip.devicesPerChip),
		},
	}
}

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
	"google.golang.org/grpc/credentials/insecure"
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
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
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

func (t *TPU) Sample() (map[string]any, error) {
	if t.client == nil || t.chip == nil {
		return nil, nil
	}

	totals, err := t.sortedMetricResponse(TOTAL_MEMORY)
	if err != nil {
		fmt.Println("error getting total memory", err)
		return nil, err
	}
	usages, err := t.sortedMetricResponse(MEMORY_USAGE)
	if err != nil {
		fmt.Println("error getting memory usage", err)
		return nil, err
	}
	dutyCycles, err := t.sortedMetricResponse(DUTY_CYCLE_PCT)
	if err != nil {
		fmt.Println("error getting duty cycle", err)
		return nil, err
	}

	fmt.Println(totals, usages, dutyCycles)

	// Duty cycle is always measured per-chip, while memory is measured per-core.
	// Repeat if necessary so these responses are the same length.
	var dutyCyclePerCore []*tpuproto.Metric
	for _, d := range dutyCycles {
		for i := 0; i < t.chip.devicesPerChip; i++ {
			dutyCyclePerCore = append(dutyCyclePerCore, d)
		}
	}

	if len(totals) != len(usages) || len(usages) != len(dutyCyclePerCore) {
		return nil, fmt.Errorf("metrics not found for all chips")
	}

	var usageList []Usage
	for i := 0; i < len(usages); i++ {
		u := usages[i]
		total := totals[i]
		duty := dutyCyclePerCore[i]

		fmt.Println(u, total, duty)

		// usage := Usage{
		// 	DeviceID:     int(u.Attribute.Value.Attr),
		// 	MemoryUsage:  u.Gauge.AsInt,
		// 	TotalMemory:  total.Gauge.AsInt,
		// 	DutyCyclePct: duty.Gauge.AsDouble,
		// }
		// usageList = append(usageList, usage)
	}

	// Prepare the sample data to return
	data := make(map[string]any)
	data["usage"] = usageList

	fmt.Println(data)

	// return data, nil
	return nil, nil
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

	counter := make(map[string]*TPUChip)

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

		key := chipType.name
		counter[key] = chipType
	}

	if len(counter) == 0 {
		return nil, 0
	}

	// Assuming only one type of TPU chip is present
	for _, chip := range counter {
		return chip, chip.devicesPerChip
	}

	return nil, 0
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

func (t *TPU) sortedMetricResponse(metricName MetricName) ([]*tpuproto.Metric, error) {
	req := &tpuproto.MetricRequest{MetricName: string(metricName)}
	resp, err := t.client.GetRuntimeMetric(context.Background(), req)
	if err != nil {
		return nil, err
	}
	metrics := resp.Metric.Metrics

	// Sort metrics by Attribute.Value.IntAttr
	// sort.Slice(metrics, func(i, j int) bool {
	// 	return metrics[i].Attribute.Value.IntAttr < metrics[j].Attribute.Value.IntAttr
	// })

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

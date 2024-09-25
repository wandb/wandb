package monitor

import (
	"fmt"
	"os"
	"path/filepath"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	googleTPUVendorID = "0x1ae0"
)

// TPUChip represents TPU chip specifications.
type TPUChip struct {
	name           string
	hbmGib         int // High Bandwidth Memory in GiB
	devicesPerChip int // Number of devices per chip
}

type TPU struct {
	name string
}

func NewTPU() *TPU {
	t := &TPU{name: "tpu"}

	return t
}

func (t *TPU) Name() string {
	return t.name
}

func (t *TPU) Sample() (map[string]any, error) {
	return nil, nil
}

func (t *TPU) IsAvailable() bool {
	return true
}

func getLocalTPUChips() (*TPUChip, int) {
	devices, err := filepath.Glob("/sys/bus/pci/devices/*")
	if err != nil {
		return nil, 0
	}

	counter := make(map[*TPUChip]int)

	for _, pciPath := range devices {
		fmt.Println(pciPath)

		vendorPath := filepath.Join(pciPath, "vendor")
		data, err := os.ReadFile(vendorPath)
		if err != nil {
			continue
		}
		vendorId := string(data)
		if vendorId != googleTPUVendorID {
			continue
		}

		devicePath := filepath.Join(pciPath, "device")
		data, err = os.ReadFile(devicePath)
		if err != nil {
			continue
		}
		deviceId := string(data)

		subsystemPath := filepath.Join(pciPath, "subsystem_device")
		data, err = os.ReadFile(subsystemPath)
		if err != nil {
			continue
		}
		subsystemId := string(data)

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
	fmt.Println(mostCommonChip)
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

func (t *TPU) Probe() *spb.MetadataRequest {
	chip, count := getLocalTPUChips()
	fmt.Println(chip, count)

	return nil
}

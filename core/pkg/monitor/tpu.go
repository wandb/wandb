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
	return false
}

// func getLocalTPUChips() ([]string, int) {
// }

func chipTypeFromPCIDeviceID(deviceId, subsystemId string) string {
	return ""
}

func (t *TPU) Probe() *spb.MetadataRequest {

	devices, err := filepath.Glob("/sys/bus/pci/devices/*")
	if err != nil {
		return nil
	}

	counter := make(map[string]int)

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

		chipType := chipTypeFromPCIDeviceID(deviceId, subsystemId)
		if chipType == "" {
			continue
		}
		counter[chipType]++
	}

	if len(counter) == 0 {
		return nil
	}

	return nil
}

package monitor

import (
	"context"
	"fmt"
	"runtime"
	"strings"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/sensors"
	"google.golang.org/protobuf/types/known/timestamppb"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// CPU samples host-wide CPU metrics: the utilization of every logical core
// and the CPU temperature.
//
// Only the standalone system monitor registers it; runs do not collect
// these metrics yet.
type CPU struct{}

func NewCPU() *CPU {
	return &CPU{}
}

// Sample collects the utilization of each core since the previous call and
// the CPU temperature where the host exposes one.
func (c *CPU) Sample() (*spb.StatsRecord, error) {
	metrics := make(map[string]any)

	percents, err := cpu.Percent(0, true)
	for i, percent := range percents {
		metrics[fmt.Sprintf("cpu.%d.cpu_percent", i)] = percent
	}

	// On Apple Silicon the wandb-xpu sidecar reports the CPU temperature.
	// A partial hwmon read comes back with a non-nil error, so the error is
	// not a reason to drop the readings.
	if runtime.GOOS == "linux" {
		temps, _ := sensors.SensorsTemperatures()
		if temp, ok := cpuTemperature(temps); ok {
			metrics["cpu.avg_temp"] = temp
		}
	}

	if len(metrics) == 0 {
		return nil, err
	}
	return marshal(metrics, timestamppb.Now()), err
}

func (c *CPU) Probe(context.Context) *spb.EnvironmentRecord {
	return nil
}

// cpuTemperatureSensors lists hwmon sensor key prefixes that read the CPU
// temperature, most representative first: the package or die sensor, then
// the individual cores, then SoC thermal zones.
var cpuTemperatureSensors = [][]string{
	{"coretemp_package_id_", "k10temp_tdie", "zenpower_tdie"},
	{"k10temp_tctl", "zenpower_tctl"},
	{"coretemp_core_", "k10temp_tccd", "zenpower_tccd"},
	{"cpu_thermal", "cpu-thermal", "x86_pkg_temp", "soc_thermal"},
}

// cpuTemperature returns the mean reading of the most representative CPU
// temperature sensors present. Readings at or below 0 °C or above 150 °C
// are skipped: hwmon reports such values for sensors that are absent,
// unpowered or broken.
func cpuTemperature(temps []sensors.TemperatureStat) (float64, bool) {
	for _, prefixes := range cpuTemperatureSensors {
		var sum float64
		var n int
		for _, t := range temps {
			if t.Temperature <= 0 || t.Temperature > 150 {
				continue
			}
			for _, prefix := range prefixes {
				if strings.HasPrefix(t.SensorKey, prefix) {
					sum += t.Temperature
					n++
					break
				}
			}
		}
		if n > 0 {
			return sum / float64(n), true
		}
	}
	return 0, false
}

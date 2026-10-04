package monitor

import (
	"testing"

	"github.com/shirou/gopsutil/v4/sensors"
	"github.com/stretchr/testify/require"
)

func TestCPUTemperature(t *testing.T) {
	tests := []struct {
		name  string
		temps []sensors.TemperatureStat
		want  float64
		ok    bool
	}{
		{
			name: "package beats cores",
			temps: []sensors.TemperatureStat{
				{SensorKey: "coretemp_package_id_0", Temperature: 60},
				{SensorKey: "coretemp_core_0", Temperature: 50},
				{SensorKey: "coretemp_core_1", Temperature: 70},
				{SensorKey: "nvme_composite", Temperature: 40},
			},
			want: 60,
			ok:   true,
		},
		{
			name: "cores averaged when no package sensor",
			temps: []sensors.TemperatureStat{
				{SensorKey: "coretemp_core_0", Temperature: 50},
				{SensorKey: "coretemp_core_1", Temperature: 70},
			},
			want: 60,
			ok:   true,
		},
		{
			name: "invalid readings skipped",
			temps: []sensors.TemperatureStat{
				{SensorKey: "k10temp_tctl", Temperature: 0},
				{SensorKey: "k10temp_tccd1", Temperature: 55},
			},
			want: 55,
			ok:   true,
		},
		{
			name:  "no cpu sensor",
			temps: []sensors.TemperatureStat{{SensorKey: "acpitz", Temperature: 45}},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, ok := cpuTemperature(tt.temps)
			require.Equal(t, tt.ok, ok)
			require.InDelta(t, tt.want, got, 1e-9)
		})
	}
}

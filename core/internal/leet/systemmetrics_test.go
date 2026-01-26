package leet_test

import (
	"fmt"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func TestMatchMetricDef_BasicFamilies(t *testing.T) {
	cases := []struct {
		name     string
		metric   string
		wantName string
		wantUnit string
	}{
		{"CPU core %", "cpu.0.cpu_percent", "CPU Core", "%"},
		{"GPU temp", "gpu.1.temp", "GPU Temp", "°C"},
		{"Disk per-device I/O", "disk.disk4.in", "Disk I/O Total", "B"},
		{"Disk write total", "disk.out", "Disk Write Total", "B"},
		{"RAM used MB", "memory.used", "RAM Used", "B"},
		{"System memory %", "memory_percent", "System Memory", "%"},
		{"Network rx bytes", "network.recv", "Network Rx", "B"},
		{"Process GPU mem bytes", "gpu.process.3.memoryAllocatedBytes", "Process GPU Memory", "B"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			def := leet.MatchMetricDef(tc.metric)
			require.Equal(t,
				fmt.Sprintf("%s (%s)", tc.wantName, tc.wantUnit),
				def.Title(),
				"metric: %s",
				tc.metric,
			)
		})
	}
}

func TestExtractBaseKey(t *testing.T) {
	cases := []struct {
		in, want string
	}{
		{"gpu.0.temp", "gpu.temp"},
		{"gpu.0.temp/l:0:GPU0", "gpu.temp"},
		{"gpu.process.2.temp", "gpu.process.temp"},
		{"disk.disk4.out", "disk.io_per_device"},
		{"cpu.0.cpu_percent", "cpu.cpu_percent"},
		{"memory.used", "memory.used"},
	}
	for _, tc := range cases {
		got := leet.ExtractBaseKey(tc.in)
		require.Equal(t, tc.want, got, "input: %s", tc.in)
	}
}

func TestExtractSeriesName(t *testing.T) {
	t.Parallel()
	cases := []struct {
		in, want string
	}{
		{"gpu.3.temp", "GPU 3"},
		{"gpu.process.2.temp", "GPU Process 2"},
		{"cpu.2.cpu_percent", "CPU 2"},
		{"disk.disk4.in", "disk4 read"},
		{"disk.disk4.out", "disk4 write"},
		{"memory.used", "Default"},
	}
	for _, tc := range cases {
		got := leet.ExtractSeriesName(tc.in)
		require.Equal(t, tc.want, got, "input: %s", tc.in)
	}
}

func TestUnitFormat(t *testing.T) {
	cases := []struct {
		val  float64
		unit leet.UnitFormatter
		want string
	}{
		{0, leet.UnitPercent, "0"},
		{9.99, leet.UnitPercent, "9.99%"},
		{100, leet.UnitPercent, "100%"},
		{950, leet.UnitMHz, "950MHz"},
		{2500, leet.UnitMHz, "2.5GHz"},
		{1024, leet.UnitBytes, "1KiB"},
		{1536, leet.UnitBytes, "1.5KiB"},
		{512, leet.UnitMiB, "512MiB"},
		{1536, leet.UnitMiB, "1.5GiB"},
		{1048576, leet.UnitMiB, "1TiB"},
		{256, leet.UnitGiB, "256GiB"},
		{1536, leet.UnitGiB, "1.5TiB"},
		{2048, leet.UnitMiBps, "2.15GB/s"},
		{0.005, leet.UnitScalar, "0.005"},
		{0.5, leet.UnitScalar, "0.5"},
		{3.14, leet.UnitScalar, "3.14"},
		{-3.14, leet.UnitScalar, "-3.14"},
		{0.0000031415, leet.UnitScalar, "3.14e-06"},
		{1200, leet.UnitScalar, "1.2e+03"},
		{1200000, leet.UnitScalar, "1.2e+06"},
	}
	for _, tc := range cases {
		got := tc.unit.Format(tc.val)
		require.Equal(t, tc.want, got, "val: %.6g, unit: %q", tc.val, tc.unit)
	}
}

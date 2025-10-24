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
		{"Disk per-device I/O", "disk.disk4.in", "Disk I/O Total", "MB"},
		{"Disk write total", "disk.out", "Disk Write Total", "MB"},
		{"RAM used GB", "memory.used", "RAM Used", "GB"},
		{"System memory %", "memory_percent", "System Memory", "%"},
		{"Network rx bytes", "network.recv", "Network Rx", "B"},
		{"Process GPU mem bytes", "gpu.process.3.memoryAllocatedBytes", "Process GPU Memory", "GB"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			def := leet.MatchMetricDef(tc.metric)
			require.Equal(t, fmt.Sprintf("%s (%s)", tc.wantName, tc.wantUnit), def.Title(), "metric: %s", tc.metric)
			require.Equal(t, tc.wantUnit, def.Unit, "metric: %s", tc.metric)
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

func TestFormatYLabel(t *testing.T) {
	cases := []struct {
		val  float64
		unit string
		want string
	}{
		// Zero special-case
		{0, "%", "0"},
		{0, "°C", "0"},
		{0, "MB/s", "0"},
		// Percent
		{9.99, "%", "9.99%"},
		{85.5, "%", "85.5%"},
		{100, "%", "100%"},
		// Temperature
		{99.9, "°C", "99.9°C"},
		{100, "°C", "100°C"},
		// Frequency
		{950, "MHz", "950MHz"},
		{2500, "MHz", "2.5GHz"},
		// Bytes (binary prefixes)
		{1024, "B", "1KiB"},
		{1536, "B", "1.5KiB"},
		// MB (cumulative, humanized to GB/TB)
		{512, "MB", "512MiB"},
		{1536, "MB", "1.5GiB"},
		{1048576, "MB", "1TiB"},
		// GB (humanized to TB)
		{256, "GB", "256GiB"},
		{1536, "GB", "1.5TiB"},
		// Rates (decimal prefixes after converting to bytes/s)
		{2048, "MB/s", "2.1GB/s"},
		// Default units/precision
		{0.005, "", "5m"},
		{0.5, "", "0.5"},
		{3.14, "", "3.1"},
		{1200, "", "1.2k"},
		{1200000, "", "1.2M"},
	}
	for _, tc := range cases {
		got := leet.FormatYLabel(tc.val, tc.unit)
		require.Equal(t, tc.want, got, "val: %.6g, unit: %q", tc.val, tc.unit)
	}
}

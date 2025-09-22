package leet_test

import (
	"testing"

	"github.com/wandb/wandb/core/internal/leet"
)

func TestMatchMetricDef_BasicFamilies(t *testing.T) {
	t.Parallel()

	cases := []struct {
		name      string
		metric    string
		wantTitle string
		wantUnit  string
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
			if def.Title != tc.wantTitle || def.Unit != tc.wantUnit {
				t.Fatalf("MatchMetricDef(%q) => {%q,%q}; want {%q,%q}",
					tc.metric, def.Title, def.Unit, tc.wantTitle, tc.wantUnit)
			}
		})
	}
}

func TestExtractBaseKey(t *testing.T) {
	t.Parallel()

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
		if got := leet.ExtractBaseKey(tc.in); got != tc.want {
			t.Fatalf("ExtractBaseKey(%q)=%q; want %q", tc.in, got, tc.want)
		}
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
		if got := leet.ExtractSeriesName(tc.in); got != tc.want {
			t.Fatalf("ExtractSeriesName(%q)=%q; want %q", tc.in, got, tc.want)
		}
	}
}

func TestFormatYLabel(t *testing.T) {
	t.Parallel()

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
		{512, "MB", "512MB"},
		{1536, "MB", "1.5GB"},
		{1048576, "MB", "1TB"}, // 1024*1024 MB == 1 TB

		// GB (humanized to TB)
		{256, "GB", "256GB"},
		{1536, "GB", "1.5TB"},

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
		if got := leet.FormatYLabel(tc.val, tc.unit); got != tc.want {
			t.Fatalf("FormatYLabel(%.6g,%q)=%q; want %q", tc.val, tc.unit, got, tc.want)
		}
	}
}

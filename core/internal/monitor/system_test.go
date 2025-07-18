package monitor_test

import (
	"context"
	"reflect"
	"testing"

	"github.com/shirou/gopsutil/v4/disk"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/monitor"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestSLURMProbe(t *testing.T) {
	tests := []struct {
		name     string
		envVars  map[string]string
		expected *spb.EnvironmentRecord
	}{
		{
			name: "With SLURM environment variables",
			envVars: map[string]string{
				"SLURM_JOB_ID":   "12345",
				"SLURM_JOB_NAME": "test_job",
				"SOME_OTHER_VAR": "some_value",
			},
			expected: &spb.EnvironmentRecord{
				Slurm: map[string]string{
					"job_id":   "12345",
					"job_name": "test_job",
				},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Set up the test environment
			for k, v := range tt.envVars {
				t.Setenv(k, v)
			}

			slurm := monitor.NewSystem(monitor.SystemParams{Pid: 0, DiskPaths: []string{"/"}})
			result := slurm.Probe(context.Background())

			if !reflect.DeepEqual(result.Slurm, tt.expected.Slurm) {
				t.Errorf("Probe() = %v, want %v", result, tt.expected)
			}
		})
	}
}

func TestCollectDiskIOMetrics(t *testing.T) {
	origParts := monitor.DiskPartitions
	origIO := monitor.DiskIOCounters
	t.Cleanup(func() {
		monitor.DiskPartitions = origParts
		monitor.DiskIOCounters = origIO
	})

	monitor.DiskPartitions = func(all bool) ([]disk.PartitionStat, error) {
		return []disk.PartitionStat{
			{Device: "/dev/nvme0n1", Mountpoint: "/"},
		}, nil
	}

	baselineRead, baselineWrite := uint64(1_000_000), uint64(2_000_000)
	monitor.DiskIOCounters = func() (map[string]disk.IOCountersStat, error) {
		return map[string]disk.IOCountersStat{
			"nvme0n1": {ReadBytes: baselineRead, WriteBytes: baselineWrite},
		}, nil
	}

	sys := monitor.NewSystem(monitor.SystemParams{
		Pid:       0,
		DiskPaths: []string{"/"},
	})

	// advance counters by +5/10 MiB
	deltaRead, deltaWrite := uint64(5<<20), uint64(10<<20)
	monitor.DiskIOCounters = func() (map[string]disk.IOCountersStat, error) {
		return map[string]disk.IOCountersStat{
			"nvme0n1": {
				ReadBytes:  baselineRead + deltaRead,
				WriteBytes: baselineWrite + deltaWrite,
			},
		}, nil
	}

	metrics := make(map[string]any)
	err := sys.CollectDiskIOMetrics(metrics)
	require.NoError(t, err)

	wantInMB := float64(deltaRead) / 1024 / 1024
	wantOutMB := float64(deltaWrite) / 1024 / 1024

	gotIn, okIn := metrics["disk.nvme0n1.in"].(float64)
	gotOut, okOut := metrics["disk.nvme0n1.out"].(float64)
	require.True(t, okIn, "disk.nvme0n1.in missing")
	require.True(t, okOut, "disk.nvme0n1.out missing")

	require.InEpsilon(t, wantInMB, gotIn, 1e-6, "read MB")
	require.InEpsilon(t, wantOutMB, gotOut, 1e-6, "write MB")
}

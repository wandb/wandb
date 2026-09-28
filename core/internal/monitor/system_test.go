package monitor_test

import (
	"context"
	"os"
	"os/exec"
	"reflect"
	"testing"

	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/process"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/systemmetrics"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestSystemSample_ExitedProcess(t *testing.T) {
	child := exec.Command(os.Args[0], "-test.run=^$")
	require.NoError(t, child.Run())

	system := monitor.NewSystem(monitor.SystemParams{
		Pid: int32(child.Process.Pid),
	})
	_, err := system.Sample()
	require.ErrorIs(t, err, process.ErrorProcessNotRunning)
	require.False(t, monitor.ShouldCaptureSamplingError(err))
}

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

	host := &spb.HostMetrics{}
	require.NoError(t, sys.CollectDiskIOMetrics(host))

	require.Len(t, host.DiskIo, 1)
	require.Equal(t, "nvme0n1", host.DiskIo[0].GetDevice())
	require.Equal(t, deltaRead, host.DiskIo[0].GetReadBytes())
	require.Equal(t, deltaWrite, host.DiskIo[0].GetWriteBytes())

	// The legacy keys report MiB read and written.
	require.Equal(t, []systemmetrics.Item{
		{Key: "disk.nvme0n1.in", Value: 5},
		{Key: "disk.nvme0n1.out", Value: 10},
	}, systemmetrics.Items(&spb.SystemMetricsRecord{Host: host}))
}

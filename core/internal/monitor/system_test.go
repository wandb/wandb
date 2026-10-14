package monitor_test

import (
	"os"
	"os/exec"
	"testing"

	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/process"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/monitor"
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

package monitor

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestCgroupV2ResourceLimits(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cgroup")
	cgroupPath := filepath.Join(mountPoint, "kubepods", "pod123", "container456")

	writeTestFile(t, filepath.Join(root, "proc-cgroup"), "0::/kubepods/pod123/container456\n")
	writeTestFile(
		t,
		filepath.Join(root, "mountinfo"),
		fmt.Sprintf("1 0 0:1 / %s rw,relatime - cgroup2 cgroup rw\n", mountPoint),
	)
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.max"), fmt.Sprint(8*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.current"), fmt.Sprint(7*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(cgroupPath, "cpu.max"), "400000 100000")
	writeCgroupFile(t, filepath.Join(cgroupPath, "cpuset.cpus.effective"), "0-7")

	limits := detectCgroupResourceLimits(cgroupPaths{
		procCgroup:    filepath.Join(root, "proc-cgroup"),
		procMountInfo: filepath.Join(root, "mountinfo"),
	})
	require.NotNil(t, limits)

	current, limit, ok := limits.MemoryStats()
	require.True(t, ok)
	require.Equal(t, uint64(7*1024*1024*1024), current)
	require.Equal(t, uint64(8*1024*1024*1024), limit)
	require.InEpsilon(t, 4.0, limits.CPULimit(), 1e-9)

	sys := &System{cgroup: limits}
	metrics := make(map[string]any)
	_, _ = sys.collectSystemMemoryMetrics(metrics)

	require.InEpsilon(t, 87.5, metrics["memory_percent"], 1e-9)
	require.InEpsilon(t, 1024.0, metrics["proc.memory.availableMB"], 1e-9)
}

func TestCgroupV2MemoryLimitFromParent(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cgroup")
	podPath := filepath.Join(mountPoint, "kubepods", "pod123")
	containerPath := filepath.Join(podPath, "container456")

	writeTestFile(t, filepath.Join(root, "proc-cgroup"), "0::/kubepods/pod123/container456\n")
	writeTestFile(
		t,
		filepath.Join(root, "mountinfo"),
		fmt.Sprintf("1 0 0:1 / %s rw,relatime - cgroup2 cgroup rw\n", mountPoint),
	)
	writeCgroupFile(t, filepath.Join(containerPath, "memory.max"), "max")
	writeCgroupFile(t, filepath.Join(containerPath, "memory.current"), fmt.Sprint(2*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(podPath, "memory.max"), fmt.Sprint(8*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(podPath, "memory.current"), fmt.Sprint(6*1024*1024*1024))

	limits := detectCgroupResourceLimits(cgroupPaths{
		procCgroup:    filepath.Join(root, "proc-cgroup"),
		procMountInfo: filepath.Join(root, "mountinfo"),
	})
	require.NotNil(t, limits)

	current, limit, ok := limits.MemoryStats()
	require.True(t, ok)
	require.Equal(t, uint64(6*1024*1024*1024), current)
	require.Equal(t, uint64(8*1024*1024*1024), limit)
}

func TestCgroupStableLimitsAreCached(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cgroup")
	cgroupPath := filepath.Join(mountPoint, "kubepods", "pod123", "container456")
	memoryLimitPath := filepath.Join(cgroupPath, "memory.max")
	memoryCurrentPath := filepath.Join(cgroupPath, "memory.current")
	cpuLimitPath := filepath.Join(cgroupPath, "cpu.max")
	cpusetPath := filepath.Join(cgroupPath, "cpuset.cpus.effective")

	writeTestFile(t, filepath.Join(root, "proc-cgroup"), "0::/kubepods/pod123/container456\n")
	writeTestFile(
		t,
		filepath.Join(root, "mountinfo"),
		fmt.Sprintf("1 0 0:1 / %s rw,relatime - cgroup2 cgroup rw\n", mountPoint),
	)
	writeCgroupFile(t, memoryLimitPath, fmt.Sprint(8*1024*1024*1024))
	writeCgroupFile(t, memoryCurrentPath, fmt.Sprint(7*1024*1024*1024))
	writeCgroupFile(t, cpuLimitPath, "400000 100000")
	writeCgroupFile(t, cpusetPath, "0-7")

	limits := detectCgroupResourceLimits(cgroupPaths{
		procCgroup:    filepath.Join(root, "proc-cgroup"),
		procMountInfo: filepath.Join(root, "mountinfo"),
	})
	require.NotNil(t, limits)

	current, limit, ok := limits.MemoryStats()
	require.True(t, ok)
	require.Equal(t, uint64(7*1024*1024*1024), current)
	require.Equal(t, uint64(8*1024*1024*1024), limit)
	require.InEpsilon(t, 4.0, limits.CPULimit(), 1e-9)

	writeCgroupFile(t, memoryLimitPath, fmt.Sprint(4*1024*1024*1024))
	writeCgroupFile(t, memoryCurrentPath, fmt.Sprint(5*1024*1024*1024))
	writeCgroupFile(t, cpuLimitPath, "100000 100000")
	writeCgroupFile(t, cpusetPath, "0-1")

	current, limit, ok = limits.MemoryStats()
	require.True(t, ok)
	require.Equal(t, uint64(5*1024*1024*1024), current)
	require.Equal(t, uint64(8*1024*1024*1024), limit)
	require.InEpsilon(t, 4.0, limits.CPULimit(), 1e-9)

	memoryLimit, ok := limits.MemoryLimit()
	require.True(t, ok)
	require.Equal(t, uint64(8*1024*1024*1024), memoryLimit)
}

func TestCgroupV1ResourceLimits(t *testing.T) {
	root := t.TempDir()
	memoryMount := filepath.Join(root, "sys", "fs", "cgroup", "memory")
	cpuMount := filepath.Join(root, "sys", "fs", "cgroup", "cpu")
	cpusetMount := filepath.Join(root, "sys", "fs", "cgroup", "cpuset")

	writeTestFile(t, filepath.Join(root, "proc-cgroup"),
		"5:memory:/docker/abc\n4:cpu,cpuacct:/docker/abc\n3:cpuset:/docker/abc\n")
	writeTestFile(
		t,
		filepath.Join(root, "mountinfo"),
		fmt.Sprintf(
			"1 0 0:1 / %s rw - cgroup cgroup rw,memory\n2 0 0:2 / %s rw - cgroup cgroup rw,cpu,cpuacct\n3 0 0:3 / %s rw - cgroup cgroup rw,cpuset\n",
			memoryMount,
			cpuMount,
			cpusetMount,
		),
	)
	writeCgroupFile(t, filepath.Join(memoryMount, "docker", "abc", "memory.limit_in_bytes"),
		fmt.Sprint(4*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(memoryMount, "docker", "abc", "memory.usage_in_bytes"),
		fmt.Sprint(3*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(cpuMount, "docker", "abc", "cpu.cfs_quota_us"), "250000")
	writeCgroupFile(t, filepath.Join(cpuMount, "docker", "abc", "cpu.cfs_period_us"), "100000")
	writeCgroupFile(t, filepath.Join(cpusetMount, "docker", "abc", "cpuset.cpus"), "0-3")

	limits := detectCgroupResourceLimits(cgroupPaths{
		procCgroup:    filepath.Join(root, "proc-cgroup"),
		procMountInfo: filepath.Join(root, "mountinfo"),
	})
	require.NotNil(t, limits)

	current, limit, ok := limits.MemoryStats()
	require.True(t, ok)
	require.Equal(t, uint64(3*1024*1024*1024), current)
	require.Equal(t, uint64(4*1024*1024*1024), limit)
	require.InEpsilon(t, 2.5, limits.CPULimit(), 1e-9)
}

func TestCgroupUnlimitedValuesAreIgnored(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cgroup")
	cgroupPath := filepath.Join(mountPoint, "kubepods", "pod123")

	writeTestFile(t, filepath.Join(root, "proc-cgroup"), "0::/kubepods/pod123\n")
	writeTestFile(
		t,
		filepath.Join(root, "mountinfo"),
		fmt.Sprintf("1 0 0:1 / %s rw,relatime - cgroup2 cgroup rw\n", mountPoint),
	)
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.max"), "max")
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.current"), "123")
	writeCgroupFile(t, filepath.Join(cgroupPath, "cpu.max"), "max 100000")

	limits := detectCgroupResourceLimits(cgroupPaths{
		procCgroup:    filepath.Join(root, "proc-cgroup"),
		procMountInfo: filepath.Join(root, "mountinfo"),
	})
	require.NotNil(t, limits)

	_, _, ok := limits.MemoryStats()
	require.False(t, ok)
	require.Zero(t, limits.CPULimit())
}

func TestCountCPUSet(t *testing.T) {
	require.Equal(t, 7, countCPUSet("0-3,8,10-11"))
	require.Equal(t, 1, countCPUSet("4"))
	require.Equal(t, 0, countCPUSet(""))
	require.Equal(t, 0, countCPUSet("3-1"))
}

func writeTestFile(t *testing.T, path, value string) {
	t.Helper()
	require.NoError(t, os.MkdirAll(filepath.Dir(path), 0o755))
	require.NoError(t, os.WriteFile(path, []byte(value), 0o644))
}

func writeCgroupFile(t *testing.T, path, value string) {
	t.Helper()
	writeTestFile(t, path, fmt.Sprintf("%s\n", value))
}

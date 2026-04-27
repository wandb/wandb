package monitor

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestCgroupV2ResourceLimits(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cgroup")
	cgroupPath := filepath.Join(mountPoint, "kubepods", "pod123", "container456")

	writeTestFile(t, testProcCgroupPath(root), "0::/kubepods/pod123/container456\n")
	writeTestFile(
		t,
		testProcMountInfoPath(root),
		fmt.Sprintf("1 0 0:1 / %s rw,relatime - cgroup2 cgroup rw\n", mountPoint),
	)
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.max"), fmt.Sprint(8*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.current"), fmt.Sprint(7*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(cgroupPath, "cpu.max"), "400000 100000")
	writeTestFile(t, testProcStatusPath(root), "Cpus_allowed_list:\t0-7\n")

	limits := detectCgroupResourceLimits(testCgroupPaths(root))
	require.NotNil(t, limits)

	current, limit, ok := limits.MemoryStats()
	require.True(t, ok)
	require.Equal(t, uint64(7*1024*1024*1024), current)
	require.Equal(t, uint64(8*1024*1024*1024), limit)
	require.InEpsilon(t, 4.0, limits.CPULimit(), 1e-9)

	sys := &System{cgroup: limits}
	metrics := make(map[string]any)
	denominator, err := sys.collectSystemMemoryMetrics(metrics)

	require.NoError(t, err)
	require.Equal(t, uint64(8*1024*1024*1024), denominator)
	require.InEpsilon(t, 87.5, metrics["memory_percent"], 1e-9)
	require.InEpsilon(t, 1024.0, metrics["proc.memory.availableMB"], 1e-9)
}

func TestCgroupV2MemoryLimitFromParent(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cgroup")
	podPath := filepath.Join(mountPoint, "kubepods", "pod123")
	containerPath := filepath.Join(podPath, "container456")

	writeTestFile(t, testProcCgroupPath(root), "0::/kubepods/pod123/container456\n")
	writeTestFile(
		t,
		testProcMountInfoPath(root),
		fmt.Sprintf("1 0 0:1 / %s rw,relatime - cgroup2 cgroup rw\n", mountPoint),
	)
	writeCgroupFile(t, filepath.Join(containerPath, "memory.max"), "max")
	writeCgroupFile(t, filepath.Join(containerPath, "memory.current"), fmt.Sprint(2*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(podPath, "memory.max"), fmt.Sprint(8*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(podPath, "memory.current"), fmt.Sprint(6*1024*1024*1024))

	limits := detectCgroupResourceLimits(testCgroupPaths(root))
	require.NotNil(t, limits)

	current, limit, ok := limits.MemoryStats()
	require.True(t, ok)
	require.Equal(t, uint64(6*1024*1024*1024), current)
	require.Equal(t, uint64(8*1024*1024*1024), limit)
}

func TestCgroupV2BindMountRoot(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cgroup")
	cgroupPath := filepath.Join(mountPoint, "container456")

	writeTestFile(t, testProcCgroupPath(root), "0::/kubepods/pod123/container456\n")
	writeTestFile(
		t,
		testProcMountInfoPath(root),
		fmt.Sprintf("1 0 0:1 /kubepods/pod123 %s rw,relatime - cgroup2 cgroup rw\n", mountPoint),
	)
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.max"), fmt.Sprint(8*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.current"), fmt.Sprint(7*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(cgroupPath, "cpu.max"), "400000 100000")

	limits := detectCgroupResourceLimits(testCgroupPaths(root))
	require.NotNil(t, limits)

	current, limit, ok := limits.MemoryStats()
	require.True(t, ok)
	require.Equal(t, uint64(7*1024*1024*1024), current)
	require.Equal(t, uint64(8*1024*1024*1024), limit)
	require.InEpsilon(t, 4.0, limits.CPULimit(), 1e-9)
}

func TestCgroupMountInfoEscapedPath(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cg space")
	escapedMountPoint := strings.ReplaceAll(mountPoint, " ", `\040`)
	cgroupPath := filepath.Join(mountPoint, "kubepods", "pod123")

	writeTestFile(t, testProcCgroupPath(root), "0::/kubepods/pod123\n")
	writeTestFile(
		t,
		testProcMountInfoPath(root),
		fmt.Sprintf("1 0 0:1 / %s rw,relatime - cgroup2 cgroup rw\n", escapedMountPoint),
	)
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.max"), fmt.Sprint(8*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.current"), fmt.Sprint(7*1024*1024*1024))

	limits := detectCgroupResourceLimits(testCgroupPaths(root))
	require.NotNil(t, limits)

	current, limit, ok := limits.MemoryStats()
	require.True(t, ok)
	require.Equal(t, uint64(7*1024*1024*1024), current)
	require.Equal(t, uint64(8*1024*1024*1024), limit)
}

func TestCgroupV2UsesSmallestAncestorLimits(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cgroup")
	podPath := filepath.Join(mountPoint, "kubepods", "pod123")
	containerPath := filepath.Join(podPath, "container456")

	writeTestFile(t, testProcCgroupPath(root), "0::/kubepods/pod123/container456\n")
	writeTestFile(
		t,
		testProcMountInfoPath(root),
		fmt.Sprintf("1 0 0:1 / %s rw,relatime - cgroup2 cgroup rw\n", mountPoint),
	)
	writeCgroupFile(t, filepath.Join(containerPath, "memory.max"), fmt.Sprint(8*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(containerPath, "memory.current"), fmt.Sprint(7*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(containerPath, "cpu.max"), "400000 100000")
	writeTestFile(t, testProcStatusPath(root), "Cpus_allowed_list:\t0-7\n")
	writeCgroupFile(t, filepath.Join(podPath, "memory.max"), fmt.Sprint(4*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(podPath, "memory.current"), fmt.Sprint(3*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(podPath, "cpu.max"), "150000 100000")

	limits := detectCgroupResourceLimits(testCgroupPaths(root))
	require.NotNil(t, limits)

	current, limit, ok := limits.MemoryStats()
	require.True(t, ok)
	require.Equal(t, uint64(3*1024*1024*1024), current)
	require.Equal(t, uint64(4*1024*1024*1024), limit)
	require.InEpsilon(t, 1.5, limits.CPULimit(), 1e-9)
}

func TestCgroupV1ResourceLimitsIgnored(t *testing.T) {
	root := t.TempDir()
	memoryMount := filepath.Join(root, "sys", "fs", "cgroup", "memory")
	cpuMount := filepath.Join(root, "sys", "fs", "cgroup", "cpu")

	writeTestFile(t, testProcCgroupPath(root),
		"5:memory:/docker/abc\n4:cpu,cpuacct:/docker/abc\n")
	writeTestFile(
		t,
		testProcMountInfoPath(root),
		fmt.Sprintf(
			"1 0 0:1 / %s rw - cgroup cgroup rw,memory\n2 0 0:2 / %s rw - cgroup cgroup rw,cpu,cpuacct\n",
			memoryMount,
			cpuMount,
		),
	)
	writeCgroupFile(t, filepath.Join(memoryMount, "docker", "abc", "memory.limit_in_bytes"),
		fmt.Sprint(4*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(memoryMount, "docker", "abc", "memory.usage_in_bytes"),
		fmt.Sprint(3*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(cpuMount, "docker", "abc", "cpu.cfs_quota_us"), "250000")
	writeCgroupFile(t, filepath.Join(cpuMount, "docker", "abc", "cpu.cfs_period_us"), "100000")
	writeTestFile(t, testProcStatusPath(root), "Cpus_allowed_list:\t0-3\n")

	limits := detectCgroupResourceLimits(testCgroupPaths(root))
	require.Nil(t, limits)
}

func TestCgroupV2DoesNotUseV1CPU(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cgroup")
	cpuMount := filepath.Join(root, "sys", "fs", "cgroup", "cpu")
	cgroupPath := filepath.Join(mountPoint, "kubepods", "pod123")

	writeTestFile(t, testProcCgroupPath(root),
		"0::/kubepods/pod123\n4:cpu,cpuacct:/docker/abc\n")
	writeTestFile(
		t,
		testProcMountInfoPath(root),
		fmt.Sprintf(
			"1 0 0:1 / %s rw - cgroup2 cgroup rw\n2 0 0:2 / %s rw - cgroup cgroup rw,cpu,cpuacct\n",
			mountPoint,
			cpuMount,
		),
	)
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.max"), fmt.Sprint(8*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.current"), fmt.Sprint(7*1024*1024*1024))
	writeCgroupFile(t, filepath.Join(cpuMount, "docker", "abc", "cpu.cfs_quota_us"), "250000")
	writeCgroupFile(t, filepath.Join(cpuMount, "docker", "abc", "cpu.cfs_period_us"), "100000")
	writeTestFile(t, testProcStatusPath(root), "Cpus_allowed_list:\t0-7\n")

	limits := detectCgroupResourceLimits(testCgroupPaths(root))
	require.NotNil(t, limits)

	current, limit, ok := limits.MemoryStats()
	require.True(t, ok)
	require.Equal(t, uint64(7*1024*1024*1024), current)
	require.Equal(t, uint64(8*1024*1024*1024), limit)
	require.Zero(t, limits.CPULimit())
}

func TestCgroupCPUUsesAllowedCPUList(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cgroup")
	cgroupPath := filepath.Join(mountPoint, "kubepods", "pod123")

	writeTestFile(t, testProcCgroupPath(root), "0::/kubepods/pod123\n")
	writeTestFile(
		t,
		testProcMountInfoPath(root),
		fmt.Sprintf("1 0 0:1 / %s rw,relatime - cgroup2 cgroup rw\n", mountPoint),
	)
	writeTestFile(t, testProcStatusPath(root), "Cpus_allowed_list:\t0-1\n")
	writeCgroupFile(t, filepath.Join(cgroupPath, "cpu.max"), "400000 100000")

	limits := detectCgroupResourceLimits(testCgroupPaths(root))
	require.NotNil(t, limits)
	require.InEpsilon(t, 2.0, limits.CPULimit(), 1e-9)
}

func TestCgroupCPUAllowedListIgnoredWhenUnrestricted(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cgroup")
	cgroupPath := filepath.Join(mountPoint, "kubepods", "pod123")

	writeTestFile(t, testProcCgroupPath(root), "0::/kubepods/pod123\n")
	writeTestFile(
		t,
		testProcMountInfoPath(root),
		fmt.Sprintf("1 0 0:1 / %s rw,relatime - cgroup2 cgroup rw\n", mountPoint),
	)
	writeTestFile(t, testProcStatusPath(root), "Cpus_allowed_list:\t0-7\n")
	writeCgroupFile(t, filepath.Join(cgroupPath, "cpu.max"), "max 100000")

	limits := detectCgroupResourceLimits(testCgroupPaths(root))
	require.Nil(t, limits)
}

func TestCgroupUnlimitedValuesAreIgnored(t *testing.T) {
	root := t.TempDir()
	mountPoint := filepath.Join(root, "sys", "fs", "cgroup")
	cgroupPath := filepath.Join(mountPoint, "kubepods", "pod123")

	writeTestFile(t, testProcCgroupPath(root), "0::/kubepods/pod123\n")
	writeTestFile(
		t,
		testProcMountInfoPath(root),
		fmt.Sprintf("1 0 0:1 / %s rw,relatime - cgroup2 cgroup rw\n", mountPoint),
	)
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.max"), "max")
	writeCgroupFile(t, filepath.Join(cgroupPath, "memory.current"), "123")
	writeCgroupFile(t, filepath.Join(cgroupPath, "cpu.max"), "max 100000")

	limits := detectCgroupResourceLimits(testCgroupPaths(root))
	require.Nil(t, limits)
}

func TestCgroupResourceLimitsUnavailable(t *testing.T) {
	root := t.TempDir()
	writeTestFile(t, testProcCgroupPath(root), "")
	writeTestFile(t, testProcMountInfoPath(root),
		fmt.Sprintf("1 0 0:1 / %s rw,relatime - proc proc rw\n", filepath.Join(root, "proc")))

	limits := detectCgroupResourceLimits(testCgroupPaths(root))
	require.Nil(t, limits)
}

func testCgroupPaths(root string) cgroupPaths {
	return cgroupPaths{procRoot: root, pid: 1, logicalCPUCount: 8}
}

func testProcCgroupPath(root string) string {
	return filepath.Join(root, "1", "cgroup")
}

func testProcMountInfoPath(root string) string {
	return filepath.Join(root, "1", "mountinfo")
}

func testProcStatusPath(root string) string {
	return filepath.Join(root, "1", "status")
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

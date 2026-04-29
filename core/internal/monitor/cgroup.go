package monitor

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/prometheus/procfs"
)

// The cgroup interface is a Linux kernel ABI exposed as files.
// See:
//   - https://docs.kernel.org/admin-guide/cgroup-v2.html
const (
	cgroupV2FSType = "cgroup2"

	cgroupNoLimitValue = "max"

	cgroupV2MemoryCurrentFile = "memory.current"
	cgroupV2MemoryMaxFile     = "memory.max"

	cgroupV2CPUMaxFile = "cpu.max"
)

var (
	defaultCgroupPaths = cgroupPaths{
		procRoot: procfs.DefaultMountPoint,
	}

	// /proc/<pid>/mountinfo is space-delimited. The kernel escapes space,
	// tab, newline, and backslash in pathname fields as octal byte sequences
	// (\040, \011, \012, \134). procfs parses the fields but leaves those
	// path escapes in place. Use raw string literals so Go does not interpret
	// the octal escapes before strings.NewReplacer sees them.
	mountInfoPathUnescaper = strings.NewReplacer(
		`\040`, " ",
		`\011`, "\t",
		`\012`, "\n",
		`\134`, `\`,
	)
)

// cgroupPaths describes which procfs tree to inspect.
//
// The zero value reads /proc/self; tests can point procRoot and pid at a fake
// /proc tree. logicalCPUCount lets us ignore an unrestricted CPU affinity list.
type cgroupPaths struct {
	procRoot        string
	pid             int
	logicalCPUCount int
}

// cgroupResourceLimits contains the cgroup v2 limits used as metric
// denominators. Limits are cached at startup; memory usage is read live.
type cgroupResourceLimits struct {
	memoryCurrentFile string
	memoryLimitBytes  uint64
	cpuLimit          float64
}

// detectCgroupResourceLimits resolves the effective cgroup limits for this
// process. Resource limits are stable enough to cache; memory usage is read live.
func detectCgroupResourceLimits(paths cgroupPaths) *cgroupResourceLimits {
	procInfo, mounts, err := readCgroupProcInfo(paths)
	if err != nil {
		return nil
	}
	if procInfo.unified == "" {
		return nil
	}

	var dirs []string
	for _, mount := range mounts {
		if mount.FSType != cgroupV2FSType {
			continue
		}
		dirs = append(
			dirs,
			ancestorDirs(
				cgroupDir(mount.MountPoint, mount.Root, procInfo.unified),
				mount.MountPoint,
			)...,
		)
	}
	if len(dirs) == 0 {
		return nil
	}

	limits := &cgroupResourceLimits{}
	limits.memoryCurrentFile, limits.memoryLimitBytes = memoryLimit(dirs)
	limits.cpuLimit = minPositive(
		cpuQuotaLimit(dirs),
		cpuAllowedLimit(procInfo.cpuAllowed, paths.logicalCPUCount),
	)

	hasMemoryLimit := limits.memoryLimitBytes > 0
	hasCPULimit := limits.cpuLimit > 0
	if !hasMemoryLimit && !hasCPULimit {
		return nil
	}
	return limits
}

type procCgroupInfo struct {
	unified    string
	cpuAllowed int
}

func readCgroupProcInfo(paths cgroupPaths) (procCgroupInfo, []*procfs.MountInfo, error) {
	root := paths.procRoot
	if root == "" {
		root = procfs.DefaultMountPoint
	}

	fs, err := procfs.NewFS(root)
	if err != nil {
		return procCgroupInfo{}, nil, err
	}

	var proc procfs.Proc
	var mounts []*procfs.MountInfo
	if paths.pid > 0 {
		proc, err = fs.Proc(paths.pid)
		if err == nil {
			mounts, err = fs.GetProcMounts(paths.pid)
		}
	} else {
		proc, err = fs.Self()
		if err == nil {
			mounts, err = fs.GetMounts()
		}
	}
	if err != nil {
		return procCgroupInfo{}, nil, err
	}

	cgroups, err := proc.Cgroups()
	if err != nil {
		return procCgroupInfo{}, nil, err
	}

	var info procCgroupInfo
	for _, cgroup := range cgroups {
		if len(cgroup.Controllers) == 0 {
			info.unified = cgroup.Path
			break
		}
	}

	if status, err := proc.NewStatus(); err == nil {
		info.cpuAllowed = len(status.CpusAllowedList)
	}
	return info, mounts, nil
}

// MemoryStats returns cgroup memory usage and its cached finite hard limit.
func (c *cgroupResourceLimits) MemoryStats() (current, limit uint64, ok bool) {
	if c.memoryCurrentFile == "" || c.memoryLimitBytes == 0 {
		return 0, 0, false
	}

	current, ok = readCgroupUint(c.memoryCurrentFile)
	if !ok {
		return 0, 0, false
	}
	return current, c.memoryLimitBytes, true
}

// MemoryLimit returns the cached finite cgroup memory limit.
func (c *cgroupResourceLimits) MemoryLimit() (uint64, bool) {
	return c.memoryLimitBytes, c.memoryLimitBytes > 0
}

// CPULimit returns the cached number of CPUs available to this process.
func (c *cgroupResourceLimits) CPULimit() float64 {
	return c.cpuLimit
}

func memoryLimit(dirs []string) (currentFile string, limit uint64) {
	for _, dir := range dirs {
		nextLimit, ok := readCgroupUint(filepath.Join(dir, cgroupV2MemoryMaxFile))
		if !ok || nextLimit == 0 {
			continue
		}
		if limit == 0 || nextLimit < limit {
			currentFile = filepath.Join(dir, cgroupV2MemoryCurrentFile)
			limit = nextLimit
		}
	}
	return currentFile, limit
}

func cpuQuotaLimit(dirs []string) float64 {
	var out float64
	for _, dir := range dirs {
		quota, period, ok := readCgroupV2CPUMax(filepath.Join(dir, cgroupV2CPUMaxFile))
		if !ok || quota <= 0 || period <= 0 {
			continue
		}
		out = minPositive(out, float64(quota)/float64(period))
	}
	return out
}

func cpuAllowedLimit(allowed, logicalCPUCount int) float64 {
	if allowed <= 0 || logicalCPUCount <= 0 || allowed >= logicalCPUCount {
		return 0
	}
	return float64(allowed)
}

func minPositive(a, b float64) float64 {
	if a <= 0 {
		if b > 0 {
			return b
		}
		return 0
	}
	if b <= 0 {
		return a
	}
	if b < a {
		return b
	}
	return a
}

func cgroupDir(mountPoint, mountRoot, cgroupPath string) string {
	rel := filepath.Clean(cgroupPath)
	root := filepath.Clean(unescapeMountInfoPath(mountRoot))
	mountPoint = unescapeMountInfoPath(mountPoint)

	if root != "/" {
		if rel == root {
			rel = "/"
		} else if strings.HasPrefix(rel, root+"/") {
			rel = strings.TrimPrefix(rel, root)
		}
	}

	return filepath.Join(mountPoint, strings.TrimPrefix(rel, "/"))
}

func ancestorDirs(dir, mountPoint string) []string {
	dir = filepath.Clean(dir)
	mountPoint = filepath.Clean(mountPoint)

	var dirs []string
	for {
		dirs = append(dirs, dir)
		if dir == mountPoint || dir == "." || dir == "/" {
			return dirs
		}

		parent := filepath.Dir(dir)
		if parent == dir {
			return dirs
		}
		dir = parent
	}
}

func readCgroupV2CPUMax(path string) (quota, period int64, ok bool) {
	text, err := os.ReadFile(path)
	if err != nil {
		return 0, 0, false
	}

	fields := strings.Fields(string(text))
	if len(fields) != 2 || fields[0] == cgroupNoLimitValue {
		return 0, 0, false
	}

	quota, err = strconv.ParseInt(fields[0], 10, 64)
	if err != nil {
		return 0, 0, false
	}
	period, err = strconv.ParseInt(fields[1], 10, 64)
	if err != nil {
		return 0, 0, false
	}
	return quota, period, true
}

func readCgroupUint(path string) (uint64, bool) {
	text, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}

	value := strings.TrimSpace(string(text))
	if value == "" || value == cgroupNoLimitValue {
		return 0, false
	}

	out, err := strconv.ParseUint(value, 10, 64)
	return out, err == nil
}

func unescapeMountInfoPath(path string) string {
	return mountInfoPathUnescaper.Replace(path)
}

package monitor

import (
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
)

// The cgroup interface is a Linux kernel ABI exposed as files.
// Please refer to the kernel documentation for more info:
//   - cgroup v2 files: https://docs.kernel.org/admin-guide/cgroup-v2.html
//   - cgroup v1 memory files: https://docs.kernel.org/admin-guide/cgroup-v1/memory.html
//   - cgroup v1 CPU quota files: https://docs.kernel.org/scheduler/sched-bwc.html
//   - /proc/[pid]/cgroup: https://man7.org/linux/man-pages/man5/proc_pid_cgroup.5.html
//   - /proc/[pid]/mountinfo: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html
const (
	procSelfCgroupPath    = "/proc/self/cgroup"
	procSelfMountInfoPath = "/proc/self/mountinfo"

	cgroupVersion1 = 1
	cgroupVersion2 = 2

	cgroupV1FSType = "cgroup"
	cgroupV2FSType = "cgroup2"

	cgroupMemoryController = "memory"
	cgroupCPUController    = "cpu"
	cgroupCPUSetController = "cpuset"

	cgroupNoLimitValue = "max"

	cgroupV2MemoryCurrentFile = "memory.current"
	cgroupV2MemoryMaxFile     = "memory.max"
	cgroupV1MemoryUsageFile   = "memory.usage_in_bytes"
	cgroupV1MemoryLimitFile   = "memory.limit_in_bytes"

	cgroupV2CPUMaxFile    = "cpu.max"
	cgroupV1CPUQuotaFile  = "cpu.cfs_quota_us"
	cgroupV1CPUPeriodFile = "cpu.cfs_period_us"

	cgroupCPUSetEffectiveFile = "cpuset.cpus.effective"
	cgroupCPUSetFile          = "cpuset.cpus"

	cgroupRootPath    = "/"
	cgroupCurrentPath = "."

	cgroupV1NoMemoryLimit = uint64(1 << 60)

	procCgroupSeparator       = ":"
	procCgroupFieldCount      = 3
	procCgroupControllerField = 1
	procCgroupPathField       = 2

	mountInfoSeparator       = " - "
	mountInfoFieldCount      = 2
	mountInfoMinPrefixFields = 5
	mountInfoMinSuffixFields = 3
	mountInfoRootField       = 3
	mountInfoMountPointField = 4
	mountInfoFSTypeField     = 0
	mountInfoOptionsField    = 2

	cpusetRangeFieldCount = 2

	lineSeparator  = "\n"
	listSeparator  = ","
	rangeSeparator = "-"

	mountInfoEscapedSpace     = `\040`
	mountInfoEscapedTab       = `\011`
	mountInfoEscapedNewline   = `\012`
	mountInfoEscapedBackslash = `\134`

	spaceCharacter     = " "
	tabCharacter       = "\t"
	newlineCharacter   = "\n"
	backslashCharacter = `\`

	base10 = 10
	bits64 = 64
)

var (
	defaultCgroupPaths = cgroupPaths{
		procCgroup:    procSelfCgroupPath,
		procMountInfo: procSelfMountInfoPath,
	}

	cgroupCPUSetFiles = [...]string{
		cgroupCPUSetEffectiveFile,
		cgroupCPUSetFile,
	}
)

// cgroupPaths names the procfs files used to discover the current process's
// cgroup membership and visible cgroup mounts.
type cgroupPaths struct {
	procCgroup    string
	procMountInfo string
}

// cgroupResourceLimits stores the cgroup controllers that can bound reported
// system metrics for this process.
type cgroupResourceLimits struct {
	memory cgroupController
	cpu    cgroupController
	cpuset cgroupController

	memoryStatsOnce sync.Once
	memoryStats     cgroupMemoryStats
	cpuLimitOnce    sync.Once
	cpuLimit        float64
}

// cgroupController records one mounted controller and the candidate cgroup
// directories to inspect, ordered from the process cgroup toward the mount root.
type cgroupController struct {
	version    int
	dirs       []string
	mountPoint string
}

// cgroupMemoryStats caches the stable memory limit and current-usage file. The
// memory usage value itself is read fresh for each sample.
type cgroupMemoryStats struct {
	currentFile string
	limit       uint64
	ok          bool
}

// cgroupMountInfo is the subset of /proc/[pid]/mountinfo needed to map a
// cgroup path from /proc/[pid]/cgroup onto the corresponding cgroupfs mount.
type cgroupMountInfo struct {
	fsType      string
	root        string
	mountPoint  string
	controllers map[string]struct{}
}

// procCgroupInfo is the parsed cgroup membership for a single process.
type procCgroupInfo struct {
	unified    string
	controller map[string]string
}

// detectCgroupResourceLimits resolves the cgroup controllers that constrain the
// current process. It returns nil when procfs is unavailable or no supported
// cgroup mount is visible.
func detectCgroupResourceLimits(paths cgroupPaths) *cgroupResourceLimits {
	procInfo, err := parseProcCgroup(paths.procCgroup)
	if err != nil {
		return nil
	}

	mounts, err := parseCgroupMountInfo(paths.procMountInfo)
	if err != nil {
		return nil
	}

	for _, mount := range mounts {
		if mount.fsType == cgroupV2FSType && procInfo.unified != "" {
			dirs := ancestorDirs(
				cgroupDir(mount.mountPoint, mount.root, procInfo.unified),
				mount.mountPoint,
			)
			return &cgroupResourceLimits{
				memory: cgroupController{
					version:    cgroupVersion2,
					dirs:       dirs,
					mountPoint: mount.mountPoint,
				},
				cpu: cgroupController{
					version:    cgroupVersion2,
					dirs:       dirs,
					mountPoint: mount.mountPoint,
				},
				cpuset: cgroupController{
					version:    cgroupVersion2,
					dirs:       dirs,
					mountPoint: mount.mountPoint,
				},
			}
		}
	}

	limits := &cgroupResourceLimits{}
	for _, mount := range mounts {
		if mount.fsType != cgroupV1FSType {
			continue
		}

		if _, ok := mount.controllers[cgroupMemoryController]; ok {
			limits.memory = controllerFromMount(
				mount,
				procInfo.controller[cgroupMemoryController],
			)
		}
		if _, ok := mount.controllers[cgroupCPUController]; ok {
			limits.cpu = controllerFromMount(
				mount,
				procInfo.controller[cgroupCPUController],
			)
		}
		if _, ok := mount.controllers[cgroupCPUSetController]; ok {
			limits.cpuset = controllerFromMount(
				mount,
				procInfo.controller[cgroupCPUSetController],
			)
		}
	}

	if len(limits.memory.dirs) == 0 && len(limits.cpu.dirs) == 0 && len(limits.cpuset.dirs) == 0 {
		return nil
	}

	return limits
}

// controllerFromMount maps a cgroup v1 controller mount and process cgroup path
// to the directories that can hold effective resource limits.
func controllerFromMount(mount cgroupMountInfo, cgroupPath string) cgroupController {
	if cgroupPath == "" {
		return cgroupController{}
	}

	return cgroupController{
		version: cgroupVersion1,
		dirs: ancestorDirs(
			cgroupDir(mount.mountPoint, mount.root, cgroupPath),
			mount.mountPoint,
		),
		mountPoint: mount.mountPoint,
	}
}

// MemoryStats returns cgroup memory usage and the cached finite hard limit. The
// limit and current-usage file are resolved once; usage is read fresh each call.
func (c *cgroupResourceLimits) MemoryStats() (current, limit uint64, ok bool) {
	c.memoryStatsOnce.Do(c.initMemoryStats)
	if !c.memoryStats.ok {
		return 0, 0, false
	}

	current, ok = readCgroupUint(c.memoryStats.currentFile)
	if !ok {
		return 0, 0, false
	}

	return current, c.memoryStats.limit, true
}

// MemoryLimit returns the cached finite cgroup memory limit.
func (c *cgroupResourceLimits) MemoryLimit() (limit uint64, ok bool) {
	c.memoryStatsOnce.Do(c.initMemoryStats)
	return c.memoryStats.limit, c.memoryStats.ok
}

// initMemoryStats resolves the first finite cgroup memory limit while walking
// from the process cgroup toward its ancestors.
func (c *cgroupResourceLimits) initMemoryStats() {
	if len(c.memory.dirs) == 0 {
		return
	}

	currentFile, limitFile := c.memoryFileNames()

	for _, dir := range c.memory.dirs {
		limit, ok := readCgroupUint(filepath.Join(dir, limitFile))
		if !ok || !isFiniteMemoryLimit(limit) {
			continue
		}

		c.memoryStats = cgroupMemoryStats{
			currentFile: filepath.Join(dir, currentFile),
			limit:       limit,
			ok:          true,
		}
		return
	}
}

// memoryFileNames returns the cgroup files for the active memory controller.
func (c *cgroupResourceLimits) memoryFileNames() (currentFile, limitFile string) {
	if c.memory.version == cgroupVersion2 {
		return cgroupV2MemoryCurrentFile, cgroupV2MemoryMaxFile
	}

	return cgroupV1MemoryUsageFile, cgroupV1MemoryLimitFile
}

// CPULimit returns the number of CPUs available to the process according to the
// cached most restrictive cgroup CPU quota or cpuset bound.
func (c *cgroupResourceLimits) CPULimit() float64 {
	c.cpuLimitOnce.Do(func() {
		c.cpuLimit = c.detectCPULimit()
	})
	return c.cpuLimit
}

// detectCPULimit resolves the cgroup CPU capacity from quota and cpuset files.
func (c *cgroupResourceLimits) detectCPULimit() float64 {
	limits := make([]float64, 0, 2)

	if limit := c.cpuQuotaLimit(); limit > 0 {
		limits = append(limits, limit)
	}
	if limit := c.cpusetLimit(); limit > 0 {
		limits = append(limits, limit)
	}

	if len(limits) == 0 {
		return 0
	}

	out := limits[0]
	for _, limit := range limits[1:] {
		out = math.Min(out, limit)
	}
	return out
}

// cpuQuotaLimit returns the CPU quota as a count of host CPUs, or zero when no
// cgroup quota applies.
func (c *cgroupResourceLimits) cpuQuotaLimit() float64 {
	if len(c.cpu.dirs) == 0 {
		return 0
	}

	for _, dir := range c.cpu.dirs {
		var quota, period int64
		var ok bool

		if c.cpu.version == cgroupVersion2 {
			quota, period, ok = readCgroupV2CPUMax(filepath.Join(dir, cgroupV2CPUMaxFile))
		} else {
			quota, ok = readCgroupInt(filepath.Join(dir, cgroupV1CPUQuotaFile))
			if !ok || quota <= 0 {
				continue
			}
			period, ok = readCgroupInt(filepath.Join(dir, cgroupV1CPUPeriodFile))
		}

		if ok && quota > 0 && period > 0 {
			return float64(quota) / float64(period)
		}
	}

	return 0
}

// cpusetLimit returns the number of CPUs granted by the cgroup cpuset
// controller, or zero when no cpuset applies.
func (c *cgroupResourceLimits) cpusetLimit() float64 {
	if len(c.cpuset.dirs) == 0 {
		return 0
	}

	for _, dir := range c.cpuset.dirs {
		for _, file := range cgroupCPUSetFiles {
			text, err := os.ReadFile(filepath.Join(dir, file))
			if err != nil {
				continue
			}

			if count := countCPUSet(strings.TrimSpace(string(text))); count > 0 {
				return float64(count)
			}
		}
	}

	return 0
}

// parseProcCgroup parses /proc/[pid]/cgroup into cgroup v2 unified membership
// and cgroup v1 controller memberships.
func parseProcCgroup(path string) (procCgroupInfo, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return procCgroupInfo{}, err
	}

	info := procCgroupInfo{controller: make(map[string]string)}
	for line := range strings.SplitSeq(strings.TrimSpace(string(data)), lineSeparator) {
		if line == "" {
			continue
		}

		parts := strings.SplitN(line, procCgroupSeparator, procCgroupFieldCount)
		if len(parts) != procCgroupFieldCount {
			continue
		}

		if parts[procCgroupControllerField] == "" {
			info.unified = parts[procCgroupPathField]
			continue
		}

		for controller := range strings.SplitSeq(parts[procCgroupControllerField], listSeparator) {
			info.controller[controller] = parts[procCgroupPathField]
		}
	}

	return info, nil
}

// parseCgroupMountInfo returns the cgroup mounts visible in a process mount
// namespace.
func parseCgroupMountInfo(path string) ([]cgroupMountInfo, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var mounts []cgroupMountInfo
	for line := range strings.SplitSeq(strings.TrimSpace(string(data)), lineSeparator) {
		if line == "" {
			continue
		}

		mount, ok := parseCgroupMountInfoLine(line)
		if ok {
			mounts = append(mounts, mount)
		}
	}

	return mounts, nil
}

// parseCgroupMountInfoLine parses a single /proc/[pid]/mountinfo line. The
// separator is significant because mountinfo has optional fields before it and
// fixed filesystem fields after it.
func parseCgroupMountInfoLine(line string) (cgroupMountInfo, bool) {
	parts := strings.SplitN(line, mountInfoSeparator, mountInfoFieldCount)
	if len(parts) != mountInfoFieldCount {
		return cgroupMountInfo{}, false
	}

	preFields := strings.Fields(parts[0])
	postFields := strings.Fields(parts[1])
	if len(preFields) < mountInfoMinPrefixFields || len(postFields) < mountInfoMinSuffixFields {
		return cgroupMountInfo{}, false
	}

	fsType := postFields[mountInfoFSTypeField]
	if fsType != cgroupV1FSType && fsType != cgroupV2FSType {
		return cgroupMountInfo{}, false
	}

	controllers := make(map[string]struct{})
	if fsType == cgroupV1FSType {
		for opt := range strings.SplitSeq(postFields[mountInfoOptionsField], listSeparator) {
			controllers[opt] = struct{}{}
		}
	}

	return cgroupMountInfo{
		fsType:      fsType,
		root:        unescapeMountInfoPath(preFields[mountInfoRootField]),
		mountPoint:  unescapeMountInfoPath(preFields[mountInfoMountPointField]),
		controllers: controllers,
	}, true
}

// cgroupDir converts a process cgroup path into an absolute path under a cgroup
// mount, accounting for bind mounts whose mount root is below the cgroup root.
func cgroupDir(mountPoint, mountRoot, cgroupPath string) string {
	rel := filepath.Clean(cgroupPath)
	root := filepath.Clean(mountRoot)

	if root != cgroupRootPath {
		if rel == root {
			rel = cgroupRootPath
		} else if strings.HasPrefix(rel, root+cgroupRootPath) {
			rel = strings.TrimPrefix(rel, root)
		}
	}

	return filepath.Join(mountPoint, strings.TrimPrefix(rel, cgroupRootPath))
}

// ancestorDirs returns a cgroup directory and its ancestors up to the mount
// point. cgroup limits are hierarchical, so an ancestor can be the effective
// bound when the leaf cgroup is unconstrained.
func ancestorDirs(dir, mountPoint string) []string {
	dir = filepath.Clean(dir)
	mountPoint = filepath.Clean(mountPoint)

	var dirs []string
	for {
		dirs = append(dirs, dir)
		if dir == mountPoint || dir == cgroupCurrentPath || dir == cgroupRootPath {
			return dirs
		}

		parent := filepath.Dir(dir)
		if parent == dir {
			return dirs
		}
		dir = parent
	}
}

// readCgroupV2CPUMax reads the cgroup v2 CPU quota and period from cpu.max.
func readCgroupV2CPUMax(path string) (quota, period int64, ok bool) {
	text, err := os.ReadFile(path)
	if err != nil {
		return 0, 0, false
	}

	fields := strings.Fields(string(text))
	if len(fields) != 2 || fields[0] == cgroupNoLimitValue {
		return 0, 0, false
	}

	quota, err = strconv.ParseInt(fields[0], base10, bits64)
	if err != nil {
		return 0, 0, false
	}

	period, err = strconv.ParseInt(fields[1], base10, bits64)
	if err != nil {
		return 0, 0, false
	}

	return quota, period, true
}

// readCgroupUint reads a cgroup file containing a non-negative integer. It
// treats cgroup v2's max value as an unconstrained limit.
func readCgroupUint(path string) (uint64, bool) {
	text, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}

	value := strings.TrimSpace(string(text))
	if value == "" || value == cgroupNoLimitValue {
		return 0, false
	}

	out, err := strconv.ParseUint(value, base10, bits64)
	return out, err == nil
}

// readCgroupInt reads a cgroup file containing a signed integer.
func readCgroupInt(path string) (int64, bool) {
	text, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}

	out, err := strconv.ParseInt(strings.TrimSpace(string(text)), base10, bits64)
	return out, err == nil
}

// isFiniteMemoryLimit reports whether a memory limit is usable as a denominator
// for usage percentages.
func isFiniteMemoryLimit(limit uint64) bool {
	return limit > 0 && limit < cgroupV1NoMemoryLimit
}

// countCPUSet counts CPUs in the cpuset list format used by cpuset.cpus and
// cpuset.cpus.effective.
func countCPUSet(value string) int {
	if value == "" {
		return 0
	}

	count := 0
	for part := range strings.SplitSeq(value, listSeparator) {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}

		bounds := strings.SplitN(part, rangeSeparator, cpusetRangeFieldCount)
		start, err := strconv.Atoi(bounds[0])
		if err != nil {
			continue
		}

		end := start
		if len(bounds) == cpusetRangeFieldCount {
			end, err = strconv.Atoi(bounds[1])
			if err != nil {
				continue
			}
		}

		if end < start {
			continue
		}
		count += end - start + 1
	}

	return count
}

// unescapeMountInfoPath decodes the octal escapes used in mountinfo path
// fields.
func unescapeMountInfoPath(path string) string {
	replacer := strings.NewReplacer(
		mountInfoEscapedSpace, spaceCharacter,
		mountInfoEscapedTab, tabCharacter,
		mountInfoEscapedNewline, newlineCharacter,
		mountInfoEscapedBackslash, backslashCharacter,
	)
	return replacer.Replace(path)
}

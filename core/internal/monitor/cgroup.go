package monitor

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
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

	// cgroup v1 reports no memory limit as a huge LONG_MAX-derived value. This
	// threshold treats those sentinel values as unlimited without rejecting real limits.
	cgroupV1NoMemoryLimit = uint64(1 << 60)

	mountInfoSeparator = " - "
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

	mountInfoPathUnescaper = strings.NewReplacer(
		`\040`, " ",
		`\011`, "\t",
		`\012`, "\n",
		`\134`, `\`,
	)
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
}

// cgroupController records one mounted controller and the candidate cgroup
// directories to inspect, ordered from the process cgroup toward the mount root.
type cgroupController struct {
	version int
	dirs    []string
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

	v2 := cgroupV2ResourceLimits(procInfo, mounts)
	if v2 == nil {
		return cgroupV1ResourceLimits(procInfo, mounts)
	}

	v1 := cgroupV1ResourceLimits(procInfo, mounts)
	if v1 == nil {
		return v2
	}

	// Hybrid hierarchies can expose the v2 tree while resource controllers still
	// live in v1 mounts, so choose the most restrictive controller per resource.
	limits := *v2
	if v1Limit, ok := v1.MemoryLimit(); ok {
		if v2Limit, ok := v2.MemoryLimit(); !ok || v1Limit < v2Limit {
			limits.memory = v1.memory
		}
	}
	if v1Quota := v1.cpuQuotaLimit(); v1Quota > 0 {
		if v2Quota := v2.cpuQuotaLimit(); v2Quota == 0 || v1Quota < v2Quota {
			limits.cpu = v1.cpu
		}
	}
	if v1CPUSet := v1.cpusetLimit(); v1CPUSet > 0 {
		if v2CPUSet := v2.cpusetLimit(); v2CPUSet == 0 || v1CPUSet < v2CPUSet {
			limits.cpuset = v1.cpuset
		}
	}

	return &limits
}

func cgroupV2ResourceLimits(
	procInfo procCgroupInfo,
	mounts []cgroupMountInfo,
) *cgroupResourceLimits {
	if procInfo.unified == "" {
		return nil
	}

	for _, mount := range mounts {
		if mount.fsType == cgroupV2FSType {
			dirs := ancestorDirs(
				cgroupDir(mount.mountPoint, mount.root, procInfo.unified),
				mount.mountPoint,
			)
			controller := cgroupController{
				version: cgroupVersion2,
				dirs:    dirs,
			}
			return &cgroupResourceLimits{
				memory: controller,
				cpu:    controller,
				cpuset: controller,
			}
		}
	}

	return nil
}

func cgroupV1ResourceLimits(
	procInfo procCgroupInfo,
	mounts []cgroupMountInfo,
) *cgroupResourceLimits {
	limits := &cgroupResourceLimits{}
	for _, mount := range mounts {
		if mount.fsType != cgroupV1FSType {
			continue
		}

		if _, ok := mount.controllers[cgroupMemoryController]; ok && len(limits.memory.dirs) == 0 {
			limits.memory = controllerFromMount(mount, procInfo.controller[cgroupMemoryController])
		}
		if _, ok := mount.controllers[cgroupCPUController]; ok && len(limits.cpu.dirs) == 0 {
			limits.cpu = controllerFromMount(mount, procInfo.controller[cgroupCPUController])
		}
		if _, ok := mount.controllers[cgroupCPUSetController]; ok && len(limits.cpuset.dirs) == 0 {
			limits.cpuset = controllerFromMount(mount, procInfo.controller[cgroupCPUSetController])
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
	}
}

// MemoryStats returns cgroup memory usage and the finite hard limit.
func (c *cgroupResourceLimits) MemoryStats() (current, limit uint64, ok bool) {
	currentFile, limit, ok := c.memoryCurrentFileAndLimit()
	if !ok {
		return 0, 0, false
	}

	current, ok = readCgroupUint(currentFile)
	if !ok {
		return 0, 0, false
	}

	return current, limit, true
}

// MemoryLimit returns the finite cgroup memory limit.
func (c *cgroupResourceLimits) MemoryLimit() (limit uint64, ok bool) {
	_, limit, ok = c.memoryCurrentFileAndLimit()
	return limit, ok
}

// memoryCurrentFileAndLimit resolves the smallest finite cgroup memory limit
// while walking from the process cgroup toward its ancestors.
func (c *cgroupResourceLimits) memoryCurrentFileAndLimit() (currentFile string, limit uint64, ok bool) {
	if len(c.memory.dirs) == 0 {
		return "", 0, false
	}

	currentName, limitName := memoryFileNames(c.memory.version)

	for _, dir := range c.memory.dirs {
		nextLimit, readOK := readCgroupUint(filepath.Join(dir, limitName))
		if !readOK || !isFiniteMemoryLimit(nextLimit) {
			continue
		}

		if currentFile != "" && nextLimit >= limit {
			continue
		}

		currentFile = filepath.Join(dir, currentName)
		limit = nextLimit
		ok = true
	}

	return currentFile, limit, ok
}

// memoryFileNames returns the cgroup files for the active memory controller.
func memoryFileNames(version int) (currentFile, limitFile string) {
	if version == cgroupVersion2 {
		return cgroupV2MemoryCurrentFile, cgroupV2MemoryMaxFile
	}

	return cgroupV1MemoryUsageFile, cgroupV1MemoryLimitFile
}

// CPULimit returns the number of CPUs available to the process according to the
// most restrictive cgroup CPU quota or cpuset bound.
func (c *cgroupResourceLimits) CPULimit() float64 {
	limit := c.cpuQuotaLimit()
	if cpusetLimit := c.cpusetLimit(); cpusetLimit > 0 &&
		(limit == 0 || cpusetLimit < limit) {
		limit = cpusetLimit
	}

	return limit
}

// cpuQuotaLimit returns the CPU quota as a count of host CPUs, or zero when no
// cgroup quota applies.
func (c *cgroupResourceLimits) cpuQuotaLimit() float64 {
	if len(c.cpu.dirs) == 0 {
		return 0
	}

	var out float64
	for _, dir := range c.cpu.dirs {
		quota, period, ok := cpuQuotaAndPeriod(c.cpu, dir)
		if !ok || quota <= 0 || period <= 0 {
			continue
		}

		limit := float64(quota) / float64(period)
		if out == 0 || limit < out {
			out = limit
		}
	}

	return out
}

func cpuQuotaAndPeriod(controller cgroupController, dir string) (quota, period int64, ok bool) {
	if controller.version == cgroupVersion2 {
		return readCgroupV2CPUMax(filepath.Join(dir, cgroupV2CPUMaxFile))
	}

	quota, ok = readCgroupInt(filepath.Join(dir, cgroupV1CPUQuotaFile))
	if !ok || quota <= 0 {
		return 0, 0, false
	}

	period, ok = readCgroupInt(filepath.Join(dir, cgroupV1CPUPeriodFile))
	return quota, period, ok
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
	for line := range strings.SplitSeq(strings.TrimSpace(string(data)), "\n") {
		if line == "" {
			continue
		}

		_, rest, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		controllers, cgroupPath, ok := strings.Cut(rest, ":")
		if !ok {
			continue
		}

		if controllers == "" {
			info.unified = cgroupPath
			continue
		}

		for controller := range strings.SplitSeq(controllers, ",") {
			info.controller[controller] = cgroupPath
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
	for line := range strings.SplitSeq(strings.TrimSpace(string(data)), "\n") {
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
	pre, post, ok := strings.Cut(line, mountInfoSeparator)
	if !ok {
		return cgroupMountInfo{}, false
	}

	preFields := strings.Fields(pre)
	postFields := strings.Fields(post)
	if len(preFields) < 5 || len(postFields) < 3 {
		return cgroupMountInfo{}, false
	}

	fsType := postFields[0]
	if fsType != cgroupV1FSType && fsType != cgroupV2FSType {
		return cgroupMountInfo{}, false
	}

	controllers := make(map[string]struct{})
	if fsType == cgroupV1FSType {
		for opt := range strings.SplitSeq(postFields[2], ",") {
			if isCgroupV1Controller(opt) {
				controllers[opt] = struct{}{}
			}
		}
	}

	return cgroupMountInfo{
		fsType:      fsType,
		root:        unescapeMountInfoPath(preFields[3]),
		mountPoint:  unescapeMountInfoPath(preFields[4]),
		controllers: controllers,
	}, true
}

func isCgroupV1Controller(name string) bool {
	switch name {
	case cgroupMemoryController, cgroupCPUController, cgroupCPUSetController:
		return true
	default:
		return false
	}
}

// cgroupDir converts a process cgroup path into an absolute path under a cgroup
// mount, accounting for bind mounts whose mount root is below the cgroup root.
func cgroupDir(mountPoint, mountRoot, cgroupPath string) string {
	rel := filepath.Clean(cgroupPath)
	root := filepath.Clean(mountRoot)

	if root != "/" {
		if rel == root {
			rel = "/"
		} else if strings.HasPrefix(rel, root+"/") {
			rel = strings.TrimPrefix(rel, root)
		}
	}

	return filepath.Join(mountPoint, strings.TrimPrefix(rel, "/"))
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

	out, err := strconv.ParseUint(value, 10, 64)
	return out, err == nil
}

// readCgroupInt reads a cgroup file containing a signed integer.
func readCgroupInt(path string) (int64, bool) {
	text, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}

	out, err := strconv.ParseInt(strings.TrimSpace(string(text)), 10, 64)
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
	for part := range strings.SplitSeq(value, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}

		bounds := strings.SplitN(part, "-", 2)
		start, err := strconv.Atoi(bounds[0])
		if err != nil {
			continue
		}

		end := start
		if len(bounds) == 2 {
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
	return mountInfoPathUnescaper.Replace(path)
}

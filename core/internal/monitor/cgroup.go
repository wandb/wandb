package monitor

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/prometheus/procfs"
)

// This file detects cgroup v2 limits to use as denominators for the system
// memory and CPU percentages. Without these, a containerized run reports
// usage as a fraction of the host node, which produces misleading
// numbers when the cgroup limit is much smaller than the host.
//
// Strategy: read the unified cgroup v2 path the process belongs to from
// /proc/<pid>/cgroup, find its directory under a cgroup2 mount via
// /proc/<pid>/mountinfo, then read memory.max, cpu.max, and the process's
// CPU affinity. Limits are cached at startup; only memory.current is read
// live during sampling. Cgroup v1 is intentionally not supported — the
// kernel exposes a different file layout, and v2 has been the default in
// every major distro for years.
//
// We deliberately read only the leaf cgroup that actually contains the
// process. A parent cgroup may carry a tighter limit, but its
// memory.current also includes sibling workloads, so dividing parent
// usage by parent limit would not describe this process. The Go runtime's
// cgroup-aware GOMAXPROCS makes the same call.
//
// Reference: https://docs.kernel.org/admin-guide/cgroup-v2.html

const (
	// cgroupV2FSType identifies a cgroup v2 mount in /proc/<pid>/mountinfo.
	// Cgroup v1 mounts use the type "cgroup" instead, which is how we
	// filter v1 entries out and avoid misreading them as v2.
	cgroupV2FSType = "cgroup2"

	// cgroupNoLimitValue is the literal the kernel writes when a resource
	// is unbounded (memory.max, the quota field of cpu.max, etc.). We treat
	// it as "no limit" so callers do not have to special-case the string.
	cgroupNoLimitValue = "max"

	cgroupV2MemoryCurrentFile = "memory.current"
	cgroupV2MemoryMaxFile     = "memory.max"

	cgroupV2CPUMaxFile = "cpu.max"
)

// defaultCgroupPaths is the production configuration: read the real /proc
// for /proc/self. Tests construct a cgroupPaths pointing at a fake /proc
// tree and a synthetic pid so they do not depend on the host's cgroups.
var defaultCgroupPaths = cgroupPaths{
	procRoot: procfs.DefaultMountPoint,
}

// cgroupPaths configures which procfs tree to read.
//
// The zero value reads the real /proc/self. Tests redirect procRoot at a
// temporary directory and set pid to read a synthetic process entry under
// it.
//
// logicalCPUCount is the host's logical CPU count. It is supplied here
// instead of being read inside cgroup detection so callers (production via
// gopsutil, tests via a fixed integer) control it consistently. A zero
// value means "unknown"; cpuAllowedLimit handles that case.
type cgroupPaths struct {
	procRoot        string
	pid             int
	logicalCPUCount int
}

// cgroupResourceLimits holds the cgroup v2 numbers used as denominators for
// memory_percent and CPU normalization.
//
// memoryLimitBytes and cpuLimit are captured once at startup. Cgroup
// limits can change at runtime, but doing so is rare and re-detecting on
// every sample is not worth the cost. memory.current, in contrast, must
// be read live because it is what we are measuring; MemoryStats reads it
// from the same cgroup directory we measured the limit from so numerator
// and denominator stay consistent.
type cgroupResourceLimits struct {
	// memoryCurrentFile is the absolute path to memory.current alongside
	// the cgroup directory whose memory.max is memoryLimitBytes. Empty
	// when no finite memory limit applied at startup; in that case
	// MemoryStats returns ok=false.
	memoryCurrentFile string

	// memoryLimitBytes is the finite memory.max reading in bytes.
	// Zero means no memory limit applied at startup.
	memoryLimitBytes uint64

	// cpuLimit is the effective CPU count: the smaller of cpu.max
	// quota/period and the size of Cpus_allowed_list (when smaller than
	// the host). Zero means no CPU limit applied at startup.
	cpuLimit float64
}

// detectCgroupResourceLimits resolves the cgroup v2 limits that apply to
// this process and caches them as denominators for system metric reporting.
//
// Returns nil — letting the caller fall back to host-wide gopsutil
// metrics — when any of:
//
//   - procfs cannot be read (almost always means we are not on Linux);
//   - the process has no cgroup v2 entry (cgroup v1 only, or no cgroup);
//   - no cgroup2 mount in mountinfo points at the process's cgroup path
//     (cgroup tooling visible to the process is broken or restricted);
//   - neither a finite memory limit nor a CPU limit was found
//     (we are on the host or in a container with no resource limits set).
//
// Returning nil is the success case for "no cgroup limit applies"; the
// caller treats nil and "limits with all zeros" the same way, so we
// collapse them here to keep the consumer (System.collectSystemMemoryMetrics
// and System.cpuCapacity) simple.
func detectCgroupResourceLimits(paths cgroupPaths) *cgroupResourceLimits {
	procInfo, mounts, err := readCgroupProcInfo(paths)
	if err != nil {
		return nil
	}
	if procInfo.cgroupV2Path == "" {
		return nil
	}

	// Cgroup v2 has a single unified hierarchy per mount namespace, so we
	// expect at most one cgroup2 mount visible to the process. Use the
	// first one and skip cgroup v1 entries.
	var leafDir string
	for _, mount := range mounts {
		if mount.FSType == cgroupV2FSType {
			leafDir = cgroupDir(mount, procInfo.cgroupV2Path)
			break
		}
	}
	if leafDir == "" {
		return nil
	}

	limits := &cgroupResourceLimits{}
	limits.memoryCurrentFile, limits.memoryLimitBytes = memoryLimit(leafDir)
	// cpu.max and the cpuset affinity list are independent restrictions:
	// either may be unset, both may apply. Take the binding constraint.
	// minPositive (instead of plain min) avoids letting an unset 0 win
	// over a real positive limit.
	limits.cpuLimit = minPositive(
		cpuQuotaLimit(leafDir),
		cpuAllowedLimit(procInfo.cpuAllowed, paths.logicalCPUCount),
	)

	hasMemoryLimit := limits.memoryLimitBytes > 0
	hasCPULimit := limits.cpuLimit > 0
	if !hasMemoryLimit && !hasCPULimit {
		return nil
	}
	return limits
}

// procCgroupInfo carries the per-process facts read from /proc that we
// need to locate and interpret cgroup files.
type procCgroupInfo struct {
	// cgroupV2Path is the path read from the unified-hierarchy entry of
	// /proc/<pid>/cgroup, e.g. "/kubepods/pod123/container456". Empty if
	// the process has no cgroup v2 entry (cgroup v1 only, or no cgroup);
	// detectCgroupResourceLimits gives up in that case because we cannot
	// locate the cgroup directory without it.
	cgroupV2Path string

	// cpuAllowed is the count of CPUs in /proc/<pid>/status
	// Cpus_allowed_list. Zero if the field was missing or unreadable, in
	// which case cpuAllowedLimit treats it as "no signal".
	cpuAllowed int
}

// readCgroupProcInfo reads /proc data for the configured pid (or self).
//
// On success, returns the cgroup v2 path and CPU affinity count for the
// process, plus its visible mount table. Returns an error only if procfs
// itself, the process directory, or the mount/cgroup files are unreadable.
//
// info.cgroupV2Path may legitimately be empty even on success: it is the
// /proc/<pid>/cgroup entry with no controllers, which is absent when the
// system runs cgroup v1 only. The caller treats that as "no v2 limits to
// detect" rather than as an error.
//
// info.cpuAllowed is best-effort. /proc/<pid>/status is independent from
// the cgroup files, so a missing or malformed status leaves cpuAllowed = 0
// without affecting the rest of detection.
func readCgroupProcInfo(paths cgroupPaths) (procCgroupInfo, []*procfs.MountInfo, error) {
	root := paths.procRoot
	if root == "" {
		root = procfs.DefaultMountPoint
	}

	fs, err := procfs.NewFS(root)
	if err != nil {
		return procCgroupInfo{}, nil, err
	}

	// Prefer pid-addressed reads when set so tests can inspect a
	// synthetic process under a fake /proc tree. In production, paths.pid
	// is 0 and we read /proc/self.
	//
	// Mounts must come from the same process's mountinfo because mount
	// namespaces can differ between processes — using the wrong process's
	// mount table would point cgroupDir at directories that do not exist
	// inside this process's view.
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

	// Cgroup v2 has exactly one unified hierarchy. It is written as
	// "0::<path>" in /proc/<pid>/cgroup — hierarchy id 0 with no
	// controllers — and procfs surfaces it as a Cgroup with empty
	// Controllers. Stop at the first match; there is at most one v2 entry
	// per process.
	var info procCgroupInfo
	for _, cgroup := range cgroups {
		if len(cgroup.Controllers) == 0 {
			info.cgroupV2Path = cgroup.Path
			break
		}
	}

	// Best-effort: a missing or unparseable status file does not block
	// cgroup-based memory or cpu.max detection.
	if status, err := proc.NewStatus(); err == nil {
		info.cpuAllowed = len(status.CpusAllowedList)
	}
	return info, mounts, nil
}

// MemoryStats returns the live cgroup memory usage paired with the cached
// finite memory limit.
//
// ok is true only when the limit was finite at detection time AND the live
// memory.current read succeeds; in that case current and limit come from
// the same cgroup directory, so the percentage current/limit is always
// meaningful. ok is false on the host (no memory limit applied) or if
// memory.current became unreadable since detection (e.g. the cgroup was
// migrated or destroyed). Callers should fall back to host-wide memory
// metrics when ok is false.
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

// MemoryLimit returns the cached finite memory limit. ok is false when no
// memory limit applied at startup (memory.max was "max" or unreadable).
func (c *cgroupResourceLimits) MemoryLimit() (uint64, bool) {
	return c.memoryLimitBytes, c.memoryLimitBytes > 0
}

// CPULimit returns the cached effective CPU count. Zero means no CPU
// restriction; callers should fall back to the host's physical CPU count
// when zero is returned.
func (c *cgroupResourceLimits) CPULimit() float64 {
	return c.cpuLimit
}

// memoryLimit reads memory.max from a cgroup directory and returns it
// alongside the path to the matching memory.current file.
//
// Pre: dir is the absolute path of a cgroup v2 directory.
// Post: returns ("", 0) if memory.max is missing or unbounded — the
// caller treats this as "no memory limit applies". When the limit is
// finite, currentFile is in the same directory so live reads stay
// consistent with the cached limit.
func memoryLimit(dir string) (currentFile string, limit uint64) {
	limit, ok := readCgroupUint(filepath.Join(dir, cgroupV2MemoryMaxFile))
	if !ok || limit == 0 {
		return "", 0
	}
	return filepath.Join(dir, cgroupV2MemoryCurrentFile), limit
}

// cpuQuotaLimit reads cpu.max from a cgroup directory and returns the
// effective CPU count (quota / period).
//
// Pre: dir is the absolute path of a cgroup v2 directory.
// Post: returns 0 ("no cpu.max-imposed limit") when cpu.max is missing,
// unbounded, or malformed. The caller folds this into minPositive with
// cpuAllowedLimit, so 0 is a sentinel rather than a CPU value.
func cpuQuotaLimit(dir string) float64 {
	quota, period, ok := readCgroupV2CPUMax(filepath.Join(dir, cgroupV2CPUMaxFile))
	if !ok || quota <= 0 || period <= 0 {
		return 0
	}
	return float64(quota) / float64(period)
}

// cpuAllowedLimit treats /proc/<pid>/status Cpus_allowed_list as a CPU
// limit when, and only when, it is strictly smaller than the host's
// logical CPU count.
//
// Why this exists separately from cpu.max: containers commonly omit
// cpu.max but pin the workload via cpuset (e.g. Kubernetes static CPU
// manager), so the affinity list is the only signal that the process
// cannot use all host CPUs. Conversely, on a host without cpuset
// restrictions the affinity list equals the full set of logical CPUs;
// treating that as a "limit" would change CPU normalization for every
// host-mode user, so we filter it out.
//
// Pre:
//   - allowed is the count from /proc/<pid>/status Cpus_allowed_list,
//     or 0 if the field was missing.
//   - logicalCPUCount is the host's logical CPU count, or 0 if cpu.Counts
//     could not determine it.
//
// Post: returns 0 ("no affinity-imposed limit") when:
//   - allowed <= 0 (no signal); or
//   - logicalCPUCount > 0 AND allowed >= logicalCPUCount (the process
//     can use every CPU; not a real restriction).
//
// When logicalCPUCount is 0 the comparison cannot be made, so we return
// float64(allowed) and let cpuQuotaLimit + minPositive fold it in. This
// risks reporting a redundant limit on hosts where we could not read the
// CPU count, which we accept rather than silently drop a real restriction.
func cpuAllowedLimit(allowed, logicalCPUCount int) float64 {
	if allowed <= 0 {
		return 0
	}
	if logicalCPUCount > 0 && allowed >= logicalCPUCount {
		return 0
	}
	return float64(allowed)
}

// minPositive returns the smaller of two CPU-limit values, treating zero
// or any negative as "missing" rather than "the smallest possible value".
//
// Why not plain min: cpu.max quota and Cpus_allowed_list are independent
// signals. Either may be zero (missing) without invalidating the other.
// Using min would let a missing source drive the result to zero and
// silently discard a real limit from the other source.
//
// Pre: a and b are CPU counts; a value <= 0 is treated as the absence of
// that source's limit.
// Post: returns the smaller positive of {a, b}, or 0 if neither is
// positive. Symmetric in a and b. Negative inputs are clamped to 0 in
// the result so callers never see a non-zero negative.
func minPositive(a, b float64) float64 {
	switch {
	case a <= 0:
		return max(b, 0)
	case b <= 0:
		return max(a, 0)
	default:
		return min(a, b)
	}
}

// cgroupDir maps the cgroup path of this process to a directory under a
// cgroup2 mount. Returns the leaf cgroup directory only; ancestors are
// intentionally not considered (see package comment).
//
// Two complications make this non-trivial:
//
//  1. Bind mounts. A container runtime often bind-mounts only a sub-tree
//     of the host's cgroup hierarchy into the container, so /sys/fs/cgroup
//     inside the container is rooted at e.g. /kubepods/pod123 on the host.
//     mount.Root captures that source path. The cgroup path from
//     /proc/<pid>/cgroup is reported relative to the host cgroup root and
//     therefore must have mount.Root stripped from its prefix before
//     joining under mount.MountPoint, otherwise we look in a directory
//     that does not exist inside the container.
//
//  2. Mountpoint vs. mount root semantics. When mount.Root is "/" (no
//     bind-mount tricks), the cgroup path is appended to the mountpoint
//     unchanged. When mount.Root is a sub-path, we must trim it off the
//     cgroup path; if the cgroup path equals the root exactly, the
//     directory is the mountpoint itself.
//
// Pre:
//   - mount is a cgroup2 entry from /proc/<pid>/mountinfo (caller filtered
//     by FSType already).
//   - cgroupPath is from the unified-hierarchy entry of /proc/<pid>/cgroup;
//     it is always absolute and reported relative to the host cgroup root.
//
// Post: returns an absolute filesystem path inside mount.MountPoint
// pointing at the directory holding memory.max, cpu.max, etc. The path
// is not validated; readCgroupUint and readCgroupV2CPUMax handle missing
// files by returning ok=false.
func cgroupDir(mount *procfs.MountInfo, cgroupPath string) string {
	rel := filepath.Clean(cgroupPath)
	root := filepath.Clean(mount.Root)

	if root != "/" {
		if rel == root {
			rel = "/"
		} else if strings.HasPrefix(rel, root+"/") {
			rel = strings.TrimPrefix(rel, root)
		}
	}

	return filepath.Join(mount.MountPoint, strings.TrimPrefix(rel, "/"))
}

// readCgroupV2CPUMax parses a cpu.max file.
//
// File format (kernel ABI, cgroup v2 "CPU" section): exactly two
// whitespace-separated tokens "$quota $period", both in microseconds.
// $quota is replaced by the literal "max" when no CPU bandwidth limit
// applies; $period is always numeric.
//
// Pre: path is the absolute path to a cpu.max file.
// Post: returns (0, 0, false) if the file is missing, malformed, holds the
// unlimited sentinel, or has a non-positive period; both values may be
// further validated by the caller before division.
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

// readCgroupUint reads a cgroup v2 file containing a single decimal
// uint64 (e.g. memory.max, memory.current).
//
// File format: a single decimal integer with optional whitespace, or the
// literal "max" when the resource is unbounded.
//
// Pre: path is the absolute path of a cgroup file.
// Post: returns (0, false) when the file is missing, blank, holds the
// unlimited sentinel "max", or fails to parse as a uint64. Treating
// "max" as ok=false lets callers branch on the presence of a finite
// limit without needing to know the literal string.
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

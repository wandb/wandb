package monitor

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"maps"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/mem"
	"github.com/shirou/gopsutil/v4/net"
	"github.com/shirou/gopsutil/v4/process"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

var (
	DiskPartitions = disk.Partitions
	DiskIOCounters = func() (map[string]disk.IOCountersStat, error) {
		return disk.IOCounters()
	}
)

// System encapsulates the state needed to monitor resources available on most systems.
//
// It is used to track CPU usage, memory consumption, disk utilization, and network traffic
// for both the entire system and individual processes.
type System struct {
	// pid is the process ID to monitor for CPU and memory usage.
	pid int32

	// System CPU count.
	cpuCount int

	// Logical CPU count.
	cpuCountLogical int

	// Whether to collect process-specific metrics from the entire process tree,
	// starting from the process with PID `pid`.
	trackProcessTree bool

	// diskPaths are the file system paths to monitor.
	diskPaths []string

	// diskDevices are the real devices that back diskPaths.
	diskDevices map[string]struct{}

	// diskIntialReadBytes stores the readings of bytes read from disk at init per device.
	diskIntialReadBytes map[string]uint64

	// diskInitialWriteBytes stores the readings of bytes written to disk at init per device.
	diskInitialWriteBytes map[string]uint64

	// networkBytesSentInit stores the initial network bytes sent to calculate deltas
	networkBytesSentInit int

	// networkBytesRecvInit stores the initial network bytes received to calculate deltas
	networkBytesRecvInit int
}

type SystemParams struct {
	Pid              int32
	DiskPaths        []string
	TrackProcessTree bool
}

func NewSystem(params SystemParams) *System {
	s := &System{
		pid:                   params.Pid,
		trackProcessTree:      params.TrackProcessTree,
		diskPaths:             params.DiskPaths,
		diskDevices:           make(map[string]struct{}),
		diskIntialReadBytes:   make(map[string]uint64),
		diskInitialWriteBytes: make(map[string]uint64),
	}

	// CPU core counts.
	s.cpuCount, _ = cpu.Counts(false)
	s.cpuCountLogical, _ = cpu.Counts(true)

	// Initialize disk devices and I/O counters.
	s.initializeDisk()

	// Initialize network I/O counters.
	netIOCounters, err := net.IOCounters(false)
	if err == nil && len(netIOCounters) > 0 {
		s.networkBytesSentInit = int(netIOCounters[0].BytesSent)
		s.networkBytesRecvInit = int(netIOCounters[0].BytesRecv)
	}

	return s
}

// initializeDisk resolves disk devices from paths, filters them, and sets up I/O counters.
func (s *System) initializeDisk() {
	// Resolve the devices that back the requested paths.
	parts, _ := DiskPartitions(false)

	// rootMissing tracks whether we've seen "/" among mount-points reported by DiskPartitions.
	// If "/" is an `overlay` (happens, e.g. inside Docker), DiskPartitions(false) will
	// filter it out, and we will need to treat this case separately.
	rootMissing := true
	for _, part := range parts {
		if part.Mountpoint == "/" {
			rootMissing = false // normal host, we found the root
		}
		for _, p := range s.diskPaths {
			// Mount-point must be a prefix of the requested path.
			if strings.HasPrefix(p, part.Mountpoint) {
				s.diskDevices[trimDevPrefix(part.Device)] = struct{}{}
			}
		}
	}

	// The caller asked for "/" (the default) but none of the partitions listed it.
	// In that situation, adopt every partition we *did* see as "belonging to /".
	if rootMissing && len(s.diskPaths) == 1 && s.diskPaths[0] == "/" {
		for _, part := range parts {
			dev := trimDevPrefix(part.Device)
			if !pseudoDevice(dev) {
				s.diskDevices[dev] = struct{}{}
			}
		}
	}

	// Keep only the devices present in IOCounters and handle fallback.
	ios, _ := DiskIOCounters()
	s.filterDiskDevices(ios)

	// Initialize I/O counters for the final set of devices.
	if len(ios) > 0 {
		for dev := range s.diskDevices {
			if c, ok := ios[dev]; ok {
				s.diskIntialReadBytes[dev] = c.ReadBytes
				s.diskInitialWriteBytes[dev] = c.WriteBytes
			}
		}
	}
}

// filterDiskDevices refines the list of disk devices to monitor.
//
// It removes devices not in the I/O counters and adds all real devices as a fallback.
func (s *System) filterDiskDevices(ios map[string]disk.IOCountersStat) {
	// Keep only the devices that are also present in IOCounters.
	filtered := make(map[string]struct{})
	for dev := range s.diskDevices {
		if _, ok := ios[dev]; ok {
			filtered[dev] = struct{}{}
		}
	}
	s.diskDevices = filtered

	// Fallback: if nothing matched, watch every real block device.
	if len(s.diskDevices) == 0 {
		for d := range ios {
			if !pseudoDevice(d) {
				s.diskDevices[d] = struct{}{}
			}
		}
	}
}

func trimDevPrefix(path string) string {
	return strings.TrimPrefix(path, "/dev/")
}

func pseudoDevice(d string) bool {
	return strings.HasPrefix(d, "loop") ||
		strings.HasPrefix(d, "ram") ||
		strings.HasPrefix(d, "zram")
}

// processAndDescendants finds the root process and all its children, recursively.
//
// On some systems, this operation can be expensive, so by default it only returns the
// root process, if it exists.
func (s *System) processAndDescendants(ctx context.Context, pid int32) ([]*process.Process, error) {
	rootProc, err := process.NewProcess(pid)
	if err != nil {
		return nil, err
	}

	out := []*process.Process{rootProc}

	if !s.trackProcessTree {
		return out, nil
	}

	queue := []*process.Process{rootProc}

	for len(queue) > 0 {
		// cancel and return early if it's taking too long.
		select {
		case <-ctx.Done():
			return out, nil
		default:
			// continue processing
		}

		currProc := queue[0]
		queue = queue[1:]

		children, err := currProc.Children()
		if err != nil {
			// best effort
			return out, err
		}

		queue = append(queue, children...)
		out = append(out, children...)
	}

	return out, nil
}

// Sample collects current system metrics and returns them in a structured format.
//
// It gathers information about:
//   - Network I/O (bytes sent/received)
//   - Memory usage (system-wide and process-specific)
//   - CPU utilization (process-specific)
//   - Thread count (process-specific)
//   - Disk usage and I/O metrics
func (s *System) Sample() (*spb.StatsRecord, error) {
	metrics := make(map[string]any)
	var errs []error

	proc, err := process.NewProcess(s.pid)
	if err != nil {
		return nil, err
	}

	// Collect network metrics
	if err := s.collectNetworkMetrics(metrics); err != nil {
		errs = append(errs, err)
	}

	// Collect memory metrics
	virtualMem, err := s.collectSystemMemoryMetrics(metrics)
	if err != nil {
		errs = append(errs, err)
	}

	// Collect process-specific metrics
	if err := s.collectProcessTreeMetrics(proc, virtualMem, metrics); err != nil {
		errs = append(errs, err)
	}

	// Collect disk usage metrics
	if err := s.collectDiskUsageMetrics(metrics); err != nil {
		errs = append(errs, err)
	}

	// Collect disk I/O metrics
	if err := s.CollectDiskIOMetrics(metrics); err != nil {
		errs = append(errs, err)
	}

	if len(metrics) == 0 {
		return nil, errors.Join(errs...)
	}

	return marshal(metrics, timestamppb.Now()), errors.Join(errs...)
}

// collectProcessTreeMetrics gathers RSS, CPU%, and thread count for a process and its descendants.
func (s *System) collectProcessTreeMetrics(
	root *process.Process,
	virtualMem *mem.VirtualMemoryStat,
	metrics map[string]any,
) error {
	// Safeguard to prevent processAndDescendants from taking too long.
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	procs, err := s.processAndDescendants(ctx, root.Pid)
	if err != nil {
		return err
	}

	if len(procs) == 0 {
		return fmt.Errorf("system: empty process tree")
	}

	var (
		totalRSS     uint64
		totalCPU     float64
		totalThreads int32
	)

	for _, p := range procs {
		// Memory
		if mi, err := p.MemoryInfo(); err == nil { // accumulate if there is no error.
			totalRSS += mi.RSS
		}

		// CPU
		if pcpu, err := p.CPUPercent(); err == nil { // accumulate if there is no error.
			totalCPU += pcpu // raw – we'll normalise later
		}

		// Threads
		if th, err := p.NumThreads(); err == nil { // accumulate if there is no error.
			totalThreads += th
		}
	}

	metrics["proc.memory.rssMB"] = float64(totalRSS) / 1024 / 1024
	if virtualMem != nil && virtualMem.Total > 0 {
		metrics["proc.memory.percent"] =
			(float64(totalRSS) / float64(virtualMem.Total)) * 100
	}

	// Normalise CPU by logical core-count
	if s.cpuCount > 0 {
		metrics["cpu"] = totalCPU / float64(s.cpuCount)
	} else {
		metrics["cpu"] = totalCPU
	}

	metrics["proc.cpu.threads"] = float64(totalThreads)
	return nil
}

// collectNetworkMetrics gathers network traffic statistics.
func (s *System) collectNetworkMetrics(metrics map[string]any) error {
	netIOCounters, err := net.IOCounters(false)
	if err != nil {
		return err
	}

	if len(netIOCounters) > 0 {
		metrics["network.sent"] = float64(int(netIOCounters[0].BytesSent) - s.networkBytesSentInit)
		metrics["network.recv"] = float64(int(netIOCounters[0].BytesRecv) - s.networkBytesRecvInit)
	}

	return nil
}

// collectSystemMemoryMetrics gathers system-wide memory statistics.
func (s *System) collectSystemMemoryMetrics(metrics map[string]any) (*mem.VirtualMemoryStat, error) {
	virtualMem, err := mem.VirtualMemory()
	if err != nil {
		return nil, err
	}

	// Total system memory usage in percent
	metrics["memory_percent"] = virtualMem.UsedPercent
	// Total system memory available in MB
	metrics["proc.memory.availableMB"] = float64(virtualMem.Available) / 1024 / 1024

	return virtualMem, nil
}

// collectDiskUsageMetrics gathers disk space utilization statistics.
func (s *System) collectDiskUsageMetrics(metrics map[string]any) error {
	var firstErr error

	for _, diskPath := range s.diskPaths {
		usage, err := disk.Usage(diskPath)
		if err != nil {
			if firstErr == nil {
				firstErr = err
			}
			continue
		}

		// Used disk space as a percentage
		metrics[fmt.Sprintf("disk.%s.usagePercent", diskPath)] = usage.UsedPercent
		// Used disk space in GB
		metrics[fmt.Sprintf("disk.%s.usageGB", diskPath)] = float64(usage.Used) / 1024 / 1024 / 1024
	}

	return firstErr
}

// collectDiskIOMetrics gathers disk I/O statistics.
func (s *System) CollectDiskIOMetrics(metrics map[string]any) error {
	ios, err := DiskIOCounters()
	if err != nil {
		if !strings.Contains(err.Error(), "not implemented yet") {
			return err
		}
		return nil
	}

	for dev := range s.diskDevices {
		c, ok := ios[dev]
		if !ok {
			continue // device disappeared?
		}

		inBytes := c.ReadBytes - s.diskIntialReadBytes[dev]
		outBytes := c.WriteBytes - s.diskInitialWriteBytes[dev]

		// MB read / written per device
		metrics[fmt.Sprintf("disk.%s.in", dev)] = float64(inBytes) / 1024 / 1024
		metrics[fmt.Sprintf("disk.%s.out", dev)] = float64(outBytes) / 1024 / 1024
	}
	return nil
}

// getSlurmEnvVars collects SLURM-related environment variables.
func getSlurmEnvVars() map[string]string {
	slurmVars := make(map[string]string)

	for _, envVar := range os.Environ() {
		parts := strings.SplitN(envVar, "=", 2)
		if len(parts) != 2 {
			continue
		}

		key := parts[0]
		value := parts[1]

		if strings.HasPrefix(key, "SLURM_") {
			suffix := strings.ToLower(strings.TrimPrefix(key, "SLURM_"))
			slurmVars[suffix] = value
		}
	}

	return slurmVars
}

// Probe collects system information.
//
// Gathers hardware details about the system including:
//   - CPU information (count, logical count)
//   - Memory information (total available)
//   - Disk information (space usage for monitored paths)
//   - SLURM environment variables if running in a SLURM environment
func (s *System) Probe(ctx context.Context) *spb.EnvironmentRecord {
	// TODO: capture more detailed CPU information.
	info := &spb.EnvironmentRecord{
		Disk:   make(map[string]*spb.DiskInfo),
		Memory: &spb.MemoryInfo{},
	}

	// Collect memory information
	if virtualMem, err := mem.VirtualMemoryWithContext(ctx); err == nil { // store if no error.
		info.Memory.Total = virtualMem.Total
	}

	// Collect CPU information
	if cpuCount, err := cpu.CountsWithContext(ctx, false); err == nil { // store if no error.
		info.CpuCount = uint32(cpuCount)
	}
	if cpuCountLogical, err := cpu.CountsWithContext(ctx, true); err == nil { // store if no error.
		info.CpuCountLogical = uint32(cpuCountLogical)
	}

	// Collect disk information.
	for _, diskPath := range s.diskPaths {
		if usage, err := disk.UsageWithContext(ctx, diskPath); err == nil { // store if no error.
			info.Disk[diskPath] = &spb.DiskInfo{
				Total: usage.Total,
				Used:  usage.Used,
			}
		}
	}

	// Collect SLURM environment variables.
	if slurmVars := getSlurmEnvVars(); len(slurmVars) > 0 {
		info.Slurm = make(map[string]string)
		maps.Copy(info.Slurm, slurmVars)
	}

	return info
}

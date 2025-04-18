package monitor

import (
	"errors"
	"fmt"
	"os"
	"strings"

	"maps"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/mem"
	"github.com/shirou/gopsutil/v4/net"
	"github.com/shirou/gopsutil/v4/process"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// System encapsulates the state needed to monitor resources available on most systems.
//
// It is used to track CPU usage, memory consumption, disk utilization, and network traffic
// for both the entire system and individual processes.
type System struct {
	// pid is the process ID to monitor for CPU and memory usage
	pid int32

	// diskPaths contains the paths to monitor for disk usage
	diskPaths []string

	// diskReadBytesInit stores the initial disk read bytes to calculate deltas
	diskReadBytesInit int

	// diskWriteBytesInit stores the initial disk write bytes to calculate deltas
	diskWriteBytesInit int

	// networkBytesSentInit stores the initial network bytes sent to calculate deltas
	networkBytesSentInit int

	// networkBytesRecvInit stores the initial network bytes received to calculate deltas
	networkBytesRecvInit int
}

func NewSystem(pid int32, diskPaths []string) *System {
	s := &System{pid: pid, diskPaths: diskPaths}

	// Initialize disk I/O counters
	ioCounters, err := disk.IOCounters()
	if err == nil && len(ioCounters) > 0 {
		// Use the first disk as baseline if available
		// TODO: monitor all disks
		if counter, ok := ioCounters["disk0"]; ok {
			s.diskReadBytesInit = int(counter.ReadBytes)
			s.diskWriteBytesInit = int(counter.WriteBytes)
		}
	}

	// Initialize network I/O counters
	netIOCounters, err := net.IOCounters(false)
	if err == nil && len(netIOCounters) > 0 {
		s.networkBytesSentInit = int(netIOCounters[0].BytesSent)
		s.networkBytesRecvInit = int(netIOCounters[0].BytesRecv)
	}

	return s
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

	proc := process.Process{Pid: s.pid}

	// Collect network metrics
	if err := s.collectNetworkMetrics(metrics); err != nil {
		errs = append(errs, err)
	}

	// Collect memory metrics
	virtualMem, err := s.collectSystemMemoryMetrics(metrics)
	if err != nil {
		errs = append(errs, err)
	}

	// Collect process memory metrics
	if err := s.collectProcessMemoryMetrics(&proc, virtualMem, metrics); err != nil {
		errs = append(errs, err)
	}

	// Collect CPU metrics
	if err := s.collectCPUMetrics(&proc, metrics); err != nil {
		errs = append(errs, err)
	}

	// Collect thread metrics
	if err := s.collectThreadMetrics(&proc, metrics); err != nil {
		errs = append(errs, err)
	}

	// Collect disk usage metrics
	if err := s.collectDiskUsageMetrics(metrics); err != nil {
		errs = append(errs, err)
	}

	// Collect disk I/O metrics
	if err := s.collectDiskIOMetrics(metrics); err != nil {
		errs = append(errs, err)
	}

	if len(metrics) == 0 {
		return nil, errors.Join(errs...)
	}

	return marshal(metrics, timestamppb.Now()), errors.Join(errs...)
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

// collectProcessMemoryMetrics gathers process-specific memory statistics.
func (s *System) collectProcessMemoryMetrics(proc *process.Process, virtualMem *mem.VirtualMemoryStat, metrics map[string]any) error {
	procMem, err := proc.MemoryInfo()
	if err != nil {
		return err
	}

	// Process memory usage in MB
	metrics["proc.memory.rssMB"] = float64(procMem.RSS) / 1024 / 1024

	// Process memory usage in percent
	if virtualMem != nil && virtualMem.Total > 0 {
		metrics["proc.memory.percent"] = float64(procMem.RSS) / float64(virtualMem.Total) * 100
	}

	return nil
}

// collectCPUMetrics gathers CPU utilization statistics.
func (s *System) collectCPUMetrics(proc *process.Process, metrics map[string]any) error {
	procCPU, err := proc.CPUPercent()
	if err != nil {
		return err
	}

	// Get CPU count to normalize the percentage
	cpuCount, err := cpu.Counts(true)
	if err != nil {
		// If we can't get the CPU count, use the raw value
		metrics["cpu"] = procCPU
		return err
	}

	// Normalize CPU usage by core count
	if cpuCount > 0 {
		metrics["cpu"] = procCPU / float64(cpuCount)
	} else {
		metrics["cpu"] = procCPU
	}

	// total system CPU usage in percent
	// TODO: make logging this configurable.
	// utilization, err := cpu.Percent(0, true)
	// if err != nil {
	// 	// do not log "not implemented yet" errors
	// 	if !strings.Contains(err.Error(), "not implemented yet") {
	// 		errs = append(errs, err)
	// 	}
	// } else {
	// 	for i, u := range utilization {
	// 		metrics[fmt.Sprintf("cpu.%d.cpu_percent", i)] = u
	// 	}
	// }

	return nil
}

// collectThreadMetrics gathers thread count statistics.
func (s *System) collectThreadMetrics(proc *process.Process, metrics map[string]any) error {
	procThreads, err := proc.NumThreads()
	if err != nil {
		return err
	}

	metrics["proc.cpu.threads"] = float64(procThreads)
	return nil
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
func (s *System) collectDiskIOMetrics(metrics map[string]any) error {
	ioCounters, err := disk.IOCounters()
	if err != nil {
		// Don't report "not implemented yet" errors
		if !strings.Contains(err.Error(), "not implemented yet") {
			return err
		}
		return nil
	}

	// Get data from the first disk if available
	if counter, ok := ioCounters["disk0"]; ok {
		// MB read/written
		metrics["disk.in"] = float64(int(counter.ReadBytes)-s.diskReadBytesInit) / 1024 / 1024
		metrics["disk.out"] = float64(int(counter.WriteBytes)-s.diskWriteBytesInit) / 1024 / 1024
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

// Probe collects system information for metadata reporting.
//
// Gathers hardware details about the system including:
//   - CPU information (count, logical count)
//   - Memory information (total available)
//   - Disk information (space usage for monitored paths)
//   - SLURM environment variables if running in a SLURM environment
func (s *System) Probe() *spb.MetadataRequest {
	info := &spb.MetadataRequest{
		Cpu:    &spb.CpuInfo{},
		Disk:   make(map[string]*spb.DiskInfo),
		Memory: &spb.MemoryInfo{},
	}

	// Collect memory information
	if virtualMem, err := mem.VirtualMemory(); err == nil {
		info.Memory.Total = virtualMem.Total
	}

	// Collect CPU information
	if cpuCount, err := cpu.Counts(false); err == nil {
		info.CpuCount = uint32(cpuCount)
		info.Cpu.Count = uint32(cpuCount)
	}

	if cpuCountLogical, err := cpu.Counts(true); err == nil {
		info.CpuCountLogical = uint32(cpuCountLogical)
		info.Cpu.CountLogical = uint32(cpuCountLogical)
	}

	// Collect disk information
	for _, diskPath := range s.diskPaths {
		if usage, err := disk.Usage(diskPath); err == nil {
			info.Disk[diskPath] = &spb.DiskInfo{
				Total: usage.Total,
				Used:  usage.Used,
			}
		}
	}

	// Collect SLURM environment variables
	if slurmVars := getSlurmEnvVars(); len(slurmVars) > 0 {
		info.Slurm = make(map[string]string)
		maps.Copy(info.Slurm, slurmVars)
	}

	return info
}

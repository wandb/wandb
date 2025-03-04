package monitor

import (
	"errors"
	"fmt"
	"os"
	"strings"

	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/mem"
	"github.com/shirou/gopsutil/v4/net"
	"github.com/shirou/gopsutil/v4/process"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type System struct {
	pid                  int32
	diskPaths            []string
	diskReadBytesInit    int
	diskWriteBytesInit   int
	networkBytesSentInit int
	networkBytesRecvInit int
}

func NewSystem(pid int32, diskPaths []string) *System {
	s := &System{pid: pid, diskPaths: diskPaths}

	// TODO: collect metrics for each disk
	ioCounters, err := disk.IOCounters()
	if err == nil {
		s.diskReadBytesInit = int(ioCounters["disk0"].ReadBytes)
		s.diskWriteBytesInit = int(ioCounters["disk0"].WriteBytes)
	}

	netIOCounters, err := net.IOCounters(false)
	if err == nil {
		s.networkBytesSentInit = int(netIOCounters[0].BytesSent)
		s.networkBytesRecvInit = int(netIOCounters[0].BytesRecv)
	}

	return s
}

func (s *System) Name() string { return "system" }

func (s *System) Sample() (*spb.StatsRecord, error) {

	metrics := make(map[string]any)
	var errs []error

	proc := process.Process{Pid: s.pid}

	netIOCounters, err := net.IOCounters(false)
	if err != nil {
		errs = append(errs, err)
	} else {
		metrics["network.sent"] = float64(int(netIOCounters[0].BytesSent) - s.networkBytesSentInit)
		metrics["network.recv"] = float64(int(netIOCounters[0].BytesRecv) - s.networkBytesRecvInit)
	}

	virtualMem, err := mem.VirtualMemory()

	if err != nil {
		errs = append(errs, err)
	} else {
		// total system memory usage in percent
		metrics["memory_percent"] = virtualMem.UsedPercent
		// total system memory available in MB
		metrics["proc.memory.availableMB"] = float64(virtualMem.Available) / 1024 / 1024
	}

	procMem, err := proc.MemoryInfo()
	if err != nil {
		errs = append(errs, err)
	} else {
		// process memory usage in MB
		metrics["proc.memory.rssMB"] = float64(procMem.RSS) / 1024 / 1024
		// process memory usage in percent
		// vertualMem.Total should not be nil
		if virtualMem != nil {
			metrics["proc.memory.percent"] = float64(procMem.RSS) / float64(virtualMem.Total) * 100
		}
	}

	// process CPU usage in percent
	procCPU, err := proc.CPUPercent()
	if err != nil {
		errs = append(errs, err)
	} else {
		// cpu count
		cpuCount, err := cpu.Counts(true)
		if err != nil {
			errs = append(errs, err)
			// if we can't get the cpu count, we'll just use the raw value
			metrics["cpu"] = procCPU
		} else {
			metrics["cpu"] = procCPU / float64(cpuCount)
		}
	}
	// number of threads used by process
	procThreads, err := proc.NumThreads()
	if err != nil {
		errs = append(errs, err)
	} else {
		metrics["proc.cpu.threads"] = float64(procThreads)
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

	for _, diskPath := range s.diskPaths {
		usage, err := disk.Usage(diskPath)
		if err != nil {
			errs = append(errs, err)
		} else {
			// used disk space as a percentage
			metrics[fmt.Sprintf("disk.%s.usagePercent", diskPath)] = usage.UsedPercent
			// used disk space in GB
			metrics[fmt.Sprintf("disk.%s.usageGB", diskPath)] = float64(usage.Used) / 1024 / 1024 / 1024
		}
	}

	// IO counters
	ioCounters, err := disk.IOCounters()
	if err != nil {
		// do not log "not implemented yet" errors
		if !strings.Contains(err.Error(), "not implemented yet") {
			errs = append(errs, err)
		}
	} else {
		// MB read/written
		fmt.Println(ioCounters) // TODO: remove
		metrics["disk.in"] = float64(int(ioCounters["disk0"].ReadBytes)-s.diskReadBytesInit) / 1024 / 1024
		metrics["disk.out"] = float64(int(ioCounters["disk0"].WriteBytes)-s.diskWriteBytesInit) / 1024 / 1024
	}

	if len(metrics) == 0 {
		return nil, errors.Join(errs...)
	}

	return marshal(metrics, timestamppb.Now()), errors.Join(errs...)
}

func (s *System) IsAvailable() bool { return true }

func getSlurmEnvVars() map[string]string {
	// capture SLURM-related environment variables
	slurmVars := make(map[string]string)
	for _, envVar := range os.Environ() {
		keyValPair := strings.SplitN(envVar, "=", 2)
		key := keyValPair[0]
		value := keyValPair[1]

		if strings.HasPrefix(key, "SLURM_") {
			suffix := strings.ToLower(strings.TrimPrefix(key, "SLURM_"))
			slurmVars[suffix] = value
		}
	}
	return slurmVars
}

func (s *System) Probe() *spb.MetadataRequest {
	info := &spb.MetadataRequest{
		Cpu:    &spb.CpuInfo{},
		Disk:   make(map[string]*spb.DiskInfo),
		Memory: &spb.MemoryInfo{},
	}

	virtualMem, err := mem.VirtualMemory()
	if err == nil {
		info.Memory.Total = virtualMem.Total
	}

	// cpu
	cpuCount, err := cpu.Counts(false)
	if err == nil {
		info.CpuCount = uint32(cpuCount)
		info.Cpu.Count = uint32(cpuCount)
	}
	cpuCountLogical, err2 := cpu.Counts(true)
	if err2 == nil {
		info.CpuCountLogical = uint32(cpuCountLogical)
		info.Cpu.CountLogical = uint32(cpuCountLogical)
	}
	// TODO: add more info from cpuInfo
	// cpuInfo, err := cpu.Info()

	// disk
	for _, diskPath := range s.diskPaths {
		usage, err := disk.Usage(diskPath)
		if err != nil {
			continue
		}
		info.Disk[diskPath] = &spb.DiskInfo{
			Total: usage.Total,
			Used:  usage.Used,
		}
	}

	// TODO: network info

	// Capture SLURM-related environment variables
	if slurmVars := getSlurmEnvVars(); len(slurmVars) > 0 {
		info.Slurm = make(map[string]string)
		for k, v := range slurmVars {
			info.Slurm[k] = v
		}
	}

	return info
}

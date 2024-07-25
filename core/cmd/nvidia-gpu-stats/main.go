package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"time"

	"github.com/shirou/gopsutil/v4/process"

	"github.com/NVIDIA/go-nvml/pkg/nvml"
)

type GPUNvidia struct {
	pid      int
	nvmlInit nvml.Return
}

func NewGPUNvidia(pid int) *GPUNvidia {
	return &GPUNvidia{pid: pid}
}

func (g *GPUNvidia) gpuInUseByProcess(device nvml.Device) bool {
	proc, err := process.NewProcess(int32(g.pid))
	if err != nil {
		// user process does not exist
		return false
	}

	ourPids := make(map[int32]struct{})
	// add user process pid
	ourPids[int32(g.pid)] = struct{}{}

	// find user process's children
	childProcs, err := proc.Children()
	if err == nil {
		for _, childProc := range childProcs {
			ourPids[childProc.Pid] = struct{}{}
		}
	}

	computeProcesses, ret := device.GetComputeRunningProcesses()
	if ret != nvml.SUCCESS {
		return false
	}
	graphicsProcesses, ret := device.GetGraphicsRunningProcesses()
	if ret != nvml.SUCCESS {
		return false
	}
	pidsUsingDevice := make(map[int32]struct{})
	for _, p := range computeProcesses {
		pidsUsingDevice[int32(p.Pid)] = struct{}{}
	}
	for _, p := range graphicsProcesses {
		pidsUsingDevice[int32(p.Pid)] = struct{}{}
	}

	intersectionCount := 0
	for pid := range pidsUsingDevice {
		if _, exists := ourPids[pid]; exists {
			intersectionCount++
		}
	}

	return intersectionCount > 0
}

func (g *GPUNvidia) SampleMetrics() map[string]any {
	metrics := make(map[string]any)

	// we would only call this method if NVML is available
	if g.nvmlInit != nvml.SUCCESS {
		return nil
	}

	count, ret := nvml.DeviceGetCount()
	if ret != nvml.SUCCESS {
		return nil
	}
	metrics["gpu.count"] = count

	for di := 0; di < count; di++ {
		device, ret := nvml.DeviceGetHandleByIndex(di)
		if ret != nvml.SUCCESS {
			return nil
		}

		// get device name and total memory
		name, ret := device.GetName()
		if ret == nvml.SUCCESS {
			key := fmt.Sprintf("gpu.%d.name", di)
			metrics[key] = name
		}

		// gpu in use by process?
		gpuInUseByProcess := g.gpuInUseByProcess(device)

		// device utilization
		utilization, ret := device.GetUtilizationRates()
		if ret == nvml.SUCCESS {
			// gpu utilization rate
			key := fmt.Sprintf("gpu.%d.gpu", di)
			metrics[key] = float64(utilization.Gpu)
			// gpu utilization rate (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.gpu", di)
				metrics[keyProc] = metrics[key]
			}

			// memory utilization rate
			key = fmt.Sprintf("gpu.%d.memory", di)
			metrics[key] = float64(utilization.Memory)
			// memory utilization rate (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.memory", di)
				metrics[keyProc] = metrics[key]
			}
		}

		memoryInfo, ret := device.GetMemoryInfo()
		if ret == nvml.SUCCESS {
			// memory total
			key := fmt.Sprintf("gpu.%d.memoryTotal", di)
			metrics[key] = memoryInfo.Total

			// memory allocated
			key = fmt.Sprintf("gpu.%d.memoryAllocated", di)
			metrics[key] = float64(memoryInfo.Used) / float64(memoryInfo.Total) * 100
			// memory allocated (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.memoryAllocated", di)
				metrics[keyProc] = metrics[key]
			}

			// memory allocated (bytes)
			key = fmt.Sprintf("gpu.%d.memoryAllocatedBytes", di)
			metrics[key] = float64(memoryInfo.Used)
			// memory allocated (bytes) (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.memoryAllocatedBytes", di)
				metrics[keyProc] = metrics[key]
			}
		}

		temperature, ret := device.GetTemperature(nvml.TEMPERATURE_GPU)
		if ret == nvml.SUCCESS {
			// gpu temperature
			key := fmt.Sprintf("gpu.%d.temp", di)
			metrics[key] = float64(temperature)
			// gpu temperature (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.temp", di)
				metrics[keyProc] = metrics[key]
			}
		}

		// gpu power usage (W)
		powerUsage, ret := device.GetPowerUsage()
		if ret == nvml.SUCCESS {
			key := fmt.Sprintf("gpu.%d.powerWatts", di)
			metrics[key] = float64(powerUsage) / 1000
			// gpu power usage (W) (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.powerWatts", di)
				metrics[keyProc] = metrics[key]
			}
		}

		// gpu power limit (W)
		powerLimit, ret := device.GetEnforcedPowerLimit()
		if ret == nvml.SUCCESS {
			key := fmt.Sprintf("gpu.%d.enforcedPowerLimitWatts", di)
			metrics[key] = float64(powerLimit) / 1000
			// gpu power limit (W) (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.enforcedPowerLimitWatts", di)
				metrics[keyProc] = metrics[key]
			}

			// gpu power usage (%)
			key = fmt.Sprintf("gpu.%d.powerPercent", di)
			metrics[key] = float64(powerUsage) / float64(powerLimit) * 100
			// gpu power usage (%) (if in use by process)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.powerPercent", di)
				metrics[keyProc] = metrics[key]
			}
		}

	}

	return metrics
}

func (g *GPUNvidia) IsAvailable() bool {
	defer func() {
		if r := recover(); r != nil {
			g.nvmlInit = nvml.ERROR_UNINITIALIZED
		}
	}()
	g.nvmlInit = nvml.Init()
	return g.nvmlInit == nvml.SUCCESS
}

func (g *GPUNvidia) Close() {
	err := nvml.Shutdown()
	if err != nvml.SUCCESS {
		return
	}
}

func main() {
	samplingInterval := flag.Duration("s", 1*time.Second, "sampling interval")
	pid := flag.Int("pid", 0, "pid of the process to communicate with")

	flag.Parse()

	gpu := NewGPUNvidia(*pid)
	defer gpu.Close()

	if !gpu.IsAvailable() {
		return
	}

	// Create a ticker that fires every `samplingInterval` seconds
	ticker := time.NewTicker(*samplingInterval)
	defer ticker.Stop()

	for range ticker.C {
		timeStamp := time.Now()
		metrics := gpu.SampleMetrics()
		if metrics == nil {
			return
		}
		// add timestamp
		metrics["_timestamp"] = timeStamp.Unix()
		// print as JSON
		output, err := json.Marshal(metrics)
		if err != nil {
			return
		}
		fmt.Println(string(output))
	}
}

package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/shirou/gopsutil/v4/process"

	"github.com/NVIDIA/go-nvml/pkg/nvml"
)

type GPUNvidia struct {
	pid      int
	nvmlInit nvml.Return
}

func NewGPUNvidia(pid int) *GPUNvidia {
	start := time.Now()
	g := &GPUNvidia{pid: pid}
	fmt.Printf("NewGPUNvidia duration: %v\n", time.Since(start))
	return g
}

func (g *GPUNvidia) gpuInUseByProcess(device nvml.Device) bool {
	start := time.Now()
	defer func() {
		fmt.Printf("gpuInUseByProcess duration: %v\n", time.Since(start))
	}()

	proc, err := process.NewProcess(int32(g.pid))
	if err != nil {
		return false
	}

	ourPids := make(map[int32]struct{})
	ourPids[int32(g.pid)] = struct{}{}

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
	start := time.Now()
	defer func() {
		fmt.Printf("SampleMetrics total duration: %v\n", time.Since(start))
	}()

	metrics := make(map[string]any)

	if g.nvmlInit != nvml.SUCCESS {
		return nil
	}

	count, ret := nvml.DeviceGetCount()
	if ret != nvml.SUCCESS {
		return nil
	}
	metrics["gpu.count"] = count

	for di := 0; di < count; di++ {
		deviceStart := time.Now()
		device, ret := nvml.DeviceGetHandleByIndex(di)
		if ret != nvml.SUCCESS {
			return nil
		}

		name, ret := device.GetName()
		if ret == nvml.SUCCESS {
			key := fmt.Sprintf("gpu.%d.name", di)
			metrics[key] = name
		}

		gpuInUseByProcess := g.gpuInUseByProcess(device)

		utilization, ret := device.GetUtilizationRates()
		if ret == nvml.SUCCESS {
			key := fmt.Sprintf("gpu.%d.gpu", di)
			metrics[key] = float64(utilization.Gpu)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.gpu", di)
				metrics[keyProc] = metrics[key]
			}

			key = fmt.Sprintf("gpu.%d.memory", di)
			metrics[key] = float64(utilization.Memory)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.memory", di)
				metrics[keyProc] = metrics[key]
			}
		}

		memoryInfo, ret := device.GetMemoryInfo()
		if ret == nvml.SUCCESS {
			key := fmt.Sprintf("gpu.%d.memoryTotal", di)
			metrics[key] = memoryInfo.Total

			key = fmt.Sprintf("gpu.%d.memoryAllocated", di)
			metrics[key] = float64(memoryInfo.Used) / float64(memoryInfo.Total) * 100
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.memoryAllocated", di)
				metrics[keyProc] = metrics[key]
			}

			key = fmt.Sprintf("gpu.%d.memoryAllocatedBytes", di)
			metrics[key] = float64(memoryInfo.Used)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.memoryAllocatedBytes", di)
				metrics[keyProc] = metrics[key]
			}
		}

		temperature, ret := device.GetTemperature(nvml.TEMPERATURE_GPU)
		if ret == nvml.SUCCESS {
			key := fmt.Sprintf("gpu.%d.temp", di)
			metrics[key] = float64(temperature)
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.temp", di)
				metrics[keyProc] = metrics[key]
			}
		}

		powerUsage, ret := device.GetPowerUsage()
		if ret == nvml.SUCCESS {
			key := fmt.Sprintf("gpu.%d.powerWatts", di)
			metrics[key] = float64(powerUsage) / 1000
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.powerWatts", di)
				metrics[keyProc] = metrics[key]
			}
		}

		powerLimit, ret := device.GetEnforcedPowerLimit()
		if ret == nvml.SUCCESS {
			key := fmt.Sprintf("gpu.%d.enforcedPowerLimitWatts", di)
			metrics[key] = float64(powerLimit) / 1000
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.enforcedPowerLimitWatts", di)
				metrics[keyProc] = metrics[key]
			}

			key = fmt.Sprintf("gpu.%d.powerPercent", di)
			metrics[key] = float64(powerUsage) / float64(powerLimit) * 100
			if gpuInUseByProcess {
				keyProc := fmt.Sprintf("gpu.process.%d.powerPercent", di)
				metrics[keyProc] = metrics[key]
			}
		}

		fmt.Printf("Device %d sampling duration: %v\n", di, time.Since(deviceStart))
	}

	return metrics
}

func (g *GPUNvidia) IsAvailable() bool {
	start := time.Now()
	defer func() {
		fmt.Printf("IsAvailable duration: %v\n", time.Since(start))
	}()

	defer func() {
		if r := recover(); r != nil {
			g.nvmlInit = nvml.ERROR_UNINITIALIZED
		}
	}()
	g.nvmlInit = nvml.Init()
	return g.nvmlInit == nvml.SUCCESS
}

func (g *GPUNvidia) Close() {
	start := time.Now()
	err := nvml.Shutdown()
	fmt.Printf("Close duration: %v\n", time.Since(start))
	if err != nvml.SUCCESS {
		return
	}
}

func main() {
	start := time.Now()
	samplingInterval := flag.Duration("s", 1*time.Second, "sampling interval")
	pid := flag.Int("pid", 0, "pid of the process to communicate with")

	flag.Parse()

	gpu := NewGPUNvidia(*pid)
	defer gpu.Close()

	if !gpu.IsAvailable() {
		return
	}

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	ticker := time.NewTicker(*samplingInterval)

	done := make(chan struct{})

	wg := sync.WaitGroup{}
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			select {
			case <-done:
				return
			case <-ticker.C:
				loopStart := time.Now()
				timeStamp := time.Now()
				metrics := gpu.SampleMetrics()
				if metrics == nil {
					continue
				}
				metrics["_timestamp"] = float64(timeStamp.Unix()) + float64(timeStamp.Nanosecond())/1e9
				jsonStart := time.Now()
				output, err := json.Marshal(metrics)
				jsonDuration := time.Since(jsonStart)
				if err != nil {
					continue
				}
				fmt.Println(string(output))
				fmt.Printf("JSON marshal duration: %v\n", jsonDuration)
				fmt.Printf("Total loop duration: %v\n", time.Since(loopStart))
			}
		}
	}()

	<-sigChan

	close(done)
	ticker.Stop()
	wg.Wait()

	fmt.Printf("Total main duration: %v\n", time.Since(start))
}

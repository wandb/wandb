package systemmetrics_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/systemmetrics"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const mib = 1 << 20

func itemMap(rec *spb.SystemMetricsRecord) map[string]string {
	m := map[string]string{}
	for _, item := range systemmetrics.Items(rec) {
		m[item.Key] = item.JSON()
	}
	return m
}

// TestItems_LegacyKeys pins the legacy keys of every field to the keys
// wandb-symon emitted before it sent typed records.
func TestItems_LegacyKeys(t *testing.T) {
	f := proto.Float64
	u := proto.Uint64
	rec := &spb.SystemMetricsRecord{
		Host: &spb.HostMetrics{
			Memory: &spb.MemoryMetrics{UsedRatio: f(0.415), AvailableBytes: u(2 * mib)},
			Swap:   &spb.SwapMetrics{UsedBytes: u(10), UsedRatio: f(0.01)},
			Cpu: &spb.CpuMetrics{
				Cores:        []*spb.CpuCoreMetrics{{Index: 3, UtilizationRatio: f(0.07)}},
				TemperatureC: f(50),
			},
			DiskUsage: []*spb.DiskUsageMetrics{
				{Path: "/", UsedRatio: f(0.6), UsedBytes: u(3 << 30)},
			},
			DiskIo: []*spb.DiskIoMetrics{
				{Device: "nvme0n1p1", ReadBytes: u(mib), WriteBytes: u(2 * mib)},
			},
			Network: &spb.NetworkMetrics{SentBytes: u(1), RecvBytes: u(2), TcpRetransmits: u(3)},
			Apple: &spb.AppleHostMetrics{
				MemoryUsedBytes:      u(1),
				MemoryUsedRatio:      f(0.01),
				EcpuUtilizationRatio: f(0.01),
				EcpuFrequencyHz:      f(1e6),
				PcpuUtilizationRatio: f(0.01),
				PcpuFrequencyHz:      f(1e6),
				CpuPowerW:            f(1),
				SystemPowerW:         f(1),
			},
			Load:    &spb.LoadMetrics{OneMinute: f(1), FiveMinutes: f(1), FifteenMinutes: f(1)},
			UptimeS: f(1),
		},
		Process: &spb.ProcessMetrics{
			CpuRatio:                f(0.01),
			RssBytes:                u(3 * mib),
			MemoryRatio:             f(0.01),
			Threads:                 proto.Uint32(8),
			CgroupCpuThrottledRatio: f(0.01),
			CgroupOomKills:          u(1),
		},
		Sdk: &spb.SdkMetrics{CpuRatio: f(0.01), RssBytes: u(mib)},
		Accelerators: []*spb.AcceleratorMetrics{
			{
				Type:                spb.AcceleratorType_NVIDIA_GPU,
				Index:               0,
				Source:              "nvml",
				Binding:             spb.Binding_PROCESS,
				UtilizationRatio:    f(0.97),
				MemoryActivityRatio: f(0.01),
				MemoryUsedRatio:     f(0.01),
				MemoryUsedBytes:     u(68719476736),
				TemperatureC:        f(1),
				PowerW:              f(1),
				PowerRatio:          f(0.01),
				PowerLimitW:         f(1),
				FanSpeedRatio:       f(0.01),
				EnergyJ:             f(1),
				Vendor: &spb.AcceleratorMetrics_Nvidia{Nvidia: &spb.NvidiaMetrics{
					SmClockHz:                 f(1e6),
					MemoryClockHz:             f(1e6),
					CorrectedMemoryErrors:     u(1),
					UncorrectedMemoryErrors:   u(1),
					PcieTxBytesPerS:           f(1),
					PcieRxBytesPerS:           f(1),
					NvlinkTxBytesPerS:         f(1),
					NvlinkRxBytesPerS:         f(1),
					SmActiveRatio:             f(0.01),
					SmOccupancyRatio:          f(0.01),
					DramActiveRatio:           f(0.01),
					PipeTensorActiveRatio:     f(0.01),
					PipeTensorHmmaActiveRatio: f(0.01),
					PipeFp64ActiveRatio:       f(0.01),
					PipeFp32ActiveRatio:       f(0.01),
					PipeFp16ActiveRatio:       f(0.01),
				}},
			},
			{
				Type:             spb.AcceleratorType_NVIDIA_GPU,
				Index:            1,
				Source:           "dcgm-exporter",
				Host:             "node-7",
				MemoryUsedBytes:  u(4 * mib),
				MemoryTotalBytes: u(8 * mib),
				EnergyJ:          f(2),
				UtilizationRatio: f(0.01),
				Vendor: &spb.AcceleratorMetrics_Nvidia{Nvidia: &spb.NvidiaMetrics{
					SmActiveRatio:                  f(0.5),
					MemoryTemperatureC:             f(1),
					MaxOperatingTemperatureC:       f(1),
					MemoryMaxOperatingTemperatureC: f(1),
					MemoryFreeBytes:                u(mib),
				}},
			},
			{
				Type:                spb.AcceleratorType_AMD_GPU,
				Index:               0,
				MemoryActivityRatio: f(0.01),
				Vendor: &spb.AcceleratorMetrics_Amd{Amd: &spb.AmdMetrics{
					MemoryOverdriveRatio: f(0.01),
				}},
			},
			{
				Type:            spb.AcceleratorType_NVIDIA_GPU,
				Index:           2,
				Uuid:            "MIG-1",
				ParentUuid:      "GPU-2",
				Profile:         "3g.40gb",
				Share:           f(3.0 / 7),
				MemoryUsedBytes: u(1),
			},
			{Type: spb.AcceleratorType_APPLE_GPU, Index: 0, ClockHz: f(1e6)},
			{Type: spb.AcceleratorType_APPLE_ANE, Index: 0, PowerW: f(1)},
			{
				Type:             spb.AcceleratorType_GOOGLE_TPU,
				Index:            2,
				UtilizationRatio: f(0.01),
				MemoryUsedRatio:  f(0.01),
				MemoryUsedBytes:  u(1),
				MemoryTotalBytes: u(1),
				Vendor: &spb.AcceleratorMetrics_Tpu{Tpu: &spb.TpuMetrics{
					DutyCycleRatio:             f(0.01),
					TensorcoreIdleDurationS:    f(1),
					RuntimeHbmUtilizationRatio: f(0.01),
					IciLinkHealth:              f(1),
					ThrottleScore:              f(1),
				}},
			},
			{
				Type:             spb.AcceleratorType_AWS_TRAINIUM,
				Index:            4,
				UtilizationRatio: f(0.01),
				Vendor: &spb.AcceleratorMetrics_Trainium{Trainium: &spb.TrainiumMetrics{
					MemoryConstantsBytes:             u(1),
					MemoryModelCodeBytes:             u(1),
					MemoryModelSharedScratchpadBytes: u(1),
					MemoryRuntimeBytes:               u(1),
					MemoryTensorsBytes:               u(1),
				}},
			},
		},
		TpuRuntime: &spb.TpuRuntimeMetrics{
			Distributions: []*spb.TpuRuntimeMetrics_Distribution{
				{
					Kind:  spb.TpuRuntimeMetrics_HLO_EXEC_TIMING,
					Label: "program_main",
					Mean:  f(1e-6),
					P50:   f(2.5e-6),
				},
				{Kind: spb.TpuRuntimeMetrics_GRPC_TCP_DELIVERY_RATE, P999: f(1e6)},
			},
			HloQueueSizes: []*spb.TpuRuntimeMetrics_QueueSize{
				{Label: "tensor_core_0", Size: f(1)},
			},
		},
		TrainiumHost: &spb.TrainiumHostMetrics{
			HostMemoryBytes:            u(1),
			DeviceMemoryBytes:          u(1),
			HostMemoryApplicationBytes: u(1),
			HostMemoryConstantsBytes:   u(1),
			HostMemoryDmaBuffersBytes:  u(1),
			HostMemoryTensorsBytes:     u(1),
		},
		Generic: []*spb.GenericMetric{
			{Source: "node", Name: "node_load1", Series: 2, Value: f(0.5)},
		},
	}

	assert.Equal(t, map[string]string{
		"memory_percent":          "41.5",
		"proc.memory.availableMB": "2",
		"swap.used":               "10",
		"swap.used_percent":       "1",
		"cpu.3.cpu_percent":       "7",
		"cpu.avg_temp":            "50",
		"disk./.usagePercent":     "60",
		"disk./.usageGB":          "3",
		"disk.nvme0n1p1.in":       "1",
		"disk.nvme0n1p1.out":      "2",
		"network.sent":            "1",
		"network.recv":            "2",
		"network.tcpRetransmits":  "3",
		"memory.used":             "1",
		"memory.used_percent":     "1",
		"cpu.ecpu_percent":        "1",
		"cpu.ecpu_freq":           "1",
		"cpu.pcpu_percent":        "1",
		"cpu.pcpu_freq":           "1",
		"cpu.powerWatts":          "1",
		"system.powerWatts":       "1",
		"system.load1":            "1",
		"system.load5":            "1",
		"system.load15":           "1",
		"system.uptime":           "1",

		"cpu":                       "1",
		"proc.memory.rssMB":         "3",
		"proc.memory.percent":       "1",
		"proc.cpu.threads":          "8",
		"proc.cpu.throttledPercent": "1",
		"proc.memory.oomKills":      "1",
		"wandb.cpu":                 "1",
		"wandb.memory.rssMB":        "1",

		"gpu.0.gpu":                     "97",
		"gpu.0.memory":                  "1",
		"gpu.0.memoryAllocated":         "1",
		"gpu.0.memoryAllocatedBytes":    "68719476736",
		"gpu.0.temp":                    "1",
		"gpu.0.powerWatts":              "1",
		"gpu.0.powerPercent":            "1",
		"gpu.0.enforcedPowerLimitWatts": "1",
		"gpu.0.fanSpeed":                "1",
		"gpu.0.energyJoules":            "1",
		"gpu.0.smClock":                 "1",
		"gpu.0.memoryClock":             "1",
		"gpu.0.correctedMemoryErrors":   "1",
		"gpu.0.uncorrectedMemoryErrors": "1",
		"gpu.0.pcieTxBytes":             "1",
		"gpu.0.pcieRxBytes":             "1",
		"gpu.0.nvlinkTxBytes":           "1",
		"gpu.0.nvlinkRxBytes":           "1",
		"gpu.0.smActive":                "1",
		"gpu.0.smOccupancy":             "1",
		"gpu.0.dramActive":              "1",
		"gpu.0.pipeTensorActive":        "1",
		"gpu.0.pipeTensorHmmaActive":    "1",
		"gpu.0.pipeFp64Active":          "1",
		"gpu.0.pipeFp32Active":          "1",
		"gpu.0.pipeFp16Active":          "1",

		"gpu.process.0.gpu":                     "97",
		"gpu.process.0.memory":                  "1",
		"gpu.process.0.memoryAllocated":         "1",
		"gpu.process.0.memoryAllocatedBytes":    "68719476736",
		"gpu.process.0.temp":                    "1",
		"gpu.process.0.powerWatts":              "1",
		"gpu.process.0.powerPercent":            "1",
		"gpu.process.0.enforcedPowerLimitWatts": "1",

		"gpu.1.gpu/l:node-7":                    "1",
		"gpu.1.memoryUsed/l:node-7":             "4",
		"gpu.1.memoryTotal/l:node-7":            "8",
		"gpu.1.totalEnergyConsumption/l:node-7": "2000",
		"gpu.1.smActive/l:node-7":               "0.5",
		"gpu.1.memoryTemp/l:node-7":             "1",
		"gpu.1.maxOpTemp/l:node-7":              "1",
		"gpu.1.memoryMaxOpTemp/l:node-7":        "1",
		"gpu.1.memoryFree/l:node-7":             "1",

		"gpu.0.memoryReadWriteActivity": "1",
		"gpu.0.memoryOverDrive":         "1",
		"gpu.0.freq":                    "1",
		"ane.power":                     "1",

		"tpu.2.tensorcoreUtilization":  "1",
		"tpu.2.hbmMemoryUsage":         "1",
		"tpu.2.hbmCapacityUsage":       "1",
		"tpu.2.hbmCapacityTotal":       "1",
		"tpu.2.dutyCycle":              "1",
		"tpu.2.tensorcoreIdleDuration": "1",
		"tpu.2.runtimeHbmUtilization":  "1",
		"tpu.2.iciLinkHealth":          "1",
		"tpu.2.throttleScore":          "1",

		"tpu.hloExecTiming.program_main.meanUs": "1",
		"tpu.hloExecTiming.program_main.p50Us":  "2.5",
		"tpu.grpcTcpDeliveryRate.p999Mbps":      "1",
		"tpu.hloQueueSize.tensor_core_0":        "1",

		"trn.4.neuroncore_utilization":                          "1",
		"trn.4.neuroncore_memory_usage.constants":               "1",
		"trn.4.neuroncore_memory_usage.model_code":              "1",
		"trn.4.neuroncore_memory_usage.model_shared_scratchpad": "1",
		"trn.4.neuroncore_memory_usage.runtime_memory":          "1",
		"trn.4.neuroncore_memory_usage.tensors":                 "1",
		"trn.host_total_memory_usage":                           "1",
		"trn.neuron_device_total_memory_usage":                  "1",
		"trn.host_memory_usage.application_memory":              "1",
		"trn.host_memory_usage.constants":                       "1",
		"trn.host_memory_usage.dma_buffers":                     "1",
		"trn.host_memory_usage.tensors":                         "1",

		"openmetrics.node.node_load1.2": "0.5",
	}, itemMap(rec))
}

func TestStatsRecord_MergesLegacyItemsAndSample(t *testing.T) {
	response := &spb.SubscribeResponse{
		Record: &spb.Record{RecordType: &spb.Record_Stats{Stats: &spb.StatsRecord{
			Item: []*spb.StatsItem{{Key: "trn.1.neuroncore_utilization", ValueJson: "5.0"}},
		}}},
		Sample: &spb.SystemMetricsRecord{
			Host: &spb.HostMetrics{
				Network: &spb.NetworkMetrics{SentBytes: proto.Uint64(7)},
			},
		},
	}

	stats := systemmetrics.StatsRecord(response)

	var items [][2]string
	for _, item := range stats.GetItem() {
		items = append(items, [2]string{item.GetKey(), item.GetValueJson()})
	}
	assert.Equal(t, [][2]string{
		{"trn.1.neuroncore_utilization", "5.0"},
		{"network.sent", "7"},
	}, items)
}

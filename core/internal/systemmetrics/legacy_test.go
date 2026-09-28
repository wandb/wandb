package systemmetrics_test

import (
	"strconv"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/systemmetrics"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func itemMap(t *testing.T, rec *spb.SystemMetricsRecord) map[string]float64 {
	t.Helper()
	items := systemmetrics.Items(rec)
	m := make(map[string]float64, len(items))
	for _, item := range items {
		_, dup := m[item.Key]
		require.False(t, dup, "duplicate legacy key %q", item.Key)
		m[item.Key] = item.Value
	}
	return m
}

func TestItems_LegacyKeys(t *testing.T) {
	const gib = 1 << 30

	tests := []struct {
		name string
		rec  *spb.SystemMetricsRecord
		want map[string]float64
	}{
		{
			name: "host and process",
			rec: &spb.SystemMetricsRecord{
				Host: &spb.HostMetrics{
					Memory: &spb.MemoryMetrics{
						UsedPercent:    proto.Float64(42.5),
						AvailableBytes: proto.Uint64(3 * gib),
						Apple: &spb.AppleMemoryMetrics{
							UsedBytes:   proto.Uint64(8 * gib),
							UsedPercent: proto.Float64(50),
						},
					},
					Swap: &spb.SwapMetrics{
						UsedBytes:   proto.Uint64(1024),
						UsedPercent: proto.Float64(1.5),
					},
					DiskUsage: []*spb.DiskUsageMetrics{
						{
							Path:        "/",
							UsedPercent: proto.Float64(55),
							UsedBytes:   proto.Uint64(5 * gib),
						},
					},
					DiskIo: []*spb.DiskIoMetrics{
						{
							Device:     "nvme0n1",
							ReadBytes:  proto.Uint64(5 << 20),
							WriteBytes: proto.Uint64(10 << 20),
						},
					},
					Network: &spb.NetworkMetrics{
						SentBytes: proto.Uint64(1000),
						RecvBytes: proto.Uint64(2000),
					},
					Power: &spb.PowerMetrics{TotalW: proto.Float64(12.5)},
					Cpu: &spb.CpuMetrics{
						Cores: []*spb.CpuCoreMetrics{
							{Index: 3, UtilizationPercent: proto.Float64(77)},
						},
						Apple: &spb.AppleCpuMetrics{
							EcpuUtilizationPercent: proto.Float64(10),
							EcpuFrequencyMhz:       proto.Float64(2000),
							PcpuUtilizationPercent: proto.Float64(20),
							PcpuFrequencyMhz:       proto.Float64(3000),
							TemperatureC:           proto.Float64(45),
							PowerW:                 proto.Float64(5),
						},
					},
				},
				Process: &spb.ProcessMetrics{
					CpuPercent:    proto.Float64(12.5),
					RssBytes:      proto.Uint64(gib),
					MemoryPercent: proto.Float64(6.25),
					Threads:       proto.Uint32(8),
				},
			},
			want: map[string]float64{
				"memory_percent":          42.5,
				"proc.memory.availableMB": 3072,
				"memory.used":             8 * gib,
				"memory.used_percent":     50,
				"swap.used":               1024,
				"swap.used_percent":       1.5,
				"disk./.usagePercent":     55,
				"disk./.usageGB":          5,
				"disk.nvme0n1.in":         5,
				"disk.nvme0n1.out":        10,
				"network.sent":            1000,
				"network.recv":            2000,
				"system.powerWatts":       12.5,
				"cpu.3.cpu_percent":       77,
				"cpu.ecpu_percent":        10,
				"cpu.ecpu_freq":           2000,
				"cpu.pcpu_percent":        20,
				"cpu.pcpu_freq":           3000,
				"cpu.avg_temp":            45,
				"cpu.powerWatts":          5,
				"cpu":                     12.5,
				"proc.memory.rssMB":       1024,
				"proc.memory.percent":     6.25,
				"proc.cpu.threads":        8,
			},
		},
		{
			name: "nvidia via nvml, in use by the process",
			rec: &spb.SystemMetricsRecord{
				Accelerators: []*spb.AcceleratorMetrics{{
					Type:                   spb.AcceleratorType_NVIDIA_GPU,
					Index:                  0,
					Source:                 "nvml",
					InUseByProcess:         proto.Bool(true),
					UtilizationPercent:     proto.Float64(90),
					MemoryActivityPercent:  proto.Float64(30),
					MemoryUsedPercent:      proto.Float64(75),
					MemoryUsedBytes:        proto.Uint64(60 * gib),
					MemoryTotalBytes:       proto.Uint64(80 * gib),
					TemperatureC:           proto.Float64(65),
					PowerW:                 proto.Float64(300),
					PowerPercent:           proto.Float64(42.8),
					PowerLimitW:            proto.Float64(700),
					ClockMhz:               proto.Float64(1980),
					FanSpeedPercent:        proto.Float64(30),
					ProcessMemoryUsedBytes: proto.Uint64(gib),
					Ext: &spb.AcceleratorMetrics_Nvidia{Nvidia: &spb.NvidiaMetrics{
						SmClockMhz:              proto.Float64(1980),
						MemoryClockMhz:          proto.Float64(2619),
						CorrectedMemoryErrors:   proto.Uint64(1),
						UncorrectedMemoryErrors: proto.Uint64(0),
						SmActivePercent:         proto.Float64(55.5),
						DramActivePercent:       proto.Float64(30.1),
						PcieTxBytesPerS:         proto.Float64(1e9),
						NvlinkRxBytesPerS:       proto.Float64(2e9),
					}},
				}},
			},
			want: map[string]float64{
				"gpu.0.gpu":                             90,
				"gpu.0.memory":                          30,
				"gpu.0.memoryAllocated":                 75,
				"gpu.0.memoryAllocatedBytes":            60 * gib,
				"gpu.0.temp":                            65,
				"gpu.0.powerWatts":                      300,
				"gpu.0.powerPercent":                    42.8,
				"gpu.0.enforcedPowerLimitWatts":         700,
				"gpu.0.graphicsClock":                   1980,
				"gpu.0.fanSpeed":                        30,
				"gpu.0.smClock":                         1980,
				"gpu.0.memoryClock":                     2619,
				"gpu.0.correctedMemoryErrors":           1,
				"gpu.0.uncorrectedMemoryErrors":         0,
				"gpu.0.smActive":                        55.5,
				"gpu.0.dramActive":                      30.1,
				"gpu.0.pcieTxBytes":                     1e9,
				"gpu.0.nvlinkRxBytes":                   2e9,
				"gpu.process.0.gpu":                     90,
				"gpu.process.0.memory":                  30,
				"gpu.process.0.memoryAllocated":         75,
				"gpu.process.0.memoryAllocatedBytes":    60 * gib,
				"gpu.process.0.temp":                    65,
				"gpu.process.0.powerWatts":              300,
				"gpu.process.0.powerPercent":            42.8,
				"gpu.process.0.enforcedPowerLimitWatts": 700,
			},
		},
		{
			name: "nvidia via the dcgm exporter on another host",
			rec: &spb.SystemMetricsRecord{
				Accelerators: []*spb.AcceleratorMetrics{{
					Type:             spb.AcceleratorType_NVIDIA_GPU,
					Index:            1,
					Host:             "node1",
					Source:           "dcgm-exporter",
					TemperatureC:     proto.Float64(23),
					MemoryUsedBytes:  proto.Uint64(10 * gib),
					MemoryTotalBytes: proto.Uint64(80 * gib),
					EnergyJ:          proto.Float64(1234.5),
					Ext: &spb.AcceleratorMetrics_Nvidia{Nvidia: &spb.NvidiaMetrics{
						SmActivePercent: proto.Float64(12),
						MemoryFreeBytes: proto.Uint64(70 * gib),
					}},
				}},
			},
			want: map[string]float64{
				"gpu.1.temp/l:node1":                   23,
				"gpu.1.memoryUsed/l:node1":             10240,
				"gpu.1.memoryTotal/l:node1":            81920,
				"gpu.1.totalEnergyConsumption/l:node1": 1234500,
				"gpu.1.smActive/l:node1":               12,
				"gpu.1.memoryFree/l:node1":             71680,
			},
		},
		{
			name: "amd",
			rec: &spb.SystemMetricsRecord{
				Accelerators: []*spb.AcceleratorMetrics{
					{
						Type:                  spb.AcceleratorType_AMD_GPU,
						Index:                 2,
						Source:                "rocm-smi",
						UtilizationPercent:    proto.Float64(50),
						MemoryActivityPercent: proto.Float64(20),
						MemoryUsedPercent:     proto.Float64(40),
						TemperatureC:          proto.Float64(60),
						PowerW:                proto.Float64(200),
						PowerPercent:          proto.Float64(66.6),
						Ext: &spb.AcceleratorMetrics_Amd{
							Amd: &spb.AmdMetrics{MemoryOverdrivePercent: proto.Float64(0)},
						},
					},
				},
			},
			want: map[string]float64{
				"gpu.2.gpu":                     50,
				"gpu.2.memoryReadWriteActivity": 20,
				"gpu.2.memoryAllocated":         40,
				"gpu.2.temp":                    60,
				"gpu.2.powerWatts":              200,
				"gpu.2.powerPercent":            66.6,
				"gpu.2.memoryOverDrive":         0,
			},
		},
		{
			name: "apple gpu and neural engine",
			rec: &spb.SystemMetricsRecord{
				Accelerators: []*spb.AcceleratorMetrics{
					{
						Type:               spb.AcceleratorType_APPLE_GPU,
						Source:             "ioreport",
						UtilizationPercent: proto.Float64(33),
						ClockMhz:           proto.Float64(1200),
						PowerW:             proto.Float64(7.5),
						TemperatureC:       proto.Float64(40),
					},
					{
						Type:   spb.AcceleratorType_APPLE_ANE,
						Source: "ioreport",
						PowerW: proto.Float64(1.25),
					},
				},
			},
			want: map[string]float64{
				"gpu.0.gpu":        33,
				"gpu.0.freq":       1200,
				"gpu.0.powerWatts": 7.5,
				"gpu.0.temp":       40,
				"ane.power":        1.25,
			},
		},
		{
			name: "tpu device and runtime",
			rec: &spb.SystemMetricsRecord{
				Accelerators: []*spb.AcceleratorMetrics{{
					Type:               spb.AcceleratorType_GOOGLE_TPU,
					Index:              3,
					Source:             "libtpu",
					UtilizationPercent: proto.Float64(80),
					MemoryUsedPercent:  proto.Float64(45),
					MemoryUsedBytes:    proto.Uint64(7 * gib),
					MemoryTotalBytes:   proto.Uint64(16 * gib),
					Ext: &spb.AcceleratorMetrics_Tpu{Tpu: &spb.TpuMetrics{
						DutyCyclePercent:             proto.Float64(99),
						TensorcoreIdleDurationS:      proto.Float64(0.5),
						RuntimeHbmUtilizationPercent: proto.Float64(44),
						IciLinkHealth:                proto.Float64(1),
						ThrottleScore:                proto.Float64(0),
					}},
				}},
				TpuRuntime: &spb.TpuRuntimeMetrics{
					Distributions: []*spb.TpuRuntimeMetrics_Distribution{
						{
							Kind:  spb.TpuRuntimeMetrics_HLO_EXEC_TIMING,
							Label: "program_main",
							Mean:  proto.Float64(100),
							P50:   proto.Float64(90),
							P999:  proto.Float64(300),
						},
						{
							Kind: spb.TpuRuntimeMetrics_GRPC_TCP_MIN_RTT,
							Mean: proto.Float64(5),
							P50:  proto.Float64(4),
						},
						{
							Kind: spb.TpuRuntimeMetrics_GRPC_TCP_DELIVERY_RATE,
							P50:  proto.Float64(1000),
						},
					},
					HloQueueSize: []*spb.TpuRuntimeMetrics_QueueSize{
						{Label: "tensor_core_0", Size: proto.Float64(3)},
					},
				},
			},
			want: map[string]float64{
				"tpu.3.tensorcoreUtilization":           80,
				"tpu.3.hbmMemoryUsage":                  45,
				"tpu.3.hbmCapacityUsage":                7 * gib,
				"tpu.3.hbmCapacityTotal":                16 * gib,
				"tpu.3.dutyCycle":                       99,
				"tpu.3.tensorcoreIdleDuration":          0.5,
				"tpu.3.runtimeHbmUtilization":           44,
				"tpu.3.iciLinkHealth":                   1,
				"tpu.3.throttleScore":                   0,
				"tpu.hloExecTiming.program_main.meanUs": 100,
				"tpu.hloExecTiming.program_main.p50Us":  90,
				"tpu.hloExecTiming.program_main.p999Us": 300,
				"tpu.grpcTcpMinRtt.meanUs":              5,
				"tpu.grpcTcpMinRtt.p50Us":               4,
				"tpu.grpcTcpDeliveryRate.p50Mbps":       1000,
				"tpu.hloQueueSize.tensor_core_0":        3,
			},
		},
		{
			name: "trainium",
			rec: &spb.SystemMetricsRecord{
				Accelerators: []*spb.AcceleratorMetrics{{
					Type:               spb.AcceleratorType_AWS_TRAINIUM,
					Index:              1,
					Source:             "neuron-monitor",
					UtilizationPercent: proto.Float64(70),
					Ext: &spb.AcceleratorMetrics_Trainium{Trainium: &spb.TrainiumMetrics{
						MemoryConstantsBytes:             proto.Uint64(1),
						MemoryModelCodeBytes:             proto.Uint64(2),
						MemoryModelSharedScratchpadBytes: proto.Uint64(3),
						MemoryRuntimeBytes:               proto.Uint64(4),
						MemoryTensorsBytes:               proto.Uint64(5),
					}},
				}},
				TrainiumHost: &spb.TrainiumHostMetrics{
					HostMemoryTotalBytes:       proto.Uint64(100),
					DeviceMemoryTotalBytes:     proto.Uint64(200),
					HostMemoryApplicationBytes: proto.Uint64(10),
					HostMemoryConstantsBytes:   proto.Uint64(20),
					HostMemoryDmaBuffersBytes:  proto.Uint64(30),
					HostMemoryTensorsBytes:     proto.Uint64(40),
				},
			},
			want: map[string]float64{
				"trn.1.neuroncore_utilization":                          70,
				"trn.1.neuroncore_memory_usage.constants":               1,
				"trn.1.neuroncore_memory_usage.model_code":              2,
				"trn.1.neuroncore_memory_usage.model_shared_scratchpad": 3,
				"trn.1.neuroncore_memory_usage.runtime_memory":          4,
				"trn.1.neuroncore_memory_usage.tensors":                 5,
				"trn.host_total_memory_usage":                           100,
				"trn.neuron_device_total_memory_usage":                  200,
				"trn.host_memory_usage.application_memory":              10,
				"trn.host_memory_usage.constants":                       20,
				"trn.host_memory_usage.dma_buffers":                     30,
				"trn.host_memory_usage.tensors":                         40,
			},
		},
		{
			name: "generic: scraped, zero valued, and unmodeled first-party",
			rec: &spb.SystemMetricsRecord{
				Generic: []*spb.GenericMetric{
					{
						Source:            "dcgm",
						Name:              "DCGM_FI_DEV_GPU_TEMP",
						Value:             proto.Float64(70),
						LegacySeriesIndex: 1,
					},
					{Source: "dcgm", Name: "DCGM_FI_DEV_XID_ERRORS", Value: proto.Float64(0)},
					{Name: "gpu.0.somethingNew", Value: proto.Float64(1)},
				},
			},
			want: map[string]float64{
				"openmetrics.dcgm.DCGM_FI_DEV_GPU_TEMP.1":   70,
				"openmetrics.dcgm.DCGM_FI_DEV_XID_ERRORS.0": 0,
				"gpu.0.somethingNew":                        1,
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, itemMap(t, tt.rec))
		})
	}
}

func TestLegacyRow(t *testing.T) {
	rec := &spb.SystemMetricsRecord{
		Timestamp: &timestamppb.Timestamp{Seconds: 1_700_000_000, Nanos: 500_000_000},
		Label:     "node-a",
		Process:   &spb.ProcessMetrics{CpuPercent: proto.Float64(12.5)},
		Accelerators: []*spb.AcceleratorMetrics{{
			Type: spb.AcceleratorType_NVIDIA_GPU, Host: "node1", Source: "dcgm-exporter",
			TemperatureC: proto.Float64(23),
		}},
	}

	row := systemmetrics.LegacyRow(rec, time.Unix(1_699_999_000, 0))

	assert.Equal(t, map[string]any{
		"_wandb":                             true,
		"_timestamp":                         1_700_000_000.5,
		"_runtime":                           1000.5,
		"system.cpu/l:node-a":                12.5,
		"system.gpu.0.temp/l:node1/l:node-a": 23.0,
	}, row)
}

func TestFromStatsRecord_RoundTrip(t *testing.T) {
	input := map[string]string{
		"gpu.0.gpu":                            "90",
		"gpu.0.memory":                         "30",
		"gpu.0.memoryAllocatedBytes":           "64424509440",
		"gpu.0.temp":                           "65.5",
		"gpu.0.powerWatts":                     "300.25",
		"gpu.0.smClock":                        "1980",
		"gpu.0.smActive":                       "55.5",
		"gpu.0.pcieTxBytes":                    "1000000000",
		"gpu.process.0.gpu":                    "90",
		"gpu.process.0.memory":                 "30",
		"gpu.process.0.memoryAllocatedBytes":   "64424509440",
		"gpu.process.0.temp":                   "65.5",
		"gpu.process.0.powerWatts":             "300.25",
		"gpu.1.temp":                           "50",
		"gpu.0.freq":                           "1200",
		"tpu.3.dutyCycle":                      "99",
		"tpu.hloExecTiming.program_main.p50Us": "90",
		"tpu.grpcTcpMinRtt.meanUs":             "5",
		"tpu.grpcTcpDeliveryRate.p50Mbps":      "1000",
		"tpu.hloQueueSize.tensor_core_0":       "3",
		"cpu.ecpu_percent":                     "10",
		"ane.power":                            "1.25",
		"memory.used":                          "8589934592",
		"system.powerWatts":                    "12.5",
		"some.unknown.key":                     "7",
	}
	stats := &spb.StatsRecord{Timestamp: &timestamppb.Timestamp{Seconds: 1}}
	for key, value := range input {
		stats.Item = append(stats.Item, &spb.StatsItem{Key: key, ValueJson: value})
	}

	rec := systemmetrics.FromStatsRecord(stats, spb.AcceleratorType_NVIDIA_GPU)

	want := make(map[string]float64, len(input))
	for key, value := range input {
		f, err := strconv.ParseFloat(value, 64)
		require.NoError(t, err)
		want[key] = f
	}
	assert.Equal(t, want, itemMap(t, rec))
	assert.Equal(t, int64(1), rec.GetTimestamp().GetSeconds())

	byType := map[spb.AcceleratorType]*spb.AcceleratorMetrics{}
	for _, acc := range rec.GetAccelerators() {
		if acc.GetIndex() == 0 {
			byType[acc.GetType()] = acc
		}
	}
	nvidia := byType[spb.AcceleratorType_NVIDIA_GPU]
	require.NotNil(t, nvidia)
	assert.Equal(t, "nvml", nvidia.GetSource())
	assert.True(t, nvidia.GetInUseByProcess())
	assert.Equal(t, uint64(64424509440), nvidia.GetMemoryUsedBytes())
	assert.Equal(t, 55.5, nvidia.GetNvidia().GetSmActivePercent())

	apple := byType[spb.AcceleratorType_APPLE_GPU]
	require.NotNil(t, apple, "gpu.0.freq is an Apple-only key")
	assert.Equal(t, "ioreport", apple.GetSource())
	assert.Equal(t, 1200.0, apple.GetClockMhz())

	require.Len(t, rec.GetGeneric(), 1)
	assert.Equal(t, "some.unknown.key", rec.GetGeneric()[0].GetName())
	assert.Empty(t, rec.GetGeneric()[0].GetSource())
}

func TestFromStatsRecord_HintPicksVendor(t *testing.T) {
	stats := &spb.StatsRecord{Item: []*spb.StatsItem{{Key: "gpu.0.gpu", ValueJson: "50"}}}

	rec := systemmetrics.FromStatsRecord(stats, spb.AcceleratorType_AMD_GPU)

	require.Len(t, rec.GetAccelerators(), 1)
	assert.Equal(t, spb.AcceleratorType_AMD_GPU, rec.GetAccelerators()[0].GetType())
	assert.Equal(t, "rocm-smi", rec.GetAccelerators()[0].GetSource())
	assert.Equal(t, 50.0, rec.GetAccelerators()[0].GetUtilizationPercent())
}

package monitor

import (
	"context"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/provenance"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type provenanceFakeResource struct {
	stats *spb.StatsRecord
	env   *spb.EnvironmentRecord
}

func (f *provenanceFakeResource) Sample() (*spb.StatsRecord, error) {
	return proto.Clone(f.stats).(*spb.StatsRecord), nil
}

func (f *provenanceFakeResource) Probe(context.Context) *spb.EnvironmentRecord { return f.env }

func gpuStats() *spb.StatsRecord {
	return &spb.StatsRecord{Item: []*spb.StatsItem{
		{Key: "gpu.process.0.gpu", ValueJson: "90"},
		{Key: "gpu.0.smClock", ValueJson: "1980"},
	}}
}

func gpuStatsWithThrottle() *spb.StatsRecord {
	return &spb.StatsRecord{Item: []*spb.StatsItem{
		{Key: "gpu.process.0.gpu", ValueJson: "90"},
		{Key: "gpu.0.smClock", ValueJson: "1980"},
		{Key: "gpu.0.clockThrottleReasons", ValueJson: "3"},
	}}
}

func publishedStats(fw *runworktest.FakeRunWork) *spb.StatsRecord {
	var stats *spb.StatsRecord
	for _, r := range fw.AllRecords() {
		if s := r.GetStats(); s != nil {
			stats = s
		}
	}
	return stats
}

// newProvenanceMonitor builds a monitor; flushSeconds 0 emits a window line every tick.
func newProvenanceMonitor(
	t *testing.T,
	enabled bool,
	flushSeconds float64,
) (*SystemMonitor, *runworktest.FakeRunWork) {
	t.Helper()
	fw := runworktest.New()
	factory := &SystemMonitorFactory{
		Logger: observabilitytest.NewTestLogger(t),
		Settings: settings.From(&spb.Settings{
			XProvenanceLogs:          wrapperspb.Bool(enabled),
			XProvenanceFlushInterval: wrapperspb.Double(flushSeconds),
			XLabel:                   wrapperspb.String("rank0"),
		}),
		XPUResourceManager: NewXPUResourceManager(false),
	}
	return factory.New(fw), fw
}

func provenanceLines(fw *runworktest.FakeRunWork) []string {
	var lines []string
	for _, r := range fw.AllRecords() {
		if l := r.GetOutputLogger().GetLine(); strings.HasPrefix(l, provenance.LinePrefix) {
			lines = append(lines, l)
		}
	}
	return lines
}

func TestProvenance_DisabledHasNoEmitter(t *testing.T) {
	sm, _ := newProvenanceMonitor(t, false, 0)
	assert.Nil(t, sm.provenance)
}

func TestProvenance_OnlyXPUFeedsEmitter(t *testing.T) {
	sm, fw := newProvenanceMonitor(t, true, 0)
	require.NotNil(t, sm.provenance)
	xpu := &provenanceFakeResource{
		stats: gpuStats(),
		env:   &spb.EnvironmentRecord{GpuNvidia: []*spb.GpuNvidiaInfo{{Uuid: "GPU-aaa"}}},
	}
	dcgm := &provenanceFakeResource{stats: gpuStats()}
	sm.xpu = xpu
	sm.resources = nil
	sm.addResource(xpu)
	sm.addResource(dcgm)

	sm.sample()
	sm.wg.Wait()

	lines := provenanceLines(fw)
	require.Len(t, lines, 2)
	assert.Contains(t, lines[0], `"kind":"rank"`)
	assert.Contains(t, lines[1], `"kind":"window"`)
	// Label-suffixed keys would leave m empty.
	assert.Contains(t, lines[1], `"sm_clock_mhz":[1980]`)
}

func TestProvenance_DeviceBindingReachesEmitter(t *testing.T) {
	sm, fw := newProvenanceMonitor(t, true, 0)
	xpu := &provenanceFakeResource{
		stats: &spb.StatsRecord{Item: []*spb.StatsItem{{Key: "gpu.1.smClock", ValueJson: "1980"}}},
		env: &spb.EnvironmentRecord{GpuNvidia: []*spb.GpuNvidiaInfo{
			{Uuid: "GPU-aaa"}, {Uuid: "GPU-bbb"},
		}},
	}
	sm.xpu = xpu
	sm.resources = nil
	sm.addResource(xpu)

	sm.SetDeviceBinding(&spb.DeviceBindingRecord{Uuid: "GPU-bbb", Source: "cuda_runtime"})
	sm.sample()
	sm.wg.Wait()

	lines := provenanceLines(fw)
	require.Len(t, lines, 2)
	assert.Contains(t, lines[0], `"binding_source":"cuda_runtime"`)
	assert.Contains(t, lines[1], `"gpus":{"GPU-bbb"`)
}

func TestProvenance_StepReachesEmitter(t *testing.T) {
	sm, fw := newProvenanceMonitor(t, true, 0)
	xpu := &provenanceFakeResource{
		stats: gpuStats(),
		env:   &spb.EnvironmentRecord{GpuNvidia: []*spb.GpuNvidiaInfo{{Uuid: "GPU-aaa"}}},
	}
	sm.xpu = xpu
	sm.resources = nil
	sm.addResource(xpu)

	sm.SetStep("trainer/global_step", 7)
	sm.sample()
	sm.wg.Wait()

	lines := provenanceLines(fw)
	require.Len(t, lines, 2)
	for _, l := range lines {
		assert.Contains(t, l, `"step":7,"step_key":"trainer/global_step"`)
	}
	// No RunHandle in this test, so the run never initializes.
	assert.NotContains(t, lines[0], "runtime_s")
	assert.Contains(t, lines[1], `"runtime_s":[null],"step":[7]`)
}

func TestProvenance_DrainAfterFinish(t *testing.T) {
	sm, fw := newProvenanceMonitor(t, true, 60)
	xpu := &provenanceFakeResource{
		stats: gpuStats(),
		env:   &spb.EnvironmentRecord{GpuNvidia: []*spb.GpuNvidiaInfo{{Uuid: "GPU-aaa"}}},
	}
	sm.xpu = xpu
	sm.resources = nil
	sm.addResource(xpu)

	sm.sample()
	sm.wg.Wait()
	require.Len(t, provenanceLines(fw), 1)

	records := sm.DrainProvenance()
	require.Len(t, records, 1)
	assert.Contains(t, records[0].GetOutputLogger().GetLine(), `"kind":"window"`)
	assert.Empty(t, sm.DrainProvenance())
}

// newProvenanceMonitorWithSettings builds a monitor with a single-GPU fake XPU resource attached.
func newProvenanceMonitorWithSettings(
	t *testing.T,
	protoSettings *spb.Settings,
) (*SystemMonitor, *runworktest.FakeRunWork) {
	t.Helper()
	fw := runworktest.New()
	factory := &SystemMonitorFactory{
		Logger:             observabilitytest.NewTestLogger(t),
		Settings:           settings.From(protoSettings),
		XPUResourceManager: NewXPUResourceManager(false),
	}
	sm := factory.New(fw)
	xpu := &provenanceFakeResource{
		stats: gpuStats(),
		env:   &spb.EnvironmentRecord{GpuNvidia: []*spb.GpuNvidiaInfo{{Uuid: "GPU-aaa"}}},
	}
	sm.xpu = xpu
	sm.resources = nil
	sm.addResource(xpu)
	return sm, fw
}

func TestObserveHistoryRow_MetricSetUsesLastValue(t *testing.T) {
	sm, fw := newProvenanceMonitorWithSettings(t, &spb.Settings{
		XProvenanceLogs:       wrapperspb.Bool(true),
		XProvenanceStepMetric: wrapperspb.String("trainer/global_step"),
	})

	row := runhistory.New()
	row.SetFloat(pathtree.PathOf("trainer/global_step"), 7)
	sm.ObserveHistoryRow(row, true, 99)
	sm.sample()
	sm.wg.Wait()

	lines := provenanceLines(fw)
	require.NotEmpty(t, lines)
	for _, l := range lines {
		assert.Contains(t, l, `"step":7,"step_key":"trainer/global_step"`)
	}
}

func TestObserveHistoryRow_MetricAbsentKeepsPrevious(t *testing.T) {
	sm, fw := newProvenanceMonitorWithSettings(t, &spb.Settings{
		XProvenanceLogs:       wrapperspb.Bool(true),
		XProvenanceStepMetric: wrapperspb.String("trainer/global_step"),
	})

	present := runhistory.New()
	present.SetFloat(pathtree.PathOf("trainer/global_step"), 5)
	sm.ObserveHistoryRow(present, true, 1)

	absent := runhistory.New()
	absent.SetFloat(pathtree.PathOf("other_metric"), 1)
	sm.ObserveHistoryRow(absent, true, 2)

	sm.sample()
	sm.wg.Wait()

	lines := provenanceLines(fw)
	require.NotEmpty(t, lines)
	for _, l := range lines {
		assert.Contains(t, l, `"step":5,"step_key":"trainer/global_step"`)
	}
}

func TestObserveHistoryRow_NonSharedUsesRunStep(t *testing.T) {
	sm, fw := newProvenanceMonitorWithSettings(t, &spb.Settings{
		XProvenanceLogs: wrapperspb.Bool(true),
	})

	row := runhistory.New()
	row.SetFloat(pathtree.PathOf("loss"), 0.1)
	sm.ObserveHistoryRow(row, true, 42)
	sm.sample()
	sm.wg.Wait()

	lines := provenanceLines(fw)
	require.NotEmpty(t, lines)
	for _, l := range lines {
		assert.Contains(t, l, `"step":42,"step_key":"_step"`)
	}
}

func TestObserveHistoryRow_SharedModeCountsWriterLocalRows(t *testing.T) {
	sm, fw := newProvenanceMonitorWithSettings(t, &spb.Settings{
		XProvenanceLogs: wrapperspb.Bool(true),
		XShared:         wrapperspb.Bool(true),
	})

	row := runhistory.New()
	row.SetFloat(pathtree.PathOf("loss"), 0.1)
	sm.ObserveHistoryRow(row, false, 0)
	sm.ObserveHistoryRow(row, false, 0)
	sm.sample()
	sm.wg.Wait()

	lines := provenanceLines(fw)
	require.NotEmpty(t, lines)
	for _, l := range lines {
		assert.Contains(t, l, `"step":2,"step_key":"writer_local"`)
	}
}

// A large flush interval avoids emit(), which would hang FakeRunWork once sm.cancel() already closed done.
func TestProvenance_SampleSkipsOnSampleAfterCancel(t *testing.T) {
	sm, _ := newProvenanceMonitor(t, true, 3600)
	xpu := &provenanceFakeResource{
		stats: gpuStats(),
		env:   &spb.EnvironmentRecord{GpuNvidia: []*spb.GpuNvidiaInfo{{Uuid: "GPU-aaa"}}},
	}
	sm.xpu = xpu
	sm.resources = nil
	sm.addResource(xpu)

	sm.cancel()
	sm.sample()
	sm.wg.Wait()

	assert.Empty(t, sm.DrainProvenance())
}

func TestProvenance_ClockThrottleReasonsLogsOnlyEnabled(t *testing.T) {
	sm, fw := newProvenanceMonitor(t, true, 0)
	require.NotNil(t, sm.provenance)
	xpu := &provenanceFakeResource{
		stats: gpuStatsWithThrottle(),
		env:   &spb.EnvironmentRecord{GpuNvidia: []*spb.GpuNvidiaInfo{{Uuid: "GPU-aaa"}}},
	}
	sm.xpu = xpu
	sm.resources = nil
	sm.addResource(xpu)

	sm.sample()
	sm.wg.Wait()

	stats := publishedStats(fw)
	require.NotNil(t, stats)
	var keys []string
	for _, item := range stats.Item {
		keys = append(keys, item.Key)
	}
	assert.NotContains(t, keys, "gpu.0.clockThrottleReasons")
	assert.NotContains(t, keys, "gpu.0.clockThrottleReasons/l:rank0")
	assert.Contains(t, keys, "gpu.process.0.gpu/l:rank0")
	assert.Contains(t, keys, "gpu.0.smClock/l:rank0")

	lines := provenanceLines(fw)
	require.Len(t, lines, 2)
	assert.Contains(t, lines[1], `"throttle_reasons"`)
}

func TestProvenance_ClockThrottleReasonsLogsOnlyDisabled(t *testing.T) {
	sm, fw := newProvenanceMonitor(t, false, 0)
	assert.Nil(t, sm.provenance)
	xpu := &provenanceFakeResource{
		stats: gpuStatsWithThrottle(),
		env:   &spb.EnvironmentRecord{GpuNvidia: []*spb.GpuNvidiaInfo{{Uuid: "GPU-aaa"}}},
	}
	sm.xpu = xpu
	sm.resources = nil
	sm.addResource(xpu)

	sm.sample()
	sm.wg.Wait()

	stats := publishedStats(fw)
	require.NotNil(t, stats)
	var keys []string
	for _, item := range stats.Item {
		keys = append(keys, item.Key)
	}
	assert.NotContains(t, keys, "gpu.0.clockThrottleReasons")
	assert.NotContains(t, keys, "gpu.0.clockThrottleReasons/l:rank0")
	assert.Contains(t, keys, "gpu.process.0.gpu/l:rank0")
	assert.Contains(t, keys, "gpu.0.smClock/l:rank0")
}

func TestSetDeviceBinding_NilSafe(t *testing.T) {
	var sm *SystemMonitor
	sm.SetDeviceBinding(&spb.DeviceBindingRecord{Uuid: "GPU-aaa"})
	sm.SetStep("_step", 1)

	assert.Empty(t, sm.DrainProvenance())

	disabled, _ := newProvenanceMonitor(t, false, 0)
	disabled.SetDeviceBinding(&spb.DeviceBindingRecord{Uuid: "GPU-aaa"})
	disabled.SetStep("_step", 1)
	assert.Empty(t, disabled.DrainProvenance())
}

package provenance_test

import (
	"encoding/json"
	"maps"
	"math"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func intPtr(n int) *int { return &n }

func stats(kv ...string) *spb.StatsRecord {
	r := &spb.StatsRecord{}
	for i := 0; i < len(kv); i += 2 {
		r.Item = append(r.Item, &spb.StatsItem{Key: kv[i], ValueJson: kv[i+1]})
	}
	return r
}

func envRecord(uuids ...string) *spb.EnvironmentRecord {
	e := &spb.EnvironmentRecord{}
	for i, u := range uuids {
		e.GpuNvidia = append(e.GpuNvidia, &spb.GpuNvidiaInfo{
			Uuid: u, PciBusId: "00000000:1" + string(rune('0'+i)) + ":00.0", Serial: "S" + u,
		})
	}
	return e
}

func TestReadLaunch(t *testing.T) {
	tests := []struct {
		name string
		env  map[string]string
		want provenance.Launch
	}{
		{
			name: "slurm only",
			env: map[string]string{
				"SLURM_JOB_ID":          "26",
				"SLURM_CLUSTER_NAME":    "slurm-2",
				"SLURM_STEP_ID":         "0",
				"SLURM_RESTART_COUNT":   "1",
				"SLURM_JOB_NODELIST":    "h[001-024]",
				"SLURM_JOB_NUM_NODES":   "24",
				"SLURM_NTASKS":          "192",
				"SLURM_NTASKS_PER_NODE": "8(x24)",
				"SLURM_PROCID":          "17",
				"SLURM_LOCALID":         "1",
				"SLURM_NODEID":          "2",
				"SLURM_GPUS_ON_NODE":    "8",
			},
			want: provenance.Launch{
				Job: provenance.Job{
					Scheduler:     "slurm",
					Cluster:       "slurm-2",
					ID:            "26",
					StepID:        "0",
					Attempt:       intPtr(1),
					Nodelist:      "h[001-024]",
					NumNodes:      intPtr(24),
					WorldSize:     intPtr(192),
					NtasksPerNode: "8(x24)",
					GpusOnNode:    intPtr(8),
				},
				Rank: provenance.Rank{
					Global:   intPtr(17),
					Local:    intPtr(1),
					Node:     intPtr(2),
					Hostname: "h003",
				},
			},
		},
		{
			name: "torchrun under slurm: torch rank fields win",
			env: map[string]string{
				"SLURM_JOB_ID": "26", "SLURM_PROCID": "2", "SLURM_NTASKS": "2",
				"RANK": "9", "LOCAL_RANK": "1", "GROUP_RANK": "1", "WORLD_SIZE": "16",
				"TORCHELASTIC_RESTART_COUNT": "3", "MASTER_ADDR": "h001",
			},
			want: provenance.Launch{
				Job: provenance.Job{
					Scheduler: "slurm",
					ID:        "26",
					Attempt:   intPtr(3),
					WorldSize: intPtr(16),
				},
				Rank: provenance.Rank{
					Global:   intPtr(9),
					Local:    intPtr(1),
					Node:     intPtr(1),
					Hostname: "h003",
				},
				Env: map[string]string{"MASTER_ADDR": "h001"},
			},
		},
		{
			name: "torchelastic only",
			env: map[string]string{
				"TORCHELASTIC_RUN_ID": "abc",
				"RANK":                "0",
				"LOCAL_RANK":          "0",
				"WORLD_SIZE":          "8",
			},
			want: provenance.Launch{
				Job:  provenance.Job{Scheduler: "torchelastic", ID: "abc", WorldSize: intPtr(8)},
				Rank: provenance.Rank{Global: intPtr(0), Local: intPtr(0), Hostname: "h003"},
				Env:  map[string]string{"TORCHELASTIC_RUN_ID": "abc"},
			},
		},
		{
			name: "openmpi",
			env: map[string]string{
				"OMPI_COMM_WORLD_RANK":       "3",
				"OMPI_COMM_WORLD_LOCAL_RANK": "3",
				"OMPI_COMM_WORLD_SIZE":       "4",
			},
			want: provenance.Launch{
				Job:  provenance.Job{Scheduler: "openmpi", WorldSize: intPtr(4)},
				Rank: provenance.Rank{Global: intPtr(3), Local: intPtr(3), Hostname: "h003"},
			},
		},
		{
			name: "none",
			env:  map[string]string{},
			want: provenance.Launch{
				Job:  provenance.Job{Scheduler: "none"},
				Rank: provenance.Rank{Hostname: "h003"},
			},
		},
		{
			name: "malformed ints omitted, not zeroed",
			env: map[string]string{
				"SLURM_JOB_ID":        "1",
				"SLURM_PROCID":        "x",
				"SLURM_JOB_NUM_NODES": "",
			},
			want: provenance.Launch{
				Job:  provenance.Job{Scheduler: "slurm", ID: "1"},
				Rank: provenance.Rank{Hostname: "h003"},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, provenance.ReadLaunch(tt.env, "h003"))
		})
	}
}

func TestReadLaunch_CapsEnvValues(t *testing.T) {
	l := provenance.ReadLaunch(
		map[string]string{"CUDA_VISIBLE_DEVICES": strings.Repeat("0,", 500)},
		"",
	)
	assert.Len(t, l.Env["CUDA_VISIBLE_DEVICES"], 256)
}

func TestResolveBinding(t *testing.T) {
	gpus := []provenance.GpuIdentity{
		{UUID: "GPU-aaa", IndexHost: intPtr(0)},
		{UUID: "GPU-bbb", IndexHost: intPtr(1)},
	}
	tests := []struct {
		name       string
		metrics    *spb.StatsRecord
		reported   *spb.DeviceBindingRecord
		env        map[string]string
		wantSource string
		wantUUIDs  []string
		ambiguous  bool
	}{
		{
			"single process key",
			stats("gpu.process.1.gpu", "90"),
			nil,
			nil,
			"nvml_process",
			[]string{"GPU-bbb"},
			false,
		},
		{
			"multiple process keys",
			stats("gpu.process.0.gpu", "1", "gpu.process.1.gpu", "90"),
			nil,
			nil,
			"nvml_process",
			[]string{"GPU-aaa", "GPU-bbb"},
			true,
		},
		{
			"reported narrows nvml",
			stats("gpu.process.0.gpu", "1", "gpu.process.1.gpu", "90"),
			&spb.DeviceBindingRecord{Uuid: "gpu-BBB"},
			nil,
			"nvml_process",
			[]string{"GPU-bbb"},
			false,
		},
		{
			"reported disagrees with nvml",
			stats("gpu.process.0.gpu", "1"),
			&spb.DeviceBindingRecord{Uuid: "GPU-bbb"},
			nil,
			"conflict",
			[]string{},
			false,
		},
		{
			"reported only, matched case-insensitively",
			stats("gpu.0.gpu", "1"),
			&spb.DeviceBindingRecord{Uuid: "gpu-bbb"},
			nil,
			"cuda_runtime",
			[]string{"GPU-bbb"},
			false,
		},
		{
			"reported only, unmatched",
			stats(),
			&spb.DeviceBindingRecord{Uuid: "GPU-zzz"},
			nil,
			"cuda_runtime",
			[]string{"GPU-zzz"},
			false,
		},
		{
			"single UUID CVD",
			stats(),
			nil,
			map[string]string{"CUDA_VISIBLE_DEVICES": "GPU-aaa"},
			"cuda_visible_devices_uuid",
			[]string{"GPU-aaa"},
			false,
		},
		{
			"multiple UUID CVD",
			stats(),
			nil,
			map[string]string{"CUDA_VISIBLE_DEVICES": "GPU-aaa,GPU-bbb", "LOCAL_RANK": "1"},
			"unresolved",
			[]string{},
			false,
		},
		{
			"integer CVD",
			stats(),
			nil,
			map[string]string{"CUDA_VISIBLE_DEVICES": "1"},
			"unresolved",
			[]string{},
			false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			b := provenance.ResolveBinding(tt.metrics, gpus, tt.reported, tt.env)
			assert.Equal(t, tt.wantSource, b.Source)
			uuids := []string{}
			for _, g := range b.GPUs {
				uuids = append(uuids, g.UUID)
			}
			assert.Equal(t, tt.wantUUIDs, uuids)
			assert.Equal(t, tt.ambiguous, b.Ambiguous)
		})
	}
}

func TestResolveBinding_ConflictListsBothSets(t *testing.T) {
	gpus := []provenance.GpuIdentity{
		{UUID: "GPU-aaa", IndexHost: intPtr(0)},
		{UUID: "GPU-bbb", IndexHost: intPtr(1)},
	}
	b := provenance.ResolveBinding(
		stats("gpu.process.0.gpu", "1"),
		gpus,
		&spb.DeviceBindingRecord{Uuid: "GPU-bbb"},
		nil,
	)
	require.Len(t, b.GPUsNVML, 1)
	require.Len(t, b.GPUsCudaRuntime, 1)
	assert.Equal(t, "GPU-aaa", b.GPUsNVML[0].UUID)
	assert.Equal(t, "GPU-bbb", b.GPUsCudaRuntime[0].UUID)
}

type harness struct {
	lines     []string
	probes    int
	now       time.Time
	runtime   time.Duration
	runtimeOK bool
	em        *provenance.Emitter
}

// newHarness builds an emitter that flushes every tick unless an option overrides it.
func newHarness(
	env *spb.EnvironmentRecord,
	launch provenance.Launch, //nolint:gocritic // test harness copies the fixture value intentionally
	opts ...func(*provenance.EmitterParams),
) *harness {
	h := &harness{now: time.Date(2026, 9, 23, 10, 0, 0, 0, time.UTC)}
	p := &provenance.EmitterParams{
		Launch:   launch,
		WriterID: "w1",
		Emit:     func(line string) { h.lines = append(h.lines, line) },
		Probe:    func() *spb.EnvironmentRecord { h.probes++; return env },
		Runtime:  func() (time.Duration, bool) { return h.runtime, h.runtimeOK },
		Now:      func() time.Time { return h.now },
	}
	for _, opt := range opts {
		opt(p)
	}
	h.em = provenance.NewEmitter(p)
	return h
}

func withFlush(d time.Duration) func(*provenance.EmitterParams) {
	return func(p *provenance.EmitterParams) { p.FlushInterval = d }
}

func withMaxLineBytes(n int) func(*provenance.EmitterParams) {
	return func(p *provenance.EmitterParams) { p.MaxLineBytes = n }
}

func withHost(hp provenance.HostPaths) func(*provenance.EmitterParams) {
	return func(p *provenance.EmitterParams) { p.Host = hp }
}

func (h *harness) decoded(t *testing.T) []map[string]any {
	t.Helper()
	var out []map[string]any
	for _, l := range h.lines {
		require.True(t, strings.HasPrefix(l, provenance.LinePrefix), l)
		var m map[string]any
		require.NoError(t, json.Unmarshal([]byte(strings.TrimPrefix(l, provenance.LinePrefix)), &m))
		out = append(out, m)
	}
	return out
}

func kinds(recs []map[string]any) []string {
	var ks []string
	for _, r := range recs {
		ks = append(ks, r["kind"].(string))
	}
	return ks
}

func gpuCol(t *testing.T, rec map[string]any, uuid, name string) []any {
	t.Helper()
	return rec["gpus"].(map[string]any)[uuid].(map[string]any)[name].([]any)
}

var rank17 = provenance.Launch{
	Job:  provenance.Job{Scheduler: "slurm"},
	Rank: provenance.Rank{Global: intPtr(17)},
}

func TestEmitter_FirstSampleEmitsRankThenWindow(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa", "GPU-bbb"), rank17)

	h.em.OnSample(stats("gpu.process.1.gpu", "90", "gpu.1.smClock", "1980", "gpu.1.gpu", "97"), nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	assert.EqualValues(t, 1, recs[0]["v"])
	assert.Equal(t, "w1", recs[0]["writer_id"])
	assert.Equal(t, "2026-09-23T10:00:00Z", recs[0]["collected_at"])
	rank := recs[0]["rank"].(map[string]any)
	assert.Equal(t, "nvml_process", rank["binding_source"])
	assert.EqualValues(t, 17, rank["global"])
	gpu := rank["gpus"].([]any)[0].(map[string]any)
	assert.Equal(t, "GPU-bbb", gpu["uuid"])
	assert.Equal(t, "00000000:11:00.0", gpu["pci_bus_id"])
	assert.EqualValues(t, 1, gpu["index_host"])

	w := recs[1]
	assert.EqualValues(t, 17, w["rank"])
	assert.Equal(t, "2026-09-23T10:00:00Z", w["t0"])
	assert.Equal(t, []any{0.0}, w["ticks"].(map[string]any)["dt_ms"])
	assert.Equal(t, []any{1980.0}, gpuCol(t, w, "GPU-bbb", "sm_clock_mhz"))
	assert.Equal(t, []any{97.0}, gpuCol(t, w, "GPU-bbb", "util_pct"))
	assert.Equal(t, 1, h.probes)
}

func TestEmitter_PacksTicksUntilFlushInterval(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa"), rank17, withFlush(time.Minute))
	s := stats("gpu.process.0.gpu", "90", "gpu.0.smClock", "1980")

	for range 12 {
		h.em.OnSample(s, nil)
		h.now = h.now.Add(5 * time.Second)
	}
	require.Equal(t, []string{"rank"}, kinds(h.decoded(t)))

	h.em.OnSample(s, nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	dt := recs[1]["ticks"].(map[string]any)["dt_ms"].([]any)
	require.Len(t, dt, 13)
	assert.EqualValues(t, 60000, dt[12])
	assert.Len(t, gpuCol(t, recs[1], "GPU-aaa", "sm_clock_mhz"), 13)

	h.now = h.now.Add(5 * time.Second)
	h.em.OnSample(s, nil)
	assert.Len(t, h.lines, 2)
}

func TestEmitter_FlushesEarlyAtLineBudget(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa"), rank17, withFlush(time.Hour), withMaxLineBytes(1000))
	s := stats(
		"gpu.process.0.gpu",
		"90",
		"gpu.0.smClock",
		"1980",
		"gpu.0.gpu",
		"97",
		"gpu.0.powerWatts",
		"612.4",
	)

	for range 100 {
		h.em.OnSample(s, nil)
		h.now = h.now.Add(5 * time.Second)
	}

	ks := kinds(h.decoded(t))
	require.Greater(t, len(ks), 2)
	for i, l := range h.lines[1:] {
		assert.Equal(t, "window", ks[i+1])
		assert.Less(t, len(l), 2000)
	}
}

func TestEmitter_UnchangedBindingNoNewRank(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa"), rank17)
	s := stats("gpu.process.0.gpu", "90", "gpu.0.gpu", "97")

	h.em.OnSample(s, nil)
	h.em.OnSample(s, nil)

	assert.Equal(t, []string{"rank", "window", "window"}, kinds(h.decoded(t)))
	assert.Equal(t, 1, h.probes)
}

func TestEmitter_BindingChangeEmitsNewRank(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa", "GPU-bbb"), rank17)

	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)
	h.em.OnSample(stats("gpu.process.1.gpu", "90"), nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window", "rank", "window"}, kinds(recs))
	assert.Contains(t, recs[3]["gpus"], "GPU-bbb")
	assert.NotContains(t, recs[3]["gpus"], "GPU-aaa")
}

func TestEmitter_ResolvedNeverDowngrades(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa"), rank17)

	h.em.OnSample(stats("gpu.process.0.gpu", "90", "gpu.0.gpu", "97"), nil)
	h.em.OnSample(stats("gpu.0.gpu", "0"), nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window", "window"}, kinds(recs))
	assert.Equal(t, []any{0.0}, gpuCol(t, recs[2], "GPU-aaa", "util_pct"))
}

func TestEmitter_UnresolvedThenResolved(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa"), rank17)

	h.em.OnSample(stats("gpu.0.gpu", "0"), nil)
	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "rank", "window"}, kinds(recs))
	assert.Equal(t, "unresolved", recs[0]["rank"].(map[string]any)["binding_source"])
	assert.Empty(t, recs[0]["rank"].(map[string]any)["gpus"])
}

func TestEmitter_MissingFieldsAndRealZero(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa"), rank17)

	h.em.OnSample(stats("gpu.process.0.gpu", "0", "gpu.0.gpu", "0", "gpu.0.smClock", "1980"), nil)

	w := h.decoded(t)[1]
	assert.Equal(t, []any{0.0}, gpuCol(t, w, "GPU-aaa", "util_pct"))
	assert.NotContains(t, w["gpus"].(map[string]any)["GPU-aaa"], "sm_active")
}

func TestEmitter_GapsRecordedInWindow(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa"), rank17, withFlush(15*time.Second))
	ok := stats("gpu.process.0.gpu", "90", "gpu.0.gpu", "97")

	h.em.OnSample(ok, nil)
	h.now = h.now.Add(5 * time.Second)
	h.em.OnSample(nil, assert.AnError)
	h.now = h.now.Add(5 * time.Second)
	h.em.OnSample(nil, nil)
	h.now = h.now.Add(5 * time.Second)
	h.em.OnSample(ok, nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	assert.Equal(t, []any{1.0, 2.0}, recs[1]["gaps"])
	assert.Equal(t, []any{97.0, nil, nil, 97.0}, gpuCol(t, recs[1], "GPU-aaa", "util_pct"))
}

func TestEmitter_ZeroGPUsEmitsHostOnlyWindow(t *testing.T) {
	h := newHarness(&spb.EnvironmentRecord{}, rank17, withHost(fakeHost(t, "0-3", true)))

	h.em.OnSample(stats("gpu.process.0.gpu", "90", "gpu.0.gpu", "97"), nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	rank := recs[0]["rank"].(map[string]any)
	assert.Equal(t, "no_nvidia_gpu", rank["binding_source"])
	assert.Equal(t, []any{}, rank["gpus"])
	assert.Contains(t, recs[1], "host")
	assert.NotContains(t, recs[1], "gpus")
	assert.Equal(t, 1, h.probes)
}

func TestEmitter_NilProbeIsGPUInfoUnavailable(t *testing.T) {
	h := newHarness(nil, rank17)

	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank"}, kinds(recs))
	assert.Equal(t, "gpu_info_unavailable", recs[0]["rank"].(map[string]any)["binding_source"])
	assert.Equal(t, 1, h.probes)
}

// XPU.Sample returns (nil, nil) on both a start failure and an empty sample; neither is a gap here.
func TestEmitter_ZeroGPUsNoGapsWithHostTree(t *testing.T) {
	h := newHarness(&spb.EnvironmentRecord{}, rank17, withFlush(15*time.Second),
		withHost(fakeHost(t, "0-3", true)))

	h.em.OnSample(nil, nil)
	h.now = h.now.Add(5 * time.Second)
	h.em.OnSample(nil, nil)
	h.now = h.now.Add(5 * time.Second)
	h.em.OnSample(nil, nil)
	h.now = h.now.Add(5 * time.Second)
	h.em.OnSample(nil, nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	assert.Equal(t, "no_nvidia_gpu", recs[0]["rank"].(map[string]any)["binding_source"])
	assert.NotContains(t, recs[1], "gaps")
	assert.Contains(t, recs[1], "host")
	assert.NotContains(t, recs[1], "gpus")
	assert.Equal(t, 1, h.probes)
}

func TestEmitter_ZeroGPUsWithoutHostTreeOnlyRank(t *testing.T) {
	h := newHarness(&spb.EnvironmentRecord{}, rank17, withFlush(15*time.Second))

	h.em.OnSample(nil, nil)
	h.now = h.now.Add(5 * time.Second)
	h.em.OnSample(nil, nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank"}, kinds(recs))
	assert.Equal(t, "no_nvidia_gpu", recs[0]["rank"].(map[string]any)["binding_source"])
	_, ok := h.em.Drain()
	assert.False(t, ok, "a tick with neither GPU nor host values must not buffer a window")
	assert.Equal(t, 1, h.probes)
}

func TestEmitter_DeviceBindingBeforeFirstSample(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa", "GPU-bbb"), rank17)

	h.em.SetDeviceBinding(&spb.DeviceBindingRecord{Uuid: "GPU-bbb", Source: "cuda_runtime"})
	h.em.OnSample(stats("gpu.1.gpu", "90"), nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	assert.Equal(t, "cuda_runtime", recs[0]["rank"].(map[string]any)["binding_source"])
	assert.Equal(t, []any{90.0}, gpuCol(t, recs[1], "GPU-bbb", "util_pct"))
}

func TestEmitter_UnmatchedReportedUUIDHasNoSamples(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa"), rank17)

	h.em.SetDeviceBinding(&spb.DeviceBindingRecord{Uuid: "GPU-zzz"})
	h.em.OnSample(stats("gpu.0.gpu", "90"), nil)

	assert.Equal(t, []string{"rank"}, kinds(h.decoded(t)))
}

func TestEmitter_StepAndRuntime(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa"), rank17, withFlush(10*time.Second))
	s := stats("gpu.process.0.gpu", "90")

	h.em.OnSample(s, nil)
	h.now = h.now.Add(5 * time.Second)
	h.runtime, h.runtimeOK = 12500*time.Millisecond, true
	h.em.SetStep("trainer/global_step", 42)
	h.em.OnSample(s, nil)
	h.now = h.now.Add(5 * time.Second)
	h.em.OnSample(s, nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	assert.NotContains(t, recs[0], "runtime_s")
	assert.NotContains(t, recs[0], "step")
	w := recs[1]
	ticks := w["ticks"].(map[string]any)
	assert.Equal(t, []any{nil, 12.5, 12.5}, ticks["runtime_s"])
	assert.Equal(t, []any{nil, 42.0, 42.0}, ticks["step"])
	assert.EqualValues(t, 12.5, w["runtime_s"])
	assert.EqualValues(t, 42, w["step"])
	assert.Equal(t, "trainer/global_step", w["step_key"])
}

func TestEmitter_SetStepIgnoresNonFinite(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa"), rank17, withFlush(10*time.Second))
	s := stats("gpu.process.0.gpu", "90")

	h.em.SetStep("trainer/global_step", 5)
	h.em.OnSample(s, nil)
	h.em.SetStep("trainer/global_step", math.NaN())
	h.now = h.now.Add(5 * time.Second)
	h.em.OnSample(s, nil)
	h.em.SetStep("trainer/global_step", math.Inf(1))
	h.now = h.now.Add(5 * time.Second)
	h.em.OnSample(s, nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	w := recs[1]
	assert.EqualValues(t, 5, w["step"])
	ticks := w["ticks"].(map[string]any)
	assert.Equal(t, []any{5.0, 5.0, 5.0}, ticks["step"])
}

func TestEmitter_ReportNarrowsAmbiguousBinding(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa", "GPU-bbb"), rank17)
	s := stats("gpu.process.0.gpu", "1", "gpu.process.1.gpu", "90")

	h.em.OnSample(s, nil)
	h.em.SetDeviceBinding(&spb.DeviceBindingRecord{Uuid: "GPU-bbb"})
	h.em.OnSample(s, nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window", "rank", "window"}, kinds(recs))
	assert.Equal(t, true, recs[0]["rank"].(map[string]any)["ambiguous"])
	assert.NotContains(t, recs[2]["rank"].(map[string]any), "ambiguous")
	assert.Equal(
		t,
		[]string{"GPU-bbb"},
		slices.Collect(maps.Keys(recs[3]["gpus"].(map[string]any))),
	)
}

func TestEmitter_SourceFlapNoNewRank(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa", "GPU-bbb"), rank17)
	h.em.SetDeviceBinding(&spb.DeviceBindingRecord{Uuid: "GPU-bbb"})

	h.em.OnSample(stats("gpu.1.gpu", "1"), nil) // no nvml process evidence -> cuda_runtime
	h.em.OnSample(
		stats("gpu.process.1.gpu", "90"),
		nil,
	) // transient nvml process hit -> nvml_process
	h.em.OnSample(stats("gpu.1.gpu", "1"), nil) // nvml miss again -> cuda_runtime

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window", "window", "window"}, kinds(recs))
	assert.Equal(t, "cuda_runtime", recs[0]["rank"].(map[string]any)["binding_source"])
}

func TestEmitter_ConflictEmitsRankWithoutSamples(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa", "GPU-bbb"), rank17)

	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)
	h.em.SetDeviceBinding(&spb.DeviceBindingRecord{Uuid: "GPU-bbb"})
	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)

	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window", "rank"}, kinds(recs))
	assert.Equal(t, "conflict", recs[2]["rank"].(map[string]any)["binding_source"])
}

func TestEmitter_DrainReturnsPartialWindowOnce(t *testing.T) {
	h := newHarness(envRecord("GPU-aaa"), rank17, withFlush(time.Minute))
	s := stats("gpu.process.0.gpu", "90", "gpu.0.gpu", "97")

	h.em.OnSample(s, nil)
	h.now = h.now.Add(5 * time.Second)
	h.em.OnSample(s, nil)
	line, ok := h.em.Drain()

	require.True(t, ok)
	h.lines = append(h.lines, line)
	recs := h.decoded(t)
	require.Equal(t, []string{"rank", "window"}, kinds(recs))
	assert.Len(t, gpuCol(t, recs[1], "GPU-aaa", "util_pct"), 2)
	_, ok = h.em.Drain()
	assert.False(t, ok)
}

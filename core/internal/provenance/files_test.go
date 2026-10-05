package provenance_test

import (
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/provenance"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func gpuTick() *spb.StatsRecord { return stats("gpu.process.0.gpu", "90", "gpu.0.gpu", "97") }

// items renders a FilesRecord as "POLICY path" strings with slash-separated paths.
func items(r *spb.FilesRecord) []string {
	var out []string
	for _, f := range r.GetFiles() {
		out = append(out, f.GetPolicy().String()+" "+filepath.ToSlash(f.GetPath()))
	}
	return out
}

// registeredChunks returns the chunk paths of every queued FilesRecord, in order.
func (h *harness) registeredChunks() []string {
	var out []string
	for _, r := range h.emitted {
		for _, f := range r.GetFiles() {
			if p := filepath.ToSlash(f.GetPath()); strings.Contains(p, "/chunks/") {
				out = append(out, p)
			}
		}
	}
	return out
}

// tickUntilSealed samples every step until n chunks are registered and returns each seal time since the start.
func (h *harness) tickUntilSealed(t *testing.T, n int, step time.Duration) []time.Duration {
	t.Helper()
	start := h.now
	var at []time.Duration
	for len(at) < n {
		require.Less(t, h.now.Sub(start), 3*time.Hour, "chunks never sealed")
		h.em.OnSample(gpuTick(), nil)
		if len(h.registeredChunks()) > len(at) {
			at = append(at, h.now.Sub(start))
		}
		h.now = h.now.Add(step)
	}
	return at
}

func TestEmitter_SealsChunkAtIntervalWithFirstSealJitter(t *testing.T) {
	h := newHarness(t, envRecord("GPU-aaa"), rank17, withChunkInterval(10*time.Minute))

	at := h.tickUntilSealed(t, 2, 15*time.Second)

	assert.InDelta(t, (10 * time.Minute).Seconds(), at[0].Seconds(), 75)
	assert.Equal(t, 10*time.Minute+15*time.Second, at[1]-at[0], "only the first seal is jittered")
}

func TestEmitter_FirstSealJitterIsStablePerWriterAndSpread(t *testing.T) {
	firstSeal := func(id string) time.Duration {
		h := newHarness(t, envRecord("GPU-aaa"), rank17,
			func(p *provenance.EmitterParams) { p.WriterID = id })
		return h.tickUntilSealed(t, 1, 5*time.Second)[0]
	}
	seen := make(map[time.Duration]bool)
	for i := range 20 {
		id := fmt.Sprintf("01a0f836-0000-7000-8000-%012d", i)
		d := firstSeal(id)
		assert.Equal(t, d, firstSeal(id), "jitter must be derived from writer_id")
		assert.GreaterOrEqual(t, d, 18*time.Minute)
		assert.LessOrEqual(t, d, 22*time.Minute+5*time.Second)
		seen[d] = true
	}
	assert.Greater(t, len(seen), 1, "writers starting together must not all seal on one tick")
}

func TestEmitter_SealsChunkAtMaxBytes(t *testing.T) {
	h := newHarness(t, envRecord("GPU-aaa"), rank17, withMaxChunkBytes(2<<10))

	for range 40 {
		h.em.OnSample(gpuTick(), nil)
		h.now = h.now.Add(5 * time.Second)
	}

	chunks := h.registeredChunks()
	require.Greater(t, len(chunks), 2)
	for i, c := range chunks {
		assert.Equal(t,
			fmt.Sprintf("wandb-telemetry/v1/chunks/20260923T1000/w1-%06d.jsonl.gz", i), c)
	}
	assert.Equal(t, chunks, h.sealedChunks(t))
	assert.Len(t, h.windowLines(t), 40, "no window is lost across seals")
}

func TestEmitter_OpenChunkStaysInTmpUntilSealed(t *testing.T) {
	h := newHarness(t, envRecord("GPU-aaa"), rank17, withMaxChunkBytes(2<<10))

	for range 23 {
		h.em.OnSample(gpuTick(), nil)
		h.now = h.now.Add(5 * time.Second)
	}

	require.NotEmpty(t, h.sealedChunks(t))
	var published []string
	require.NoError(t, filepath.WalkDir(h.filesDir, func(p string, d fs.DirEntry, err error) error {
		if err == nil && !d.IsDir() {
			rel, _ := filepath.Rel(h.filesDir, p)
			published = append(published, filepath.ToSlash(rel))
		}
		return err
	}))
	chunkName := regexp.MustCompile(`^wandb-telemetry/v1/chunks/\d{8}T\d{4}/w1-\d{6}\.jsonl\.gz$`)
	for _, p := range published {
		if p != "wandb-telemetry/v1/rank/w1.jsonl" {
			assert.Regexp(t, chunkName, p)
		}
	}
	entries, err := os.ReadDir(h.tmpDir)
	require.NoError(t, err)
	require.LessOrEqual(t, len(entries), 1, "tmp holds at most the open chunk")
	for _, e := range entries {
		assert.Regexp(t, `^w1-\d{6}\.jsonl$`, e.Name())
	}
}

func TestEmitter_DrainSealsOpenChunkBeforeReturning(t *testing.T) {
	h := newHarness(t, envRecord("GPU-aaa"), rank17, withFlush(time.Minute))
	for range 3 {
		h.em.OnSample(gpuTick(), nil)
		h.now = h.now.Add(5 * time.Second)
	}

	got := items(h.em.Drain())

	assert.Equal(t, []string{
		"NOW wandb-telemetry/v1/chunks/20260923T1000/w1-000000.jsonl.gz",
		"END wandb-telemetry/v1/rank/w1.jsonl",
	}, got)
	_, err := os.Stat(filepath.Join(h.filesDir,
		"wandb-telemetry", "v1", "chunks", "20260923T1000", "w1-000000.jsonl.gz"))
	require.NoError(t, err, "the exit chunk must be on disk before Drain returns")
	assert.Len(t, h.windowLines(t), 1)
	assert.Nil(t, h.em.Drain())
}

func TestEmitter_ChunksRegisterNowOnlyAndRankNowThenEnd(t *testing.T) {
	h := newHarness(t, envRecord("GPU-aaa"), rank17, withMaxChunkBytes(2<<10))
	for range 20 {
		h.em.OnSample(gpuTick(), nil)
		h.now = h.now.Add(5 * time.Second)
	}

	counts := make(map[string]int)
	for _, r := range append(h.emitted, h.em.Drain()) {
		for _, it := range items(r) {
			counts[it]++
			if strings.Contains(it, "/chunks/") {
				assert.True(t, strings.HasPrefix(it, "NOW "), it)
			}
		}
	}
	assert.Equal(t, 1, counts["NOW wandb-telemetry/v1/rank/w1.jsonl"])
	assert.Equal(t, 1, counts["END wandb-telemetry/v1/rank/w1.jsonl"])
}

func TestEmitter_RankObjectHoldsFullBindingHistory(t *testing.T) {
	h := newHarness(t, envRecord("GPU-aaa", "GPU-bbb"), rank17)

	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)
	first := h.rankLines(t)
	h.em.OnSample(stats("gpu.process.1.gpu", "90"), nil)
	lines := h.rankLines(t)

	require.Len(t, first, 1)
	require.Len(t, lines, 2)
	assert.Equal(t, first[0], lines[0])
	assert.Contains(t, lines[1], `"uuid":"GPU-bbb"`)
	assert.Equal(t, 1, h.rankNowCount(), "a rewrite within 5 minutes is not registered")
	h.now = h.now.Add(5 * time.Minute)
	h.em.OnSample(stats("gpu.process.1.gpu", "90"), nil)
	assert.Equal(t, 2, h.rankNowCount(), "the pending rewrite is registered once due")
	leftovers, err := filepath.Glob(filepath.Join(h.tmpDir, "rank-*"))
	require.NoError(t, err)
	assert.Empty(t, leftovers, "the rank temp file is renamed into place")
}

// rankNowCount returns how many queued FilesRecords registered the rank object NOW.
func (h *harness) rankNowCount() int {
	n := 0
	for _, r := range h.emitted {
		for _, it := range items(r) {
			if it == "NOW wandb-telemetry/v1/rank/w1.jsonl" {
				n++
			}
		}
	}
	return n
}

func TestEmitter_FlappingBindingRegistersRankAtMostEvery5Minutes(t *testing.T) {
	h := newHarness(t, envRecord("GPU-aaa", "GPU-bbb"), rank17)
	flap := []*spb.StatsRecord{
		stats("gpu.process.0.gpu", "90"),
		stats("gpu.process.0.gpu", "90", "gpu.process.1.gpu", "90"),
	}

	const ticks = 1000
	for i := range ticks {
		h.em.OnSample(flap[i%2], nil)
		h.now = h.now.Add(15 * time.Second)
	}

	// 1000 ticks of 15 s span 250 minutes: the first registration plus one per 5 minutes.
	assert.LessOrEqual(t, h.rankNowCount(), 1+250/5)
	assert.Len(t, h.rankLines(t), 100, "the rank object keeps only the last 100 records")
}

func TestEmitter_DrainRegistersLatestRankAfterDebounce(t *testing.T) {
	h := newHarness(t, envRecord("GPU-aaa", "GPU-bbb"), rank17)

	h.em.OnSample(stats("gpu.process.0.gpu", "90"), nil)
	h.now = h.now.Add(15 * time.Second)
	h.em.OnSample(stats("gpu.process.1.gpu", "90"), nil)
	require.Equal(t, 1, h.rankNowCount())

	assert.Contains(t, items(h.em.Drain()), "END wandb-telemetry/v1/rank/w1.jsonl")
	lines := h.rankLines(t)
	require.Len(t, lines, 2)
	assert.Contains(t, lines[1], `"uuid":"GPU-bbb"`)
	assert.NotContains(t, lines[1], `"uuid":"GPU-aaa"`)
}

func TestEmitter_NoGPUWriterPublishesOnlyRankObject(t *testing.T) {
	h := newHarness(t, &spb.EnvironmentRecord{}, rank17)

	h.em.OnSample(nil, nil)

	lines := h.rankLines(t)
	require.Len(t, lines, 1)
	assert.Contains(t, lines[0], `"binding_source":"no_nvidia_gpu"`)
	assert.Equal(t, []string{"END wandb-telemetry/v1/rank/w1.jsonl"}, items(h.em.Drain()))
	assert.Empty(t, h.sealedChunks(t), "no window means no chunk file")
}

func TestEmitter_DroppedChunkRegistrationIsReturnedByDrain(t *testing.T) {
	h := newHarness(t, envRecord("GPU-aaa"), rank17, withMaxChunkBytes(2<<10))
	h.emitOK = false
	for len(h.sealedChunks(t)) == 0 {
		h.em.OnSample(gpuTick(), nil)
		h.now = h.now.Add(5 * time.Second)
	}
	dropped := h.sealedChunks(t)

	got := items(h.em.Drain())

	for _, c := range dropped {
		assert.Contains(t, got, "NOW "+c)
	}
}

func TestEmitter_DroppedChunkRegistrationIsRetriedOnNextSeal(t *testing.T) {
	h := newHarness(t, envRecord("GPU-aaa"), rank17, withMaxChunkBytes(2<<10))
	h.emitOK = false
	for len(h.sealedChunks(t)) == 0 {
		h.em.OnSample(gpuTick(), nil)
		h.now = h.now.Add(5 * time.Second)
	}
	h.emitOK = true
	for len(h.sealedChunks(t)) < 2 {
		h.em.OnSample(gpuTick(), nil)
		h.now = h.now.Add(5 * time.Second)
	}

	assert.Equal(t, h.sealedChunks(t), h.registeredChunks())
}

func TestEmitter_UnwritableSyncDirStopsWithOneWarning(t *testing.T) {
	blocker := filepath.Join(t.TempDir(), "blocker")
	require.NoError(t, os.WriteFile(blocker, nil, 0o644))
	logger, logs := observabilitytest.NewRecordingTestLogger(t)
	h := newHarness(t, envRecord("GPU-aaa"), rank17, func(p *provenance.EmitterParams) {
		p.TmpDir = filepath.Join(blocker, "provenance")
		p.Logger = logger
	})

	for range 5 {
		h.em.OnSample(gpuTick(), nil)
		h.now = h.now.Add(5 * time.Second)
	}

	assert.Nil(t, h.em.Drain())
	assert.Empty(t, h.emitted)
	var warnings int
	for _, r := range observabilitytest.ExtractLogs(t, logs) {
		if r["msg"] == "provenance: cannot write telemetry files, stopping" {
			warnings++
		}
	}
	assert.Equal(t, 1, warnings)
}

func TestEmitter_ChunkIntervalIsClampedWithWarning(t *testing.T) {
	for _, tc := range []struct{ requested, used time.Duration }{
		{time.Minute, 5 * time.Minute},
		{2 * time.Hour, time.Hour},
	} {
		t.Run(tc.requested.String(), func(t *testing.T) {
			logger, logs := observabilitytest.NewRecordingTestLogger(t)
			h := newHarness(t, envRecord("GPU-aaa"), rank17,
				withChunkInterval(tc.requested),
				func(p *provenance.EmitterParams) { p.Logger = logger })

			at := h.tickUntilSealed(t, 2, 15*time.Second)

			assert.Equal(t, tc.used+15*time.Second, at[1]-at[0])
			var used []string
			for _, r := range observabilitytest.ExtractLogs(t, logs) {
				if r["msg"] == "provenance: chunk interval out of range, clamped" {
					used = append(used, r["used"])
				}
			}
			assert.Equal(t, []string{tc.used.String()}, used)
		})
	}
}

func TestEmitter_ChunkSlotIsSealTimeFlooredTo20MinutesUTC(t *testing.T) {
	for _, tc := range []struct {
		sealAt time.Time
		slot   string
	}{
		{time.Date(2026, 9, 23, 10, 19, 59, 999e6, time.UTC), "20260923T1000"},
		{time.Date(2026, 9, 23, 10, 20, 0, 0, time.UTC), "20260923T1020"},
		{time.Date(2026, 9, 23, 23, 59, 59, 0, time.UTC), "20260923T2340"},
		{time.Date(2026, 9, 24, 0, 0, 0, 0, time.UTC), "20260924T0000"},
		{time.Date(2026, 9, 24, 2, 40, 0, 0, time.FixedZone("UTC+2", 2*3600)), "20260924T0040"},
	} {
		t.Run(tc.slot, func(t *testing.T) {
			h := newHarness(t, envRecord("GPU-aaa"), rank17, withFlush(time.Hour))
			h.now = tc.sealAt
			h.em.OnSample(gpuTick(), nil)

			assert.Equal(t, []string{
				"NOW wandb-telemetry/v1/chunks/" + tc.slot + "/w1-000000.jsonl.gz",
				"END wandb-telemetry/v1/rank/w1.jsonl",
			}, items(h.em.Drain()))
		})
	}
}

func TestEmitter_ClockStepBackKeepsChunkNamesUnique(t *testing.T) {
	h := newHarness(t, envRecord("GPU-aaa"), rank17, withMaxChunkBytes(2<<10))

	for i := range 60 {
		h.em.OnSample(gpuTick(), nil)
		h.now = h.now.Add(5 * time.Second)
		if i == 30 {
			h.now = h.now.Add(-2 * time.Hour)
		}
	}
	h.em.Drain()

	chunks := h.sealedChunks(t)
	require.Greater(t, len(chunks), 2)
	for i, c := range chunks {
		assert.Equal(t, fmt.Sprintf("w1-%06d.jsonl.gz", i), path.Base(c))
	}
	assert.Len(t, h.windowLines(t), 60)
}

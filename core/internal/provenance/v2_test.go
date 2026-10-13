package provenance_test

import (
	"compress/gzip"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestV2Paths(t *testing.T) {
	paths := provenance.Paths{WriterID: "writer-1", Slot: "20261012T1000", Sequence: 7}
	assert.Equal(t, "wandb-telemetry/v2/primary.json", paths.Primary())
	assert.Equal(t, "wandb-telemetry/v2/manifest/writer-1.json", paths.Manifest())
	assert.Equal(t, "wandb-telemetry/v2/rollup/writer-1.json", paths.Rollup())
	assert.Equal(
		t,
		"wandb-telemetry/v2/chunks/20261012T1000/writer-1-000007.jsonl.gz",
		paths.Chunk(),
	)
	for _, name := range []string{"primary", "step"} {
		data, err := os.ReadFile(filepath.Join("testdata", "v2", name+".json"))
		require.NoError(t, err)
		var record map[string]any
		require.NoError(t, json.Unmarshal(data, &record))
		assert.Equal(t, 2.0, record["v"])
	}
}

func TestV2ConflictStopsCollectionAndRetainsFinalFiles(t *testing.T) {
	dir := t.TempDir()
	emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
	emitter.AddRecord(
		provenance.Record{
			Kind: "capability",
			PayloadJSON: []byte(
				`{"collector":"writer","status":"self_disabled","reason":"run_conflict"}`,
			),
			MonotonicNS: 1,
		},
	)
	emitter.AddRecord(
		provenance.Record{Kind: "step", PayloadJSON: []byte(`{"step":2}`), MonotonicNS: 2},
	)
	emitter.OnSample(&spb.StatsRecord{Item: []*spb.StatsItem{{Key: "cpu", ValueJson: "10"}}}, nil)
	require.NotNil(t, emitter.Drain().Files)
	records := chunkRecords(t, dir)
	require.Len(t, records, 1)
	assert.Equal(t, "capability", records[0]["kind"])
}

func TestV2ManifestRetainsObservedJobFrameworkAndCoordinates(t *testing.T) {
	t.Setenv("WANDB_X_PROVENANCE_REDACTION_KEY", strings.Repeat("ab", 32))
	dir := t.TempDir()
	emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
	require.NoError(
		t,
		emitter.Start(
			provenance.StartConfig{
				WriterID:     "writer",
				RunID:        "private-job",
				IdentityJSON: []byte(`{"scheduler":"torchrun","world_size":8}`),
			},
		),
	)
	emitter.AddRecord(
		provenance.Record{
			Kind: "capability",
			PayloadJSON: []byte(
				`{"collector":"torchtitan","status":"available","source":"6b3b7d4"}`,
			),
			MonotonicNS: 1,
		},
	)
	emitter.AddRecord(
		provenance.Record{
			Kind:        "step",
			PayloadJSON: []byte(`{"step":2,"tp":1,"dp_shard":0}`),
			MonotonicNS: 2,
		},
	)
	emitter.Drain()
	data, err := os.ReadFile(filepath.Join(dir, "wandb-telemetry", "v2", "manifest", "writer.json"))
	require.NoError(t, err)
	assert.Contains(t, string(data), `"scheduler":"torchrun"`)
	assert.Contains(t, string(data), `"job_id":"job_`)
	assert.NotContains(t, string(data), "private-job")
	assert.Contains(t, string(data), `"framework":"torchtitan"`)
	assert.Contains(t, string(data), `"framework_revision":"6b3b7d4"`)
	assert.Contains(t, string(data), `"parallel_coordinates":{"dp_shard":0,"tp":1}`)
}

func TestV2StartAndDrain(t *testing.T) {
	dir := t.TempDir()
	emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
	t.Setenv("WANDB_X_PROVENANCE_REDACTION_KEY", strings.Repeat("ab", 32))
	require.NoError(
		t,
		emitter.Start(provenance.StartConfig{WriterID: "writer-a", Rank: 0, Primary: true}),
	)
	emitter.AddRecord(
		provenance.Record{
			Kind:        "step",
			PayloadJSON: []byte(`{"step":4}`),
			MonotonicNS: 7,
			WallTimeNS:  time.Now().UnixNano(),
		},
	)
	result := emitter.Drain()
	require.NotNil(t, result.Files)
	assert.Zero(t, result.Quality.DroppedRecords)
	b, err := os.ReadFile(filepath.Join(dir, "wandb-telemetry", "v2", "primary.json"))
	require.NoError(t, err)
	var pointer map[string]any
	require.NoError(t, json.Unmarshal(b, &pointer))
	assert.Equal(t, "writer-a", pointer["writer_id"])
	paths, err := filepath.Glob(
		filepath.Join(dir, "wandb-telemetry", "v2", "chunks", "*", "*.jsonl.gz"),
	)
	require.NoError(t, err)
	require.Len(t, paths, 1)
	f, err := os.Open(paths[0])
	require.NoError(t, err)
	defer f.Close()
	gz, err := gzip.NewReader(f)
	require.NoError(t, err)
	defer gz.Close()
	chunk, err := io.ReadAll(gz)
	require.NoError(t, err)
	assert.Contains(t, string(chunk), `"step":4`)
	assert.NotContains(t, string(chunk), strings.Repeat("ab", 32))
	assert.Contains(t, string(chunk), `"v":2`)
}

func TestV2RejectsInvalidRecordsAndBoundsQueue(t *testing.T) {
	emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: t.TempDir()})
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer-a"}))
	emitter.AddRecord(provenance.Record{Kind: "step", PayloadJSON: []byte(`[]`), MonotonicNS: 1})
	emitter.AddRecord(provenance.Record{Kind: "unknown", PayloadJSON: []byte(`{}`), MonotonicNS: 2})
	emitter.AddRecord(
		provenance.Record{Kind: "step", PayloadJSON: []byte(`{"step":1}`), MonotonicNS: 4},
	)
	emitter.AddRecord(provenance.Record{Kind: "step", PayloadJSON: []byte(`{}`), MonotonicNS: 3})
	for i := 0; i < 1123; i++ {
		emitter.AddRecord(
			provenance.Record{Kind: "step", PayloadJSON: []byte(`{}`), MonotonicNS: int64(i + 5)},
		)
	}
	result := emitter.Drain()
	assert.Equal(t, int64(3), result.Quality.RejectedRecords)
	assert.Equal(t, int64(100), result.Quality.DroppedRecords)
}

func TestV2NewAttemptPreservesPriorChunks(t *testing.T) {
	dir := t.TempDir()
	for attempt, writer := range []string{"writer-a", "writer-b"} {
		emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
		require.NoError(
			t,
			emitter.Start(
				provenance.StartConfig{WriterID: writer, Attempt: attempt, Primary: true},
			),
		)
		emitter.AddRecord(
			provenance.Record{Kind: "step", PayloadJSON: []byte(`{}`), MonotonicNS: 1},
		)
		emitter.Drain()
	}
	files, err := filepath.Glob(
		filepath.Join(dir, "wandb-telemetry", "v2", "chunks", "*", "*.jsonl.gz"),
	)
	require.NoError(t, err)
	assert.Len(t, files, 2)
	b, err := os.ReadFile(filepath.Join(dir, "wandb-telemetry", "v2", "primary.json"))
	require.NoError(t, err)
	assert.Contains(t, string(b), `"writer_id":"writer-b"`)
}

func TestV2PrimaryKeepsTheLaterStartOfTheSameAttempt(t *testing.T) {
	dir := t.TempDir()
	primary := func() string {
		b, err := os.ReadFile(filepath.Join(dir, "wandb-telemetry", "v2", "primary.json"))
		require.NoError(t, err)
		var pointer map[string]any
		require.NoError(t, json.Unmarshal(b, &pointer))
		return pointer["writer_id"].(string)
	}
	start := time.Date(2026, 10, 12, 10, 0, 0, 0, time.UTC)
	emitters := map[string]*provenance.Emitter{}
	for i, writer := range []string{"first-launch", "relaunch"} {
		at := start.Add(time.Duration(i) * time.Minute)
		emitters[writer] = provenance.NewEmitter(
			&provenance.EmitterParams{FilesDir: dir, Now: func() time.Time { return at }},
		)
		require.NoError(
			t,
			emitters[writer].Start(provenance.StartConfig{WriterID: writer, Primary: true}),
		)
	}
	assert.Equal(t, "relaunch", primary())
	emitters["first-launch"].Drain()
	assert.Equal(t, "relaunch", primary())
	emitters["relaunch"].Drain()
	b, err := os.ReadFile(filepath.Join(dir, "wandb-telemetry", "v2", "primary.json"))
	require.NoError(t, err)
	assert.Contains(t, string(b), `"started_at":"2026-10-12T10:01:00Z"`)
	assert.Contains(t, string(b), `"finalized":true`)
}

func TestV2ManifestAndRollupReportChunkCompressionTime(t *testing.T) {
	dir := t.TempDir()
	emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
	emitter.AddRecord(
		provenance.Record{Kind: "step", PayloadJSON: []byte(`{"step":1}`), MonotonicNS: 1},
	)
	result := emitter.Drain()
	assert.Positive(t, result.Quality.CompressionNS)
	for _, kind := range []string{"manifest", "rollup"} {
		b, err := os.ReadFile(filepath.Join(dir, "wandb-telemetry", "v2", kind, "writer.json"))
		require.NoError(t, err)
		var document struct {
			Quality provenance.Quality `json:"quality"`
		}
		require.NoError(t, json.Unmarshal(b, &document))
		assert.Equal(t, result.Quality.CompressionNS, document.Quality.CompressionNS, kind)
	}
}

func TestV2PublishesOutsideEmitterLock(t *testing.T) {
	var emitter *provenance.Emitter
	done := make(chan struct{})
	emitter = provenance.NewEmitter(
		&provenance.EmitterParams{
			FilesDir: t.TempDir(),
			Work: filesWork(func(*spb.FilesRecord) bool {
				emitter.AddRecord(
					provenance.Record{Kind: "step", PayloadJSON: []byte(`{}`), MonotonicNS: 1},
				)
				return true
			}),
		},
	)
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer-a"}))
	go func() { emitter.OnSample(nil, nil); close(done) }()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("upload registration held emitter lock")
	}
	emitter.Drain()
}

func TestV2PlatformAndBindingAreInManifest(t *testing.T) {
	dir := t.TempDir()
	emitter := provenance.NewEmitter(
		&provenance.EmitterParams{FilesDir: dir, Host: provenance.HostPaths{SysRoot: t.TempDir()}},
	)
	emitter.SetEnvironment(
		&spb.EnvironmentRecord{
			GpuNvidia: []*spb.GpuNvidiaInfo{
				{Uuid: "GPU-private", Name: "H100", Serial: "secret-serial"},
			},
		},
	)
	t.Setenv("WANDB_X_PROVENANCE_REDACTION_KEY", strings.Repeat("ab", 32))
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer-a"}))
	emitter.AddRecord(
		provenance.Record{
			Kind: "binding",
			PayloadJSON: []byte(
				`{"gpu_uuid_hmac":"gpu_uuid_b9ace856f2313cfd555be18d","cuda_index":0,"status":"available"}`,
			),
			MonotonicNS: 1,
		},
	)
	emitter.OnSample(nil, nil)
	emitter.Drain()
	data, err := os.ReadFile(
		filepath.Join(dir, "wandb-telemetry", "v2", "manifest", "writer-a.json"),
	)
	require.NoError(t, err)
	assert.Contains(t, string(data), `"binding"`)
	assert.Contains(t, string(data), `"provider":"local"`)
	assert.NotContains(t, string(data), "GPU-private")
	assert.NotContains(t, string(data), "secret-serial")
	assert.Contains(t, string(data), `"id":"gpu_uuid_b9ace856f2313cfd555be18d"`)
}

func TestV2OnlySamplesProvenBoundGPUAndRevokesPartialBinding(t *testing.T) {
	dir := t.TempDir()
	now := time.Now()
	emitter := provenance.NewEmitter(
		&provenance.EmitterParams{FilesDir: dir, Now: func() time.Time { return now }},
	)
	emitter.SetEnvironment(
		&spb.EnvironmentRecord{GpuNvidia: []*spb.GpuNvidiaInfo{{Uuid: "GPU-a"}, {Uuid: "GPU-b"}}},
	)
	t.Setenv("WANDB_X_PROVENANCE_REDACTION_KEY", strings.Repeat("ab", 32))
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
	emitter.AddRecord(
		provenance.Record{
			Kind: "binding",
			PayloadJSON: []byte(
				`{"gpu_uuid_hmac":"gpu_uuid_3eb65075498508521b048895","status":"available"}`,
			),
			MonotonicNS: 1,
		},
	)
	sample := &spb.StatsRecord{
		Item: []*spb.StatsItem{
			{Key: "gpu.0.gpu", ValueJson: "10"},
			{Key: "gpu.1.gpu", ValueJson: "85"},
		},
	}
	emitter.OnSample(sample, nil)
	emitter.AddRecord(
		provenance.Record{
			Kind:        "binding",
			PayloadJSON: []byte(`{"status":"partial","reason":"unproven_mapping"}`),
			MonotonicNS: 2,
		},
	)
	now = now.Add(15 * time.Second)
	emitter.OnSample(sample, nil)
	emitter.Drain()
	count := 0
	for _, record := range chunkRecords(t, dir) {
		if record["kind"] != "infrastructure" {
			continue
		}
		values := record["values"].(map[string]any)
		require.Len(t, values, 1)
		for key, value := range values {
			assert.Contains(t, key, "gpu.gpu_uuid_")
			assert.Equal(t, 85.0, value)
		}
		count++
	}
	assert.Equal(t, 1, count)
}

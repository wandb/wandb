package provenance_test

import (
	"bufio"
	"compress/gzip"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func stats(kv ...string) *spb.StatsRecord {
	result := &spb.StatsRecord{}
	for i := 0; i < len(kv); i += 2 {
		result.Item = append(result.Item, &spb.StatsItem{Key: kv[i], ValueJson: kv[i+1]})
	}
	return result
}

func chunkRecords(t *testing.T, dir string) []map[string]any {
	t.Helper()
	files, err := filepath.Glob(
		filepath.Join(dir, "wandb-telemetry", "v2", "chunks", "*", "*.jsonl.gz"),
	)
	require.NoError(t, err)
	var records []map[string]any
	for _, name := range files {
		f, err := os.Open(name)
		require.NoError(t, err)
		gz, err := gzip.NewReader(f)
		require.NoError(t, err)
		scanner := bufio.NewScanner(gz)
		scanner.Buffer(make([]byte, 4096), 1<<20)
		for scanner.Scan() {
			var record map[string]any
			require.NoError(t, json.Unmarshal(scanner.Bytes(), &record))
			records = append(records, record)
		}
		require.NoError(t, scanner.Err())
		require.NoError(t, gz.Close())
		require.NoError(t, f.Close())
	}
	return records
}

func TestV2PseudonymousBindingIsUnchangedAndOmittedWithoutKey(t *testing.T) {
	for _, key := range []string{"", "secret", strings.Repeat("AB", 32), strings.Repeat("ab", 32)} {
		t.Setenv("WANDB_X_PROVENANCE_REDACTION_KEY", key)
		dir := t.TempDir()
		emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
		require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer-a"}))
		emitter.AddRecord(
			provenance.Record{
				Kind: "binding",
				PayloadJSON: []byte(
					`{"gpu_uuid_hmac":"gpu_uuid_b9ace856f2313cfd555be18d","cuda_index":0}`,
				),
			},
		)
		emitter.Drain()
		records := chunkRecords(t, dir)
		require.Len(t, records, 1)
		if key != strings.Repeat("ab", 32) {
			assert.NotContains(t, records[0], "gpu_uuid_hmac")
		} else {
			assert.Equal(t, "gpu_uuid_b9ace856f2313cfd555be18d", records[0]["gpu_uuid_hmac"])
		}
		data, err := os.ReadFile(
			filepath.Join(dir, "wandb-telemetry", "v2", "manifest", "writer-a.json"),
		)
		require.NoError(t, err)
		switch key {
		case "":
			assert.Contains(t, string(data), "missing_redaction_key")
		case strings.Repeat("ab", 32):
			assert.NotContains(t, string(data), key)
		default:
			assert.Contains(t, string(data), "invalid_redaction_key")
		}
	}
}

func TestV2RejectsRawAndMalformedPseudonymousBinding(t *testing.T) {
	t.Setenv("WANDB_X_PROVENANCE_REDACTION_KEY", strings.Repeat("ab", 32))
	for _, payload := range []string{
		`{"gpu_uuid":"GPU-private"}`,
		`{"gpu_uuid_hmac":"GPU-private"}`,
		`{"gpu_uuid_hmac":"gpu_uuid_B9ACE856F2313CFD555BE18D"}`,
		`{"gpu_uuid_hmac":"gpu_uuid_b9ace856f2313cfd555be18"}`,
		`{"gpu_uuid_hmac":"gpu_uuid_b9ace856f2313cfd555be18d0"}`,
		`{"gpu_uuid_hmac":"hostname_b9ace856f2313cfd555be18d"}`,
		`{"gpu_uuid_hmac":null}`,
	} {
		dir := t.TempDir()
		emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
		require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
		emitter.AddRecord(provenance.Record{Kind: "binding", PayloadJSON: []byte(payload)})
		assert.EqualValues(t, 1, emitter.Drain().Quality.RejectedRecords)
		assert.Empty(t, chunkRecords(t, dir))
	}
}

func TestV2RejectsPathTraversal(t *testing.T) {
	for _, writer := range []string{"../escape", "nested/writer", "", `writer\escape`} {
		emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: t.TempDir()})
		require.Error(t, emitter.Start(provenance.StartConfig{WriterID: writer}))
	}
}

func TestV2UnknownPayloadFieldIsRejected(t *testing.T) {
	emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: t.TempDir()})
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
	emitter.AddRecord(
		provenance.Record{Kind: "step", PayloadJSON: []byte(`{"arbitrary_environment":"secret"}`)},
	)
	assert.EqualValues(t, 1, emitter.Drain().Quality.RejectedRecords)
}

package provenance_test

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// The fixture is 20 consecutive QA windows per writer, about 12 minutes at 5 s sampling.
func TestChunkGzipRatio_QAWindows(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("testdata", "qa_windows.jsonl"))
	require.NoError(t, err)
	chunks := make(map[string][]byte)
	for line := range bytes.Lines(raw) {
		var h struct {
			Kind     string `json:"kind"`
			WriterID string `json:"writer_id"`
		}
		require.NoError(t, json.Unmarshal(line, &h))
		require.Equal(t, "window", h.Kind)
		chunks[h.WriterID] = append(chunks[h.WriterID], line...)
	}
	require.Len(t, chunks, 4)

	var rawTotal, gzTotal int
	for id, chunk := range chunks {
		var buf bytes.Buffer
		zw := gzip.NewWriter(&buf)
		_, err := zw.Write(chunk)
		require.NoError(t, err)
		require.NoError(t, zw.Close())
		ratio := float64(len(chunk)) / float64(buf.Len())
		t.Logf("writer %s: %d B raw, %d B gzip, %.2fx", id, len(chunk), buf.Len(), ratio)
		assert.GreaterOrEqual(t, ratio, 3.5)
		rawTotal += len(chunk)
		gzTotal += buf.Len()
	}
	t.Logf("all chunks: %d B raw, %d B gzip, %.2fx",
		rawTotal, gzTotal, float64(rawTotal)/float64(gzTotal))
}

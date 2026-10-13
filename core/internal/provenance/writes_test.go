package provenance

import (
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestFileWritesDoNotNeedTheEmitterLock(t *testing.T) {
	dir := t.TempDir()
	e := NewEmitter(&EmitterParams{FilesDir: dir})
	require.NoError(t, e.Start(StartConfig{WriterID: "writer"}))
	e.AddRecord(Record{Kind: "step", PayloadJSON: []byte(`{"step":1}`)})
	e.mu.Lock()
	e.flushQueue(e.now())
	e.seal(e.now())
	writes := e.writes
	e.writes = nil
	done := make(chan []writeResult)
	go func() { done <- e.writeFiles(writes) }()
	var results []writeResult
	select {
	case results = <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("writeFiles waited for the emitter lock")
	}
	e.register(writes, results)
	e.mu.Unlock()
	require.Len(t, results, 1)
	require.NoError(t, results[0].err)
	matches, _ := filepath.Glob(
		filepath.Join(dir, "wandb-telemetry", "v2", "chunks", "*", "writer-000000.jsonl.gz"),
	)
	assert.Len(t, matches, 1)
	assert.Equal(t, spb.FilesItem_NOW, e.pending[writes[0].name])
	e.Drain()
}

func TestFailedChunkWriteIsAGap(t *testing.T) {
	e := NewEmitter(&EmitterParams{FilesDir: t.TempDir()})
	require.NoError(t, e.Start(StartConfig{WriterID: "writer"}))
	e.mu.Lock()
	e.chunk.WriteString("{}\n")
	e.seal(e.now())
	writes := e.writes
	e.writes = nil
	e.mu.Unlock()
	writes[0].name = "../../../../" + string([]byte{0}) + "invalid"
	results := e.writeFiles(writes)
	e.mu.Lock()
	e.register(writes, results)
	gaps := e.quality.Gaps
	e.mu.Unlock()
	assert.Error(t, results[0].err)
	assert.EqualValues(t, 1, gaps)
	e.Drain()
}

package provenance_test

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance"
	"github.com/wandb/wandb/core/internal/runwork"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestV2FilesPublishAtCadenceAndFinish(t *testing.T) {
	now := time.Date(2026, 10, 12, 10, 0, 0, 0, time.UTC)
	var published []*spb.FilesRecord
	emitter := provenance.NewEmitter(
		&provenance.EmitterParams{
			FilesDir: t.TempDir(),
			Now:      func() time.Time { return now },
			Work: filesWork(
				func(files *spb.FilesRecord) bool { published = append(published, files); return true },
			),
		},
	)
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer", Primary: true}))
	emitter.AddRecord(provenance.Record{Kind: "step", PayloadJSON: []byte(`{"step":1}`)})
	emitter.OnSample(nil, nil)
	require.Len(t, published, 1)
	require.Len(t, published[0].Files, 3)
	for _, file := range published[0].Files {
		assert.Equal(t, spb.FilesItem_NOW, file.Policy)
	}
	now = now.Add(300 * time.Second)
	emitter.OnSample(nil, nil)
	require.Len(t, published, 2)
	var chunks int
	for _, file := range published[1].Files {
		if filepath.Ext(file.Path) == ".gz" {
			chunks++
		}
	}
	assert.Equal(t, 1, chunks)
	final := emitter.Drain()
	require.NotNil(t, final.Files)
	for _, file := range final.Files.Files {
		assert.Equal(t, spb.FilesItem_END, file.Policy)
	}
	assert.Nil(t, emitter.Drain().Files)
}

func TestV2MutableDocumentsAreAlwaysComplete(t *testing.T) {
	dir := t.TempDir()
	emitter := provenance.NewEmitter(&provenance.EmitterParams{FilesDir: dir})
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
	path := filepath.Join(dir, "wandb-telemetry", "v2", "rollup", "writer.json")
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 100; i++ {
			b, err := os.ReadFile(path)
			assert.NoError(t, err)
			assert.True(t, json.Valid(b))
		}
	}()
	emitter.Drain()
	wg.Wait()
}

func TestV2FailedUploadRegistrationIsRetried(t *testing.T) {
	calls := 0
	emitter := provenance.NewEmitter(
		&provenance.EmitterParams{
			FilesDir: t.TempDir(),
			Work:     filesWork(func(*spb.FilesRecord) bool { calls++; return calls > 1 }),
		},
	)
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
	emitter.OnSample(nil, nil)
	emitter.OnSample(nil, nil)
	assert.Equal(t, 2, calls)
	emitter.Drain()
}

type filesWork func(*spb.FilesRecord) bool

func (w filesWork) AddWork(work runwork.Work) { w.AddWorkOrCancel(nil, work) }
func (w filesWork) AddWorkOrCancel(_ <-chan struct{}, work runwork.Work) bool {
	return w(work.WorkImpl.(runwork.WorkRecord).Record.GetFiles())
}
func (filesWork) BeforeEndCtx() context.Context { return context.Background() }

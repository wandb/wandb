package provenance_test

import (
	"context"
	"path/filepath"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance"
	"github.com/wandb/wandb/core/internal/runwork"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type exitWork struct {
	mu    sync.Mutex
	exits []int32
}

func (w *exitWork) AddWork(work runwork.Work) { w.AddWorkOrCancel(nil, work) }
func (w *exitWork) AddWorkOrCancel(_ <-chan struct{}, work runwork.Work) bool {
	if exit := work.WorkImpl.(runwork.WorkRecord).Record.GetExit(); exit != nil {
		w.mu.Lock()
		w.exits = append(w.exits, exit.ExitCode)
		w.mu.Unlock()
		work.Request.Respond(&spb.ServerResponse{})
	}
	return true
}
func (*exitWork) BeforeEndCtx() context.Context { return context.Background() }

func TestHandshakeValidatesAndUsesCoreWriterID(t *testing.T) {
	var disabled *provenance.Emitter
	assert.Equal(
		t,
		"protocol_mismatch",
		disabled.Handshake(&spb.ProvenanceStartRequest{ProtocolVersion: 99}).Reason,
	)
	assert.Equal(
		t,
		"disabled",
		disabled.Handshake(&spb.ProvenanceStartRequest{ProtocolVersion: 2}).Reason,
	)
	dir := t.TempDir()
	emitter := provenance.NewEmitter(
		&provenance.EmitterParams{FilesDir: dir, WriterID: "core-writer", Level: 0},
	)
	assert.Equal(
		t,
		"level_mismatch",
		emitter.Handshake(&spb.ProvenanceStartRequest{ProtocolVersion: 2, Level: 1}).Reason,
	)
	response := emitter.Handshake(
		&spb.ProvenanceStartRequest{ProtocolVersion: 2, Rank: 1, Primary: true},
	)
	require.True(t, response.Accepted, response.Reason)
	assert.Equal(t, "core-writer", response.WriterId)
	assert.Equal(
		t,
		"already_started",
		emitter.Handshake(&spb.ProvenanceStartRequest{ProtocolVersion: 2}).Reason,
	)
	emitter.Drain()
	assert.NoFileExists(t, filepath.Join(dir, "wandb-telemetry", "v2", "primary.json"))
}

func TestTerminateSendsNonZeroExitOnlyToStartedEmitters(t *testing.T) {
	provenance.Terminate(time.Second, 143)
	work := &exitWork{}
	emitter := provenance.NewEmitter(
		&provenance.EmitterParams{FilesDir: t.TempDir(), WriterID: "writer", Work: work},
	)
	require.True(t, emitter.Handshake(&spb.ProvenanceStartRequest{ProtocolVersion: 2}).Accepted)
	provenance.Terminate(time.Second, 143)
	emitter.Drain()
	provenance.Terminate(time.Second, 143)
	assert.Equal(t, []int32{143}, work.exits)
}

func TestTerminateIsBoundedWhenStreamDoesNotRespond(t *testing.T) {
	emitter := provenance.NewEmitter(
		&provenance.EmitterParams{
			FilesDir: t.TempDir(),
			WriterID: "writer",
			Work:     filesWork(func(*spb.FilesRecord) bool { return true }),
		},
	)
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
	defer emitter.Drain()
	started := time.Now()
	provenance.Terminate(50*time.Millisecond, 143)
	assert.Less(t, time.Since(started), time.Second)
}

func TestBackgroundLoopFlushesWithoutSamples(t *testing.T) {
	var now atomic.Int64
	now.Store(time.Date(2026, 10, 12, 10, 0, 0, 0, time.UTC).UnixNano())
	var chunks atomic.Int32
	emitter := provenance.NewEmitter(&provenance.EmitterParams{
		FilesDir: t.TempDir(),
		Tick:     5 * time.Millisecond,
		Now:      func() time.Time { return time.Unix(0, now.Load()) },
		Work: filesWork(func(files *spb.FilesRecord) bool {
			for _, file := range files.Files {
				if filepath.Ext(file.Path) == ".gz" {
					chunks.Add(1)
				}
			}
			return true
		}),
	})
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
	emitter.AddRecord(
		provenance.Record{Kind: "step", PayloadJSON: []byte(`{"step":1}`), MonotonicNS: 1},
	)
	now.Add(int64(301 * time.Second))
	assert.Eventually(
		t,
		func() bool { return chunks.Load() == 1 },
		5*time.Second,
		5*time.Millisecond,
	)
	emitter.Drain()
}

func TestDrainRegistersFilesFromInFlightLoopFlush(t *testing.T) {
	var now atomic.Int64
	now.Store(time.Date(2026, 10, 12, 10, 0, 0, 0, time.UTC).UnixNano())
	entered, release := make(chan bool), make(chan bool)
	emitter := provenance.NewEmitter(&provenance.EmitterParams{
		FilesDir: t.TempDir(),
		Tick:     5 * time.Millisecond,
		Now:      func() time.Time { return time.Unix(0, now.Load()) },
		Work: filesWork(func(files *spb.FilesRecord) bool {
			for _, file := range files.Files {
				if filepath.Ext(file.Path) == ".gz" {
					entered <- true
					return <-release
				}
			}
			return true
		}),
	})
	require.NoError(t, emitter.Start(provenance.StartConfig{WriterID: "writer"}))
	emitter.AddRecord(
		provenance.Record{Kind: "step", PayloadJSON: []byte(`{"step":1}`), MonotonicNS: 1},
	)
	now.Add(int64(301 * time.Second))
	<-entered
	emitter.AddRecord(
		provenance.Record{Kind: "step", PayloadJSON: []byte(`{"step":2}`), MonotonicNS: 2},
	)
	drained := make(chan provenance.DrainResult)
	go func() { drained <- emitter.Drain() }()
	time.Sleep(20 * time.Millisecond)
	release <- false
	result := <-drained
	require.NotNil(t, result.Files)
	var chunks []string
	for _, file := range result.Files.Files {
		if filepath.Ext(file.Path) == ".gz" {
			chunks = append(chunks, file.Path)
		}
	}
	assert.Len(t, chunks, 2)
}

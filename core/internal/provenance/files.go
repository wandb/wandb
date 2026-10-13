package provenance

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type Paths struct {
	WriterID string
	Slot     string
	Sequence int
}

func (p Paths) Primary() string  { return "wandb-telemetry/v2/primary.json" }
func (p Paths) Manifest() string { return "wandb-telemetry/v2/manifest/" + p.WriterID + ".json" }
func (p Paths) Rollup() string   { return "wandb-telemetry/v2/rollup/" + p.WriterID + ".json" }
func (p Paths) Chunk() string {
	return fmt.Sprintf(
		"wandb-telemetry/v2/chunks/%s/%s-%06d.jsonl.gz",
		p.Slot,
		p.WriterID,
		p.Sequence,
	)
}

func atomicWrite(root, name string, data []byte) error {
	destination := filepath.Join(root, filepath.FromSlash(name))
	if err := os.MkdirAll(filepath.Dir(destination), 0o700); err != nil {
		return err
	}
	temp, err := os.CreateTemp(filepath.Dir(destination), ".telemetry-*")
	if err != nil {
		return err
	}
	defer os.Remove(temp.Name())
	if _, err = temp.Write(data); err != nil {
		temp.Close()
		return err
	}
	if err = temp.Sync(); err != nil {
		temp.Close()
		return err
	}
	if closeErr := temp.Close(); closeErr != nil {
		return closeErr
	}
	return os.Rename(temp.Name(), destination)
}

// pendingWrite is a file queued under mu and written outside it.
type pendingWrite struct {
	name   string
	data   []byte
	policy spb.FilesItem_PolicyType
	gzip   bool
	// primary skips the write when the file names a newer attempt or a later start of the same attempt.
	primary *Primary
}

var errSkipped = errors.New("newer writer owns the file")

func (e *Emitter) writeDocument(name string, value any, policy spb.FilesItem_PolicyType) error {
	data, err := json.Marshal(value)
	if err != nil {
		return err
	}
	e.writes = append(e.writes, pendingWrite{name: name, data: data, policy: policy})
	return nil
}

func (e *Emitter) seal(now time.Time) {
	if e.chunk.Len() == 0 {
		return
	}
	paths := Paths{
		WriterID: e.config.WriterID,
		Slot:     e.chunkStarted.UTC().Truncate(20 * time.Minute).Format("20060102T1504"),
		Sequence: e.sequence,
	}
	e.writes = append(
		e.writes,
		pendingWrite{
			name:   paths.Chunk(),
			data:   e.chunk.Bytes(),
			policy: spb.FilesItem_NOW,
			gzip:   true,
		},
	)
	e.sequence++
	e.chunk = bytes.Buffer{}
	e.chunkStarted = now
}

type writeResult struct {
	err         error
	compression time.Duration
}

// writeFiles performs queued writes in order without holding mu.
func (e *Emitter) writeFiles(writes []pendingWrite) []writeResult {
	results := make([]writeResult, len(writes))
	for i, write := range writes {
		data := write.data
		if write.primary != nil {
			var current Primary
			if existing, err := os.ReadFile(
				filepath.Join(e.filesDir, filepath.FromSlash(write.name)),
			); err == nil &&
				json.Unmarshal(existing, &current) == nil &&
				(current.Attempt > write.primary.Attempt || current.Attempt == write.primary.Attempt && current.WriterID != write.primary.WriterID && current.StartedAt.After(write.primary.StartedAt)) {
				results[i].err = errSkipped
				continue
			}
		}
		if write.gzip {
			started := time.Now()
			var buffer bytes.Buffer
			writer := gzip.NewWriter(&buffer)
			_, err := writer.Write(data)
			if err == nil {
				err = writer.Close()
			}
			if err != nil {
				results[i].err = err
				continue
			}
			data = buffer.Bytes()
			results[i].compression = time.Since(started)
		}
		results[i].err = atomicWrite(e.filesDir, write.name, data)
	}
	return results
}

// writeQueued performs the queued writes outside mu and registers them; call with mu held.
func (e *Emitter) writeQueued() {
	writes := e.writes
	e.writes = nil
	e.mu.Unlock()
	results := e.writeFiles(writes)
	e.mu.Lock()
	e.register(writes, results)
}

// register records completed writes for upload; call with mu held.
func (e *Emitter) register(writes []pendingWrite, results []writeResult) {
	for i, write := range writes {
		result := results[i]
		switch {
		case errors.Is(result.err, errSkipped):
		case result.err != nil:
			e.quality.Gaps++
		default:
			if write.gzip {
				e.quality.CompressionNS += result.compression.Nanoseconds()
			} else {
				e.quality.SerializedBytes += int64(len(write.data))
			}
			e.pending[write.name] = write.policy
		}
	}
}

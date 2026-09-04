package runreader

import (
	"errors"
	"io"
	"os"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	// blockSize is the transaction log's block size, as in core/pkg/leveldb.
	blockSize = 32 * 1024

	// probeHeadRecords bounds how far Probe reads for run records, which the
	// SDK writes first and again when the run's name, tags or notes change.
	probeHeadRecords = 64

	// probeTailBlocks bounds how many blocks back from the end Probe looks
	// for the exit record, which the SDK writes last, and for run records
	// written late.
	probeTailBlocks = 4
)

// ProbeResult is what Probe learned about a run.
type ProbeResult struct {
	Info  Info
	State State
}

// Probe returns a run's identity and state without reading the whole log:
// the identity comes from the run records among the first records and the
// last blocks, and the state from the last blocks of the file. It is cheap
// enough to call for every run in a directory.
func Probe(path string, logger *observability.CoreLogger) (ProbeResult, error) {
	stat, err := os.Stat(path)
	if err != nil {
		return ProbeResult{}, err
	}
	cursor, err := OpenCursor(path, logger)
	if err != nil {
		return ProbeResult{}, err
	}
	defer cursor.Close()

	var info Info
	var infoSeen bool
	var exit *spb.RunExitRecord
	readAll := stat.Size() <= (probeTailBlocks+1)*blockSize
	for i := 0; readAll || i < probeHeadRecords; i++ {
		record, err := cursor.Next()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return ProbeResult{}, err
		}
		if run := record.GetRun(); run != nil {
			info, infoSeen = infoFromRecord(run), true
		}
		if e := record.GetExit(); e != nil {
			exit = e
		}
	}
	if !readAll {
		run, tailExit, err := readTail(cursor, stat.Size())
		if err != nil {
			return ProbeResult{}, err
		}
		if run != nil {
			info, infoSeen = infoFromRecord(run), true
		}
		if tailExit != nil {
			exit = tailExit
		}
	}

	return ProbeResult{
		Info:  info,
		State: deriveState(exit, infoSeen, stat.ModTime(), time.Now()),
	}, nil
}

// readTail returns the last run and exit records in the last blocks of the
// file.
func readTail(cursor *Cursor, size int64) (*spb.RunRecord, *spb.RunExitRecord, error) {
	last := (size - 1) / blockSize * blockSize
	if err := cursor.SeekRecord(last - (probeTailBlocks-1)*blockSize); err != nil {
		return nil, nil, err
	}
	var run *spb.RunRecord
	var exit *spb.RunExitRecord
	for {
		record, err := cursor.Next()
		if errors.Is(err, io.EOF) {
			return run, exit, nil
		}
		if err != nil {
			return nil, nil, err
		}
		if r := record.GetRun(); r != nil {
			run = r
		}
		if e := record.GetExit(); e != nil {
			exit = e
		}
	}
}

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

	// probeHeadRecords bounds how far Probe reads from the start for the run
	// record, which the SDK writes first.
	probeHeadRecords = 64
)

// ProbeResult is what Probe learned about a run.
type ProbeResult struct {
	Info  Info
	State State
}

// Probe returns a run's identity and state from the first records of its
// log and the last complete ones, without reading what lies between, so it
// costs the same for a run of any size. A name, tags or notes change in the
// middle of a run is only seen by reading the run in full.
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

	var p probe
	_, atEnd, err := p.read(cursor, probeHeadRecords)
	if err != nil {
		return ProbeResult{}, err
	}
	headEnd := cursor.Offset()

	// Seek back one block at a time until a block yields a complete record:
	// a record larger than a block ends in a later block than it starts in.
	// The reader skips the chunks of a record that began before the seek.
	for start := (stat.Size() - 1) / blockSize * blockSize; !atEnd; start -= blockSize {
		start = max(start, headEnd)
		if err := cursor.SeekRecord(start); err != nil {
			return ProbeResult{}, err
		}
		n, _, err := p.read(cursor, 0)
		if err != nil {
			return ProbeResult{}, err
		}
		if n > 0 || start == headEnd {
			break
		}
	}

	return ProbeResult{
		Info:  p.info,
		State: deriveState(p.exit, p.infoSeen, stat.ModTime(), time.Now()),
	}, nil
}

type probe struct {
	info     Info
	infoSeen bool
	exit     *spb.RunExitRecord
}

// read applies up to limit records, or all remaining ones when limit is 0,
// returning how many it read and whether it reached the end of the file.
func (p *probe) read(cursor *Cursor, limit int) (int, bool, error) {
	n := 0
	for limit == 0 || n < limit {
		record, _, err := cursor.Next()
		if errors.Is(err, io.EOF) {
			return n, true, nil
		}
		if err != nil {
			return n, false, err
		}
		n++
		if run := record.GetRun(); run != nil {
			p.info, p.infoSeen = infoFromRecord(run), true
		}
		if exit := record.GetExit(); exit != nil {
			p.exit = exit
		}
	}
	return n, false, nil
}

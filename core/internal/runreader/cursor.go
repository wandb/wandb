package runreader

import (
	"errors"
	"io"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Cursor reads records from a transaction log that may still be written to.
type Cursor struct {
	reader *transactionlog.Reader
}

func OpenCursor(path string, logger *observability.CoreLogger) (*Cursor, error) {
	reader, err := transactionlog.OpenReader(path, logger)
	if err != nil {
		return nil, err
	}
	return &Cursor{reader: reader}, nil
}

// Next returns the next record, skipping corrupt data.
//
// The error wraps io.EOF when no more data is available yet, including when
// the last record is only partially written; the position is then unchanged
// so Next can be retried after the file grows. Any other error is terminal:
// the file is not a transaction log this version can read.
func (c *Cursor) Next() (*spb.Record, error) {
	for {
		before := c.reader.NextRecordOffset()
		record, err := c.reader.Read()
		switch {
		case err == nil:
			return record, nil
		case errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF):
			return nil, errors.Join(io.EOF, c.reader.ResetLastRead())
		case c.reader.NextRecordOffset() <= before:
			return nil, err
		}
	}
}

// SeekRecord positions the cursor at a record offset, as returned by a
// writer's LastRecordOffset or the start of any 32 KiB block after the first,
// which holds the file header.
func (c *Cursor) SeekRecord(offset int64) error {
	return c.reader.SeekRecord(offset)
}

func (c *Cursor) Close() {
	c.reader.Close()
}

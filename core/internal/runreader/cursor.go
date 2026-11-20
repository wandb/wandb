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

// Next returns the next record and its offset, skipping corrupt data.
//
// The error wraps io.EOF when no more data is available yet, including when
// the last record is only partially written; the position is then unchanged
// so Next can be retried after the file grows. Any other error is terminal:
// the file is not a transaction log this version can read.
func (c *Cursor) Next() (*spb.Record, int64, error) {
	for {
		before := c.reader.NextRecordOffset()
		record, err := c.reader.Read()
		switch {
		case err == nil:
			return record, before, nil
		case errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF):
			return nil, 0, errors.Join(io.EOF, c.reader.ResetLastRead())
		case c.reader.NextRecordOffset() <= before:
			return nil, 0, err
		}
	}
}

// Offset returns the offset of the next record to read.
func (c *Cursor) Offset() int64 {
	return c.reader.NextRecordOffset()
}

// SeekRecord moves the cursor to a record's offset, as returned by Next or
// Offset.
func (c *Cursor) SeekRecord(offset int64) error {
	return c.reader.SeekRecord(offset)
}

func (c *Cursor) Close() {
	c.reader.Close()
}

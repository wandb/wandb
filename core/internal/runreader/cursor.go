package runreader

import (
	"errors"
	"io"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ErrClosed is returned by a Cursor's methods after Close.
var ErrClosed = errors.New("runreader: cursor is closed")

// Cursor reads records from a transaction log that may still be written to.
//
// It may be closed from another goroutine while a read is in progress, which
// is how LEET stops a scan when the user leaves a view.
type Cursor struct {
	mu      sync.Mutex
	reader  *transactionlog.Reader // nil once closed
	skipped int
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
	var record *spb.Record
	offset, err := c.next(func() (err error) {
		record, err = c.reader.Read()
		return err
	})
	return record, offset, err
}

// NextRaw appends the next record's serialized bytes to dst and returns the
// result with the record's offset. Errors are as for Next.
func (c *Cursor) NextRaw(dst []byte) ([]byte, int64, error) {
	offset, err := c.next(func() (err error) {
		dst, err = c.reader.ReadRaw(dst)
		return err
	})
	if err != nil {
		return nil, 0, err
	}
	return dst, offset, nil
}

// next runs read at the cursor, skipping corrupt data, and returns the
// offset the record was read from.
func (c *Cursor) next(read func() error) (int64, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.reader == nil {
		return 0, ErrClosed
	}
	for {
		before := c.reader.NextRecordOffset()
		err := read()
		switch {
		case err == nil:
			return before, nil
		case errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF):
			return 0, errors.Join(io.EOF, c.reader.ResetLastRead())
		case c.reader.NextRecordOffset() <= before:
			return 0, err
		}
		c.skipped++
	}
}

// Skipped returns how many corrupt regions Next has skipped so far.
func (c *Cursor) Skipped() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.skipped
}

// Offset returns the offset of the next record to read, or 0 once closed.
func (c *Cursor) Offset() int64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.reader == nil {
		return 0
	}
	return c.reader.NextRecordOffset()
}

// SeekRecord moves the cursor to a record's offset, as returned by Next or
// Offset.
func (c *Cursor) SeekRecord(offset int64) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.reader == nil {
		return ErrClosed
	}
	return c.reader.SeekRecord(offset)
}

// Close releases the file. Later calls return ErrClosed.
func (c *Cursor) Close() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.reader != nil {
		c.reader.Close()
		c.reader = nil
	}
}

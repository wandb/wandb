package transactionlog

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
)

// Reader reads from a .wandb file.
//
// Not safe for use in multiple goroutines.
type Reader struct {
	reader *leveldb.Reader // nil when closed
	source io.ReadCloser
	logger *observability.CoreLogger

	// bufPool is a pool containing at most one byte buffer used as the Record
	// buffer in a previous Read() operation.
	//
	// This assumes that a large record is likely to be followed by another
	// large record, so reusing a single large allocation reduces GC pressure
	// and is probably not wasteful.
	//
	// This is a pool to allow the slice to be GC'ed every once in a while,
	// in particular when reading pauses for some time. This is useful for
	// flow control, LEET and live-mode syncing. The pool is per-Reader
	// because different transaction logs may have different record sizes.
	bufPool sync.Pool

	// lastReadOffset is the offset the last Read started at, used for retrying
	// that Read from the same position.
	lastReadOffset int64

	// headerValid is whether the W&B header has been verified.
	headerValid bool
}

// OpenReader opens a .wandb file for reading.
//
// Wraps errors from the os.Open() call so that they can be checked with
// errors.Is().
func OpenReader(
	path string,
	logger *observability.CoreLogger,
) (*Reader, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("transactionlog: error opening file %w", err)
	}

	reader, err := NewReader(f, logger)

	if err != nil {
		_ = f.Close()
		return nil, err
	} else {
		return reader, nil
	}
}

// NewReader starts reading a .wandb file from the given source.
//
// On success, takes ownership of the source (it should not be used except
// through the returned Reader).
func NewReader(
	source io.ReadCloser,
	logger *observability.CoreLogger,
) (*Reader, error) {
	reader := leveldb.NewReaderExt(source, leveldb.CRCAlgoIEEE)

	return &Reader{
		reader:  reader,
		source:  source,
		logger:  logger,
		bufPool: sync.Pool{New: func() any { return new(bytes.Buffer) }},
	}, nil
}

// SeekRecord seeks the underlying file to a specific offset.
//
// The offset should have come from a writer's LastRecordOffset().
func (r *Reader) SeekRecord(offset int64) error {
	return r.reader.SeekRecord(offset)
}

// Read returns the next record from the transaction log.
//
// Returns nil and an error on failure.
// On EOF, the error wraps io.EOF.
//
// Errors are not fatal, and calling Read again will attempt to skip
// corrupt data. ResetLastRead can be used to attempt to read the same
// position in the transaction log again. The error wraps EOF
// or ErrUnexpectedEOF if it may be resolved by waiting for more data.
func (r *Reader) Read() (*spb.Record, error) {
	if r.reader == nil {
		return nil, errors.New("transactionlog: reader is closed")
	}

	// Always recover after errors, skipping corrupt data.
	// No-op if there is no error.
	defer r.reader.Recover()

	r.lastReadOffset = r.reader.NextOffset()

	// Verify the W&B header before the first read.
	if err := r.verifyWBHeaderBeforeFirstRead(); err != nil {
		return nil, err
	}

	recordReader, err := r.reader.Next()

	if err != nil {
		return nil, fmt.Errorf(
			"transactionlog: error getting next record: %w", err)
	}

	buf := r.bufPool.Get().(*bytes.Buffer)
	defer func() {
		buf.Reset()
		r.bufPool.Put(buf)
	}()

	_, err = io.Copy(buf, recordReader)
	if err != nil {
		return nil, fmt.Errorf("transactionlog: error reading: %w", err)
	}

	msg := &spb.Record{}
	if err = proto.Unmarshal(buf.Bytes(), msg); err != nil {
		return nil, fmt.Errorf("transactionlog: error unmarshaling: %v", err)
	}

	return msg, nil
}

// verifyWBHeaderBeforeFirstRead verifies the W&B header if it hasn't yet been
// verified.
func (r *Reader) verifyWBHeaderBeforeFirstRead() error {
	if r.headerValid {
		return nil
	}

	if err := r.reader.VerifyWandbHeader(wandbStoreVersion); err != nil {
		return fmt.Errorf("transactionlog: bad header: %w", err)
	}

	r.headerValid = true
	return nil
}

// ResetLastRead returns to the previous Read position to allow retrying
// the same read after an error.
func (r *Reader) ResetLastRead() error {
	r.logger.Debug("transactionlog: resetting to offset", "offset", r.lastReadOffset)
	return r.SeekRecord(r.lastReadOffset)
}

// Close closes the file.
//
// The reader may not be used after.
func (r *Reader) Close() {
	err := r.source.Close()

	// Since we only use the file for reading, we do not care about
	// errors when closing, but they could indicate other issues with
	// the user's system.
	if err != nil {
		r.logger.Warn(
			fmt.Sprintf("transactionlog: error closing reader: %v", err))
	}

	r.reader = nil
}

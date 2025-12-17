package transactionlog

import (
	"errors"
	"fmt"
	"io"
	"os"

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
	source io.ReadSeeker
	logger *observability.CoreLogger

	// lastReadOffset is the offset the last Read started at, used for retrying
	// that Read from the same position.
	lastReadOffset int64
}

// OpenReader opens a .wandb file for reading.
//
// Wraps errors from the os.Open() call so that they can be checked with
// errors.Is().
//
// The `live` argument is the same as for NewReader.
func OpenReader(
	path string,
	logger *observability.CoreLogger,
	live bool,
) (*Reader, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("transactionlog: error opening file %w", err)
	}

	reader, err := NewReader(f, logger, live)

	if err != nil {
		_ = f.Close()
		return nil, err
	} else {
		return reader, nil
	}
}

// NewReader starts reading a .wandb file from the given source.
//
// The source's seek position must be 0.
//
// The `live` argument hints at whether ResetLastRead will be used
// to retry read errors in a W&B file that's being actively written.
// It increases memory usage by buffering each record but allows
// ResetLastRead to avoid IO.
//
// On success, takes ownership of the source (it should not be used except
// through the returned Reader).
func NewReader(
	source io.ReadSeeker,
	logger *observability.CoreLogger,
	live bool,
) (*Reader, error) {
	if live {
		// Add buffering to avoid IO for ResetLastRead().
		source = NewBufferedReadSeeker(source, 0)
	}

	reader := leveldb.NewReaderExt(source, leveldb.CRCAlgoIEEE)

	err := reader.VerifyWandbHeader(wandbStoreVersion)
	if err != nil {
		return nil, fmt.Errorf("transactionlog: bad header: %v", err)
	}

	return &Reader{reader: reader, source: source, logger: logger}, nil
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
// position in the transaction log again.
func (r *Reader) Read() (*spb.Record, error) {
	if r.reader == nil {
		return nil, errors.New("transactionlog: reader is closed")
	}

	// Always recover after errors, skipping corrupt data.
	// No-op if there is no error.
	defer r.reader.Recover()

	recordReader, recordOffset, err := r.reader.NextWithOffset()
	r.lastReadOffset = recordOffset

	// Set the cutoff to the block position, since seeking to the record
	// will require seeking to the start of its block.
	if bufferedSource, ok := r.source.(*BufferedReadSeeker); ok {
		blockOffset, _ := leveldb.BlockOffset(recordOffset)
		bufferedSource.SetSeekCutoff(blockOffset)
	}

	switch {
	case errors.Is(err, io.EOF):
		return nil, err
	case err != nil:
		return nil, fmt.Errorf(
			"transactionlog: error getting next record: %v", err)
	}

	buf, err := io.ReadAll(recordReader)
	if err != nil {
		return nil, fmt.Errorf("transactionlog: error reading: %v", err)
	}

	msg := &spb.Record{}
	if err = proto.Unmarshal(buf, msg); err != nil {
		return nil, fmt.Errorf("transactionlog: error unmarshaling: %v", err)
	}

	return msg, nil
}

// ResetLastRead returns to the previous Read position to allow retrying
// the same read after an error.
func (r *Reader) ResetLastRead() error {
	r.logger.Info("transactionlog: resetting to offset", "offset", r.lastReadOffset)
	return r.SeekRecord(r.lastReadOffset)
}

// Close closes the file.
//
// The reader may not be used after.
func (r *Reader) Close() {
	if r.reader == nil || r.source == nil {
		r.logger.CaptureError(errors.New("transactionlog: already closed"))
		return
	}

	closer, ok := r.source.(io.Closer)
	r.reader = nil
	r.source = nil // allow any buffer to be garbage collected

	if !ok {
		return
	}

	// Since we only use the file for reading, we do not care about
	// errors when closing, but they could indicate other issues with
	// the user's system.
	if err := closer.Close(); err != nil {
		r.logger.Warn(
			fmt.Sprintf("transactionlog: error closing reader: %v", err))
	}
}

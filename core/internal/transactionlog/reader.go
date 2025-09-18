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
	source io.ReadCloser
	logger *observability.CoreLogger
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

	err := reader.VerifyWandbHeader(wandbStoreVersion)
	if err != nil {
		return nil, fmt.Errorf("transactionlog: bad header: %v", err)
	}

	return &Reader{reader: reader, source: source}, nil
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
// corrupt data.
func (r *Reader) Read() (*spb.Record, error) {
	if r.reader == nil {
		return nil, errors.New("transactionlog: reader is closed")
	}

	// Always recover after errors, skipping corrupt data.
	// No-op if there is no error.
	defer r.reader.Recover()

	recordReader, err := r.reader.Next()

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

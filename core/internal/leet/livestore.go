package leet

import (
	"errors"
	"fmt"
	"io"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// errLiveStoreClosed is returned by reads on a closed LiveStore.
var errLiveStoreClosed = errors.New("livestore: reader is closed")

// LiveStore is the persistent store for a stream that may be actively
// written to by another process.
type LiveStore struct {
	mu sync.Mutex

	reader *transactionlog.Reader
	logger *observability.CoreLogger
}

func NewLiveStore(
	filename string,
	logger *observability.CoreLogger,
) (*LiveStore, error) {
	reader, err := transactionlog.OpenReader(filename, logger)
	if err != nil {
		return nil, fmt.Errorf("livestore: failed opening reader: %w", err)
	}

	return &LiveStore{reader: reader, logger: logger}, nil
}

// Reads the next record from the database.
func (ls *LiveStore) Read() (*spb.Record, error) {
	ls.mu.Lock()
	defer ls.mu.Unlock()

	if ls.reader == nil {
		return nil, errLiveStoreClosed
	}

	record, err := ls.reader.Read()

	if err != nil {
		// We treat unexpected EOFs the same as regular EOFs for live reading.
		if errors.Is(err, io.ErrUnexpectedEOF) {
			err = io.EOF
		}

		resetErr := ls.reader.ResetLastRead()
		return nil, errors.Join(err, resetErr)
	}

	return record, nil
}

// ReadWithOffset reads the next record and returns it together with its
// byte offset in the file, a valid input to ReadAt.
//
// On EOF (including an unexpected EOF from a partially written record) the
// read position is rewound so a future call retries once more data has
// been written, and the error wraps io.EOF. Any other error means corrupt
// data was skipped: the caller may keep reading from the next good block.
func (ls *LiveStore) ReadWithOffset() (*spb.Record, int64, error) {
	ls.mu.Lock()
	defer ls.mu.Unlock()

	if ls.reader == nil {
		return nil, 0, errLiveStoreClosed
	}

	offset := ls.reader.NextRecordOffset()

	record, err := ls.reader.Read()
	if err != nil {
		if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) {
			resetErr := ls.reader.ResetLastRead()
			return nil, 0, errors.Join(io.EOF, resetErr)
		}
		return nil, 0, err
	}

	return record, offset, nil
}

// ReadAt reads the record at the given offset, previously obtained from
// ReadWithOffset.
//
// It moves the read position, so use a dedicated LiveStore for random
// access rather than sharing one with sequential readers.
func (ls *LiveStore) ReadAt(offset int64) (*spb.Record, error) {
	ls.mu.Lock()
	defer ls.mu.Unlock()

	if ls.reader == nil {
		return nil, errLiveStoreClosed
	}

	if err := ls.reader.SeekRecord(offset); err != nil {
		return nil, err
	}
	return ls.reader.Read()
}

// Close closes the database.
func (ls *LiveStore) Close() {
	ls.mu.Lock()
	defer ls.mu.Unlock()

	if ls.reader == nil {
		return
	}

	ls.reader.Close()
	ls.reader = nil
}

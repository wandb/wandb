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
		return nil, fmt.Errorf("livestore: reader is closed")
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

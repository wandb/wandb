package leet

import (
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
)

const wandbStoreVersion = 0

// LiveStore is the persistent store for a stream that may be actively
// written to by another process.
type LiveStore struct {
	// db is the underlying database.
	db *os.File
	// reader is a LiveReader that reads records from a W&B LevelDB-style log
	// that may be actively written.
	reader *leveldb.LiveReader

	logger *observability.CoreLogger
}

func NewLiveStore(
	filename string,
	logger *observability.CoreLogger,
) (*LiveStore, error) {
	f, err := os.Open(filename)
	if err != nil {
		return nil, fmt.Errorf("livestore: failed opening file: %w", err)
	}
	reader := leveldb.NewLiveReader(f, leveldb.CRCAlgoIEEE)

	// Validate W&B header once; it's OK if it's not fully there yet (io.EOF).
	if err := reader.VerifyWandbHeader(wandbStoreVersion); err != nil && !errors.Is(err, io.EOF) {
		_ = f.Close()
		return nil, fmt.Errorf("livestore: header verify: %w", err)
	}
	return &LiveStore{f, reader, logger}, nil
}

// Reads the next record from the database.
func (lr *LiveStore) Read() (*spb.Record, error) {
	if lr.db == nil {
		return nil, fmt.Errorf("livestore: db is closed")
	}
	rdr, err := lr.reader.Next()
	if err != nil {
		return nil, err // include io.EOF (soft)
	}

	buf, err := io.ReadAll(rdr)
	if err != nil {
		return nil, fmt.Errorf("livestore: read record body: %w", err)
	}

	msg := &spb.Record{}
	if err := proto.Unmarshal(buf, msg); err != nil {
		// Helpful debug: print first bytes of the payload
		head := buf
		if len(head) > 32 {
			head = head[:32]
		}
		return nil, fmt.Errorf("livestore: unmarshal: %w (payload[0:32]=%s)", err, hex.EncodeToString(head))
	}
	return msg, nil
}

// Close closes the database.
func (ls *LiveStore) Close() {
	if ls.db == nil {
		return
	}

	db := ls.db
	ls.db = nil

	// Since we only use the file for reading, we do not care about
	// errors when closing, but they could indicate other issues with
	// the user's system.
	if err := db.Close(); err != nil {
		ls.logger.Warn(
			fmt.Sprintf("livestore: error closing reader: %v", err))
	}

	ls.reader = nil
}

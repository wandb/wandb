package leet

import (
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
)

type LiveStore struct {
	db     *os.File
	reader *leveldb.LiveReader
}

func NewLiveStore(filename string) (*LiveStore, error) {
	f, err := os.Open(filename)
	if err != nil {
		return nil, fmt.Errorf("livestore: failed opening file: %w", err)
	}
	reader := leveldb.NewLiveReader(f, leveldb.CRCAlgoIEEE)

	// Validate W&B header once; it's OK if it's not fully there yet (io.EOF).
	if err := reader.VerifyWandbHeader(0); err != nil && !errors.Is(err, io.EOF) {
		_ = f.Close()
		return nil, fmt.Errorf("livestore: header verify: %w", err)
	}
	return &LiveStore{f, reader}, nil
}

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

func (ls *LiveStore) Close() error {
	if ls.db == nil {
		return nil
	}

	db := ls.db
	ls.db = nil

	if err := db.Close(); err != nil {
		return fmt.Errorf("livestore: failed closing file: %v", err)
	}

	return nil
}

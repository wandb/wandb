package server

import (
	"bytes"
	"context"
	"encoding/binary"
	"os"

	"github.com/wandb/wandb/nexus/pkg/observability"

	"github.com/wandb/wandb/nexus/pkg/leveldb"
	"github.com/wandb/wandb/nexus/pkg/service"
	"google.golang.org/protobuf/proto"
)

// Store is the persistent store for a stream
type Store struct {
	// ctx is the context for the store
	ctx context.Context

	// writer is the underlying writer
	writer *leveldb.Writer

	// db is the underlying database
	db *os.File

	// logger is the logger for the store
	logger *observability.NexusLogger
}

// NewStore creates a new store
func NewStore(ctx context.Context, fileName string, logger *observability.NexusLogger) (*Store, error) {
	f, err := os.Create(fileName)
	if err != nil {
		logger.CaptureError("can't write header", err)
		return nil, err
	}
	writer := leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE)
	sr := &Store{ctx: ctx,
		writer: writer,
		db:     f,
		logger: logger,
	}
	if err = sr.addHeader(); err != nil {
		sr.logger.CaptureError("can't write header", err)
		return nil, err
	}
	return sr, nil
}

func (sr *Store) addHeader() error {
	type Header struct {
		ident   [4]byte
		magic   uint16
		version byte
	}
	buf := new(bytes.Buffer)
	ident := [4]byte{byte(':'), byte('W'), byte('&'), byte('B')}
	head := Header{ident: ident, magic: 0xBEE1, version: 0}
	if err := binary.Write(buf, binary.LittleEndian, &head); err != nil {
		sr.logger.CaptureError("can't write header", err)
		return err
	}
	if _, err := sr.db.Write(buf.Bytes()); err != nil {
		sr.logger.CaptureError("can't write header", err)
		return err
	}
	return nil
}

func (sr *Store) Flush() error {
	err := sr.writer.Flush()
	return err
}

func (sr *Store) Close() error {
	err := sr.writer.Close()
	return err
}

func (sr *Store) storeRecord(msg *service.Record) (int64, error) {
	writer, err := sr.writer.Next()
	if err != nil {
		sr.logger.CaptureError("can't write header", err)
		return 0, err
	}
	out, err := proto.Marshal(msg)
	if err != nil {
		sr.logger.CaptureError("can't write header", err)
		return 0, err
	}

	if _, err = writer.Write(out); err != nil {
		sr.logger.CaptureError("can't write header", err)
		return 0, err
	}

	offset, err := sr.writer.LastRecordOffset()
	if err != nil {
		sr.logger.CaptureError("can't write header", err)
		return 0, err
	}
	return offset, nil
}

package server

import (
	"bytes"
	"context"
	"encoding/binary"
	"os"

	"github.com/wandb/wandb/nexus/pkg/leveldb"
	"github.com/wandb/wandb/nexus/pkg/service"
	"golang.org/x/exp/slog"
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
	logger *slog.Logger
}

// NewStore creates a new store
func NewStore(ctx context.Context, fileName string, logger *slog.Logger) (*Store, error) {
	f, err := os.Create(fileName)
	if err != nil {
		logger.Error("cant create file", "error", err)
		return nil, err
	}
	writer := leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE)
	sr := &Store{ctx: ctx,
		writer: writer,
		db:     f,
		logger: logger}
	if err = sr.addHeader(); err != nil {
		sr.logger.Error("cant add header", "error", err)
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
		sr.logger.Error("cant write header", "error", err)
		return err
	}
	if _, err := sr.db.Write(buf.Bytes()); err != nil {
		sr.logger.Error("cant write header", "error", err)
		return err
	}
	return nil
}

func (sr *Store) Close() error {
	err := sr.writer.Close()
	return err
}

func (sr *Store) storeRecord(msg *service.Record) error {
	writer, err := sr.writer.Next()
	if err != nil {
		sr.logger.Error("cant get writer", "error", err)
		return err
	}
	out, err := proto.Marshal(msg)
	if err != nil {
		sr.logger.Error("cant marshal rec", "error", err)
		return err
	}

	if _, err = writer.Write(out); err != nil {
		sr.logger.Error("cant write rec", "error", err)
		return err
	}
	return nil
}

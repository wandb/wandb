package server

import (
	"bytes"
	"context"
	"encoding/binary"
	"fmt"
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

	// name is the name of the underlying file
	name string

	// writer is the underlying writer
	writer *leveldb.Writer

	// reader is the underlying reader
	reader *leveldb.Reader

	// db is the underlying database
	db *os.File

	// logger is the logger for the store
	logger *observability.NexusLogger
}

// NewStore creates a new store
func NewStore(ctx context.Context, fileName string, logger *observability.NexusLogger) *Store {
	sr := &Store{ctx: ctx,
		name:   fileName,
		logger: logger,
	}
	return sr
}

func (sr *Store) Open(flag int) error {
	switch flag {
	case os.O_RDONLY:
		f, err := os.Open(sr.name)
		if err != nil {
			sr.logger.CaptureError("can't open file", err)
			return err
		}
		sr.db = f
		sr.reader = leveldb.NewReaderExt(f, leveldb.CRCAlgoIEEE)
	case os.O_WRONLY:
		f, err := os.Create(sr.name)
		if err != nil {
			sr.logger.CaptureError("can't open file", err)
			return err
		}
		sr.db = f
		sr.writer = leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE)
		if err = sr.addHeader(); err != nil {
			sr.logger.CaptureError("can't write header", err)
			return err
		}
	default:
		// TODO: generalize this?
		err := fmt.Errorf("invalid flag %d", flag)
		sr.logger.CaptureError("can't open file", err)
		return err
	}
	return nil

	// f, err := os.Create(fileName)
	// if err != nil {
	// 	logger.CaptureError("can't write header", err)
	// 	return nil, err
	// }
	// writer := leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE)
	// sr := &Store{ctx: ctx,
	// 	writer: writer,
	// 	db:     f,
	// 	logger: logger,
	// }
	// if err = sr.addHeader(); err != nil {
	// 	sr.logger.CaptureError("can't write header", err)
	// 	return nil, err
	// }
	// return sr, nil

	// return nil
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

func (sr *Store) Close() error {
	err := sr.writer.Close()
	return err
}

func (sr *Store) storeRecord(msg *service.Record) error {
	writer, err := sr.writer.Next()
	if err != nil {
		sr.logger.CaptureError("can't write header", err)
		return err
	}
	out, err := proto.Marshal(msg)
	if err != nil {
		sr.logger.CaptureError("can't write header", err)
		return err
	}

	if _, err = writer.Write(out); err != nil {
		sr.logger.CaptureError("can't write header", err)
		return err
	}
	return nil
}

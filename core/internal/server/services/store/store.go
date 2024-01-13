package store

import (
	"context"
	"fmt"
	"io"
	"os"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/leveldb"
	"github.com/wandb/wandb/core/internal/observability"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

func IdentToByteSlice() [4]byte {
	byteSlice := []byte(HeaderIdent)
	var ident [4]byte
	copy(ident[:], byteSlice)
	return ident
}

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
	logger *observability.CoreLogger
}

// New creates a new store
func New(ctx context.Context, fileName string, logger *observability.CoreLogger) *Store {
	sr := &Store{ctx: ctx,
		name:   fileName,
		logger: logger,
	}
	return sr
}

// Open opens the store
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
		header := SHeader{}
		if err := header.Read(sr.db); err != nil {
			sr.logger.CaptureError("can't read header", err)
			return err
		}
		return nil
	case os.O_WRONLY:
		f, err := os.Create(sr.name)
		if err != nil {
			sr.logger.CaptureError("can't open file", err)
			return err
		}
		sr.db = f
		sr.writer = leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE)
		header := SHeader{}
		if err := header.Write(sr.db); err != nil {
			sr.logger.CaptureError("can't write header", err)
			return err
		}
		return nil
	default:
		// TODO: generalize this?
		err := fmt.Errorf("invalid flag %d", flag)
		sr.logger.CaptureError("can't open file", err)
		return err
	}
}

// Close closes the store
func (sr *Store) Close() error {
	if sr.writer != nil {
		err := sr.writer.Close()
		if err != nil {
			sr.logger.CaptureError("can't close file", err)
		}
	}

	err := sr.db.Close()
	if err != nil {
		sr.logger.CaptureError("can't close file", err)
	}
	sr.db = nil
	return err
}

func (sr *Store) Write(msg *pb.Record) error {
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

func (sr *Store) WriteDirectlyToDB(data []byte) (int, error) {
	// this is for testing purposes only
	return sr.db.Write(data)
}

func (sr *Store) Read() (*pb.Record, error) {
	// check if db is closed
	if sr.db == nil {
		err := fmt.Errorf("db is closed")
		sr.logger.CaptureError("can't read record", err)
		return nil, err
	}

	reader, err := sr.reader.Next()
	if err == io.EOF {
		return nil, err
	}

	if err != nil {
		sr.logger.CaptureError("can't read record", err)
		sr.reader.Recover()
		return nil, err
	}
	buf, err := io.ReadAll(reader)
	if err != nil {
		sr.logger.CaptureError("can't read record", err)
		sr.reader.Recover()
		return nil, err
	}
	msg := &pb.Record{}
	if err = proto.Unmarshal(buf, msg); err != nil {
		sr.logger.CaptureError("can't read record", err)
		return nil, err
	}
	return msg, nil
}

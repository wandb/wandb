package server

import (
	"context"
	"encoding/binary"
	"fmt"
	"io"
	"os"

	"github.com/wandb/wandb/core/pkg/observability"

	"github.com/wandb/wandb/core/pkg/leveldb"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/proto"
)

type HeaderOptions struct {
	IDENT   [4]byte
	Magic   uint16
	Version byte
}

const (
	// headerMagic is the magic number for the header.
	headerMagic = 0xBEE1
	// headerVersion is the version of the header.
	headerVersion = 0
)

// headerIdent returns the header identifier.
func headerIdent() [4]byte {
	return [4]byte{':', 'W', '&', 'B'}
}

// NewHeader returns a new header with default values.
func NewHeader() *HeaderOptions {
	return &HeaderOptions{
		IDENT:   headerIdent(),
		Magic:   headerMagic,
		Version: headerVersion,
	}
}

// MarshalBinary encodes the header to binary format.
func (o *HeaderOptions) MarshalBinary(w io.Writer) error {

	if err := binary.Write(w, binary.LittleEndian, o); err != nil {
		return fmt.Errorf("error writing binary data: %w", err)
	}
	return nil
}

// UnmarshalBinary decodes binary data into the header.
func (o *HeaderOptions) UnmarshalBinary(r io.Reader) error {
	if err := binary.Read(r, binary.LittleEndian, o); err != nil {
		return fmt.Errorf("error reading binary data: %w", err)
	}
	return nil
}

// Valid checks if the header is valid based on a reference header.
func (o *HeaderOptions) Valid() bool {
	return o.IDENT == headerIdent() && o.Magic == headerMagic && o.Version == headerVersion
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

// NewStore creates a new store
func NewStore(ctx context.Context, fileName string, logger *observability.CoreLogger) *Store {
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
		header := NewHeader()
		if err := header.UnmarshalBinary(sr.db); err != nil {
			sr.logger.CaptureError("can't read header", err)
			return err
		}
		if !header.Valid() {
			err := fmt.Errorf("invalid header")
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
		header := NewHeader()
		if err := header.MarshalBinary(sr.db); err != nil {
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

func (sr *Store) Write(msg *service.Record) error {
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

func (sr *Store) Read() (*service.Record, error) {
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
	msg := &service.Record{}
	if err = proto.Unmarshal(buf, msg); err != nil {
		sr.logger.CaptureError("can't read record", err)
		return nil, err
	}
	return msg, nil
}

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

const (
	HeaderIdent   = ":W&B"
	HeaderMagic   = 0xBEE1
	HeaderVersion = 0
)

type StoreHeader struct {
	ident   [4]byte
	magic   uint16
	version byte
}

func IdentToByteSlice() [4]byte {
	byteSlice := []byte(HeaderIdent)
	var ident [4]byte
	copy(ident[:], byteSlice)
	return ident
}

func (sh *StoreHeader) Write(w io.Writer) error {

	head := StoreHeader{ident: IdentToByteSlice(), magic: HeaderMagic, version: HeaderVersion}
	if err := binary.Write(w, binary.LittleEndian, &head); err != nil {
		return err
	}
	return nil
}

func (sh *StoreHeader) Read(r io.Reader) error {
	buf := [7]byte{}
	if err := binary.Read(r, binary.LittleEndian, &buf); err != nil {
		return err
	}
	sh.ident = [4]byte{buf[0], buf[1], buf[2], buf[3]}
	sh.magic = binary.LittleEndian.Uint16(buf[4:6])
	sh.version = buf[6]

	if sh.ident != IdentToByteSlice() {
		err := fmt.Errorf("invalid header")
		return err
	}
	if sh.magic != HeaderMagic {
		err := fmt.Errorf("invalid header")
		return err
	}
	if sh.version != HeaderVersion {
		err := fmt.Errorf("invalid header")
		return err
	}
	return nil
}

func (sh *StoreHeader) GetIdent() [4]byte {
	return sh.ident
}

func (sh *StoreHeader) GetMagic() uint16 {
	return sh.magic
}

func (sh *StoreHeader) GetVersion() byte {
	return sh.version
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
		header := StoreHeader{}
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
		header := StoreHeader{}
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

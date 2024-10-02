package server

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
	// headerLength is fixed to IDENT(4) + Magic(2) + Version(1) = 7
	headerLength = 7
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
	// name is the name of the underlying file
	name string

	// writer is the underlying writer
	writer *leveldb.Writer

	// reader is the underlying reader
	reader *leveldb.Reader

	// db is the underlying database
	db *os.File
}

// NewStore creates a new store
func NewStore(fileName string) *Store {
	return &Store{name: fileName}
}

// Open opens the store
func (sr *Store) Open(flag int) error {
	switch flag {
	case os.O_RDONLY:
		f, err := os.Open(sr.name)
		if err != nil {
			return fmt.Errorf("store: failed to open file: %v", err)
		}
		sr.db = f
		headerBuffer := make([]byte, headerLength)
		sr.reader = leveldb.NewReaderExt(f, leveldb.CRCAlgoIEEE)
		err = sr.reader.ReadHeader(headerBuffer)
		if err != nil {
			return fmt.Errorf("store: failed to read header: %v", err)
		}
		headerReader := bytes.NewReader(headerBuffer)
		header := NewHeader()
		if err = header.UnmarshalBinary(headerReader); err != nil {
			return fmt.Errorf("store: failed to unmarshal header: %v", err)
		}
		if !header.Valid() {
			return errors.New("store: invalid header")
		}
		return nil
	case os.O_WRONLY:
		f, err := os.Create(sr.name)
		if err != nil {
			return fmt.Errorf("store: failed to open file: %v", err)
		}
		sr.db = f
		var headerBuffer bytes.Buffer
		header := NewHeader()
		if err := header.MarshalBinary(&headerBuffer); err != nil {
			return fmt.Errorf("store: failed to write header: %v", err)
		}
		sr.writer = leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE, headerBuffer.Bytes())
		return nil
	default:
		// TODO: generalize this?
		return fmt.Errorf("store: invalid flag %d", flag)
	}
}

// Close closes the store
func (sr *Store) Close() error {
	errs := []error{}

	if sr.writer != nil {
		err := sr.writer.Close()
		if err != nil {
			errs = append(errs, fmt.Errorf("store: failed closing writer: %v", err))
		}
	}

	db := sr.db
	sr.db = nil

	err := db.Close()
	if err != nil {
		errs = append(errs, fmt.Errorf("store: failed closing file: %v", err))
	}

	return errors.Join(errs...)
}

func (sr *Store) Write(msg *spb.Record) error {
	writer, err := sr.writer.Next()
	if err != nil {
		return fmt.Errorf("store: can't get next record: %v", err)
	}
	out, err := proto.Marshal(msg)
	if err != nil {
		return fmt.Errorf("store: can't marshal proto: %v", err)
	}

	if _, err = writer.Write(out); err != nil {
		return fmt.Errorf("store: can't write proto: %v", err)
	}
	return nil
}

// Reads the next record from the database.
//
// Returns nil and an error on failure. On EOF, error is [io.EOF].
func (sr *Store) Read() (*spb.Record, error) {
	// check if db is closed
	if sr.db == nil {
		return nil, fmt.Errorf("store: db is closed")
	}

	reader, err := sr.reader.Next()
	if err == io.EOF {
		return nil, io.EOF
	}

	if err != nil {
		sr.reader.Recover()
		return nil, fmt.Errorf("store: failed to get next record: %v", err)
	}
	buf, err := io.ReadAll(reader)
	if err != nil {
		sr.reader.Recover()
		return nil, fmt.Errorf("store: error reading: %v", err)
	}
	msg := &spb.Record{}
	if err = proto.Unmarshal(buf, msg); err != nil {
		return nil, fmt.Errorf("store: failed to unmarshal: %v", err)
	}
	return msg, nil
}

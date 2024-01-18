package store

import (
	"context"
	"errors"
	"io"
	"os"

	"github.com/wandb/wandb/core/internal/leveldb"
)

// HeaderSchema interface for the store header
//
// UnmarshalBinary reads the header from the reader into the header
// MarshalBinary writes the header to the writer from the header
// Valid checks if the header is valid based on the header defined schema
type HeaderSchema interface {
	UnmarshalBinary(io.Reader) error
	MarshalBinary(io.Writer) error
	Valid() bool
}

// defaultHeader is the default header for the store
//
// It is used if no header is provided
type defaultHeader struct {
}

func (dh *defaultHeader) MarshalBinary(io.Writer) error {
	return nil
}

func (dh *defaultHeader) UnmarshalBinary(io.Reader) error {
	return nil
}

func (dh *defaultHeader) Valid() bool {
	return true
}

// ErrInvalidHeader is the error for an invalid header
// based on the header defined schema
var ErrInvalidHeader = errors.New("invalid header")

// StoreOptions are the options for the store
//
// Name is the name of the underlying file that is used for the store
// Flag is the flag for the store use the os package flags
// Header is the header for the store to use for validation and versioning
type StoreOptions struct {
	Name   string
	Flag   int
	Header HeaderSchema
}

// Store is the persistent store
//
// It is an append-only log that stores records in a binary format
// Uses leveldb for the underlying protocol buffer storage
// Uses a header to validate the store and version it
type Store struct {
	// ctx is the context for the store
	ctx context.Context

	// name is the name of the underlying file
	name string

	// writer is the underlying leveldb writer for the store
	writer *leveldb.Writer

	// reader is the underlying leveldb reader for the store
	reader *leveldb.Reader

	// db is the underlying database file
	db *os.File

	// flag is the flag for the store use the os package flags
	flag int

	// h is the header for the store to use for validation and versioning
	h HeaderSchema
}

var ErrInvalidFlag = errors.New("invalid flag")

// New creates a new store
func New(ctx context.Context, opts StoreOptions) *Store {
	if opts.Header == nil {
		opts.Header = &defaultHeader{}
	}
	return &Store{
		ctx:  ctx,
		name: opts.Name,
		flag: opts.Flag,
		h:    opts.Header,
	}
}

// Open opens the store for reading or writing
//
// It opens the underlying file and creates the leveldb reader or writer
// In the case of writing it also writes the header to the file for validation and versioning
// In the case of reading it also reads the header from the file for validation and versioning
// Currently only supports os.O_RDONLY and os.O_WRONLY flags
func (sr *Store) Open() error {
	switch sr.flag {
	case os.O_RDONLY:
		var err error
		if sr.db, err = os.Open(sr.name); err != nil {
			return err
		}
		sr.reader = leveldb.NewReaderExt(sr.db, leveldb.CRCAlgoIEEE)
		if err := sr.h.UnmarshalBinary(sr.db); err != nil {
			return err
		}
		if !sr.h.Valid() {
			return ErrInvalidHeader
		}
		return nil
	case os.O_WRONLY:
		var err error
		if sr.db, err = os.Create(sr.name); err != nil {
			return err
		}
		sr.writer = leveldb.NewWriterExt(sr.db, leveldb.CRCAlgoIEEE)
		if err := sr.h.MarshalBinary(sr.db); err != nil {
			return err
		}
		return nil
	default:
		return ErrInvalidFlag
	}
}

// Close closes the store
//
// It closes the underlying file and the leveldb writer
func (sr *Store) Close() error {
	var rerr error
	if sr.writer != nil {
		rerr = sr.writer.Close()
	}

	if err := sr.db.Close(); err != nil {
		rerr = err
	}
	sr.db = nil
	return rerr
}

// Write writes a record to the store
//
// It writes the record using the leveldb writer
func (sr *Store) Write(data []byte) error {
	writer, err := sr.writer.Next()
	if err != nil {
		return err
	}
	if _, err = writer.Write(data); err != nil {
		return err
	}
	return nil
}

// WriteDirectly writes a record to the store without using the leveldb writer
//
// This method is for testing purposes only and should not be used in production
// Note that using this method directly might corrupt the underlying store file
// Use with caution and only for testing purposes
func (sr *Store) WriteDirectly(data []byte) (int, error) {
	// this is for testing purposes only
	return sr.db.Write(data)
}

// Read reads a record from the store and returns it
//
// It reads the record for the store using the leveldb reader
func (sr *Store) Read() ([]byte, error) {
	// check if db is closed
	if sr.db == nil {
		return nil, errors.New("db is closed")
	}

	reader, err := sr.reader.Next()
	if errors.Is(err, io.EOF) {
		return nil, err
	}

	if err != nil {
		sr.reader.Recover()
		return nil, err
	}
	bytes, err := io.ReadAll(reader)
	if err != nil {
		sr.reader.Recover()
		return nil, err
	}
	return bytes, nil
}

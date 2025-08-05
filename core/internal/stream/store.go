package stream

import (
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
)

const wandbStoreVersion = 0

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
		sr.reader = leveldb.NewReaderExt(f, leveldb.CRCAlgoIEEE)
		err = sr.reader.VerifyWandbHeader(wandbStoreVersion)
		if err != nil {
			return fmt.Errorf("store: Open: %v", err)
		}
		return nil

	case os.O_WRONLY:
		f, err := os.Create(sr.name)
		if err != nil {
			return fmt.Errorf("store: failed to open file: %v", err)
		}
		sr.db = f
		sr.writer = leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE, wandbStoreVersion)
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

// Recover clears any errors, so that calling Next will restart
// reading from the next good block.
func (sr *Store) Recover() {
	if sr.reader != nil {
		sr.reader.Recover()
	}
}

// GetCurrentOffset returns the current read offset if the underlying reader supports seeking.
// Returns -1 if seeking is not supported or if there's an error.
func (sr *Store) GetCurrentOffset() int64 {
	if sr.db == nil {
		return -1
	}

	offset, err := sr.db.Seek(0, io.SeekCurrent)
	if err != nil {
		return -1
	}

	return offset
}

// SeekToOffset seeks to the specified offset before the next read operation.
// This is useful for retrying reads from a known good position when monitoring live files.
func (sr *Store) SeekToOffset(offset int64) error {
	if sr.db == nil {
		return fmt.Errorf("store: db is closed")
	}

	if sr.reader == nil {
		return fmt.Errorf("store: reader not initialized")
	}

	// Use the leveldb.Reader's SeekRecord method to seek to the offset
	// This maintains proper reader state unlike raw file seeking
	err := sr.reader.SeekRecord(offset)
	if err != nil {
		// If SeekRecord fails, try a more manual approach
		// Seek the underlying file
		_, seekErr := sr.db.Seek(offset, io.SeekStart)
		if seekErr != nil {
			return fmt.Errorf("store: failed to seek: %w", seekErr)
		}

		// Recreate the reader from the seeked position
		sr.reader = leveldb.NewReaderExt(sr.db, leveldb.CRCAlgoIEEE)

		// If we're seeking past the header, we don't need to verify it again
		// The header is 7 bytes, so if offset > 7, skip verification
		if offset <= 7 {
			// Re-verify the header if seeking to beginning
			if err := sr.reader.VerifyWandbHeader(wandbStoreVersion); err != nil {
				return fmt.Errorf("store: failed to verify header after seek: %w", err)
			}
		}
	}

	return nil
}

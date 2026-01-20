package transactionlog

import (
	"errors"
	"fmt"
	"os"

	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Writer creates a .wandb file.
//
// Not safe for use in multiple goroutines.
type Writer struct {
	writer *leveldb.Writer // nil when closed
	file   *os.File
}

// OpenWriter opens a .wandb file for writing.
//
// The file must not already exist. It is created with permissions 0o666
// (meaning read and write permissions for user, group and others).
//
// The file header is output immediately, so that OpenReader() can open it
// before any records are written.
//
// The parent directory must exist.
//
// Wraps errors from the os.OpenFile() call so that they can be checked
// with errors.Is().
func OpenWriter(path string) (*Writer, error) {
	// O_EXCL returns an error if the file already exists.
	//
	// Note that os.Create() silently truncates an existing file,
	// which is very bad if it happens to be an actual transaction log.
	// Could happen due to a race between two wandb scripts!
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o666)
	if err != nil {
		return nil, fmt.Errorf("transactionlog: error creating file: %w", err)
	}

	writer := leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE, wandbStoreVersion)

	// Flush immediately to write the file's header.
	if err := writer.Flush(); err != nil {
		_ = f.Close()
		return nil, fmt.Errorf("transactionlog: error writing header: %v", err)
	}

	return &Writer{writer: writer, file: f}, nil
}

// Write writes the next record into the transaction log.
func (w *Writer) Write(msg *spb.Record) error {
	if w.writer == nil {
		return errors.New("transactionlog: writer is closed")
	}

	msgBytes, err := proto.Marshal(msg)
	if err != nil {
		return fmt.Errorf("transactionlog: error marshaling: %v", err)
	}

	recordWriter, err := w.writer.Next()
	if err != nil {
		return fmt.Errorf("transactionlog: error starting next record: %v", err)
	}

	// NOTE: The io.Writer contract guarantees a non-nil error on a short write.
	_, err = recordWriter.Write(msgBytes)
	if err != nil {
		return fmt.Errorf("transactionlog: error writing: %v", err)
	}

	return nil
}

// Flush flushes the in-memory store to disk.
func (w *Writer) Flush() error {
	return w.writer.Flush()
}

// LastRecordOffset returns the offset where the last record was written.
func (w *Writer) LastRecordOffset() (int64, error) {
	return w.writer.LastRecordOffset()
}

// Close closes the file.
//
// The writer may not be used after.
// An error could indicate that not all data was written.
func (w *Writer) Close() error {
	if w.writer == nil {
		return errors.New("transactionlog: writer already closed")
	}

	var errs []error

	if err := w.writer.Close(); err != nil {
		errs = append(errs,
			fmt.Errorf("transactionlog: error closing writer: %v", err))
	}

	if err := w.file.Close(); err != nil {
		errs = append(errs,
			fmt.Errorf("transactionlog: error closing file: %v", err))
	}

	w.writer = nil
	return errors.Join(errs...)
}

package stream

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
)

// Only live streams construct this; replay should never back itself up.
type transactionLogBackup struct {
	writer      *Writer
	executionID string
}

func (s *Sender) startTransactionLogBackup() <-chan struct{} {
	if s.transactionLogBackup == nil {
		return nil
	}

	done := make(chan struct{})
	go func() {
		defer close(done)
		defer s.logger.Reraise("stream")

		ctx := s.runWork.BeforeEndCtx()
		if s.settings.Proto.XTransactionLogBackupTimeout != nil {
			var cancel context.CancelFunc
			ctx, cancel = context.WithTimeout(ctx, s.settings.GetTransactionLogBackupTimeout())
			defer cancel()
		}

		if err := s.backupTransactionLog(ctx); err != nil {
			s.printer.Warnf("Transaction log backup failed; local run files were retained: %v", err)
		}
	}()

	return done
}

func (s *Sender) backupTransactionLog(ctx context.Context) error {
	upserter, err := s.runHandle.Upserter()
	if err != nil {
		return err
	}

	backup := s.transactionLogBackup
	if backup.writer == nil {
		return errors.New("transaction log writer is unavailable")
	}

	if err := ctx.Err(); err != nil {
		return err
	}
	source, err := os.Open(s.settings.GetTransactionLogPath())
	if err != nil {
		return fmt.Errorf("open transaction log: %w", err)
	}
	defer source.Close()

	if err := backup.writer.Flush(); err != nil {
		return fmt.Errorf("flush transaction log: %w", err)
	}
	
	size, err := backup.writer.Size()
	if err != nil {
		return fmt.Errorf("stat transaction log: %w", err)
	}

	return uploadTransactionLogBackup(ctx, s.settings.GetTransactionLogBackup(), upserter.RunPath().RunID, backup.executionID, source, size)
}

type transactionLogBackupContextReader struct {
	ctx    context.Context
	reader io.Reader
}

func (r transactionLogBackupContextReader) Read(p []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.reader.Read(p)
}

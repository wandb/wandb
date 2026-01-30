package runsync

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"sync"
	"time"

	"github.com/google/wire"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/stream"
	"github.com/wandb/wandb/core/internal/transactionlog"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var runReaderProviders = wire.NewSet(
	wire.Struct(new(RunReaderFactory), "*"),
)

// RunReaderFactory constructs RunReader.
type RunReaderFactory struct {
	Logger     *observability.CoreLogger
	Operations *wboperation.WandbOperations
}

// RunReader gets information out of .wandb files.
type RunReader struct {
	path        string          // transaction log path
	displayPath DisplayPath     // printable form of 'path'
	updates     *RunSyncUpdates // modifications to make to records
	live        bool            // "live" mode retries EOFs

	seenExit bool // whether we've processed an exit record yet

	logger       *observability.CoreLogger
	operations   *wboperation.WandbOperations
	recordParser stream.RecordParser
	runWork      runwork.RunWork
}

func (f *RunReaderFactory) New(
	path string,
	displayPath DisplayPath,
	updates *RunSyncUpdates,
	live bool,
	recordParser stream.RecordParser,
	runWork runwork.RunWork,
) *RunReader {
	return &RunReader{
		path:        path,
		displayPath: displayPath,
		updates:     updates,
		live:        live,

		logger:       f.Logger,
		operations:   f.Operations,
		recordParser: recordParser,
		runWork:      runWork,
	}
}

// ExtractRunInfo reads and returns basic run information.
func (r *RunReader) ExtractRunInfo(ctx context.Context) (*RunInfo, error) {
	r.logger.Info("runsync: getting info", "path", r.path)

	reader, err := r.open()
	if err != nil {
		return nil, err
	}
	defer reader.Close()

	for {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		default:
		}

		record, err := r.nextUpdatedRecord(ctx, reader, true /*retryEOF*/)

		if err != nil {
			return nil, &SyncError{
				Err:      err,
				Message:  "didn't find run info",
				UserText: fmt.Sprintf("Failed to read %q: %v", r.displayPath, err),
			}
		}

		if run := record.GetRun(); run != nil {
			return &RunInfo{
				Entity:    run.Entity,
				Project:   run.Project,
				RunID:     run.RunId,
				StartTime: run.StartTime.AsTime(),
			}, nil
		}
	}
}

// ProcessTransactionLog processes the .wandb file and adds to RunWork.
//
// Returns an error if it fails to start or on partial success.
//
// Closes RunWork at the end, even on error. If there was no Exit record,
// creates one with an exit code of 1.
func (r *RunReader) ProcessTransactionLog(ctx context.Context) error {
	r.logger.Info("runsync: starting to read", "path", r.path)

	// Abort any async work on cancellation.
	cancelAbort := context.AfterFunc(ctx, r.runWork.Abort)
	defer cancelAbort() // must run after closeRunWork()

	defer r.closeRunWork()

	reader, err := r.open()
	if err != nil {
		return err
	}
	defer reader.Close()

	for {
		record, err := r.nextUpdatedRecord(ctx, reader, !r.seenExit /*retryEOF*/)

		if errors.Is(err, io.EOF) {
			r.logger.Info("runsync: done reading", "path", r.path)
			return nil
		}

		if err != nil {
			// TODO: Keep going to skip corrupt data.
			//   Need to update Read so that we can tell if we can recover.
			return err
		}

		r.parseAndAddWork(record)

		switch {
		case record.GetExit() != nil:
			r.seenExit = true
		case record.GetRun() != nil:
			// The RunStart request is required to come after a Run record,
			// but its contents are irrelevant when syncing. It causes
			// the Sender to start FileStream.
			r.parseAndAddWork(
				&spb.Record{RecordType: &spb.Record_Request{
					Request: &spb.Request{RequestType: &spb.Request_RunStart{
						RunStart: &spb.RunStartRequest{},
					}},
				}})
		}
	}
}

// closeRunWork closes RunWork creating an exit record if one hasn't been seen.
func (r *RunReader) closeRunWork() {
	if !r.seenExit {
		r.logger.Warn(
			"runsync: no exit record encountered, using exit code 1 (failed)",
			"path", r.path)

		r.parseAndAddWork(
			&spb.Record{
				RecordType: &spb.Record_Exit{
					Exit: &spb.RunExitRecord{
						ExitCode: 1,
					},
				},
			})
	}

	r.runWork.Close()
}

// open returns an opened transaction log Reader.
func (r *RunReader) open() (*transactionlog.Reader, error) {
	reader, err := transactionlog.OpenReader(r.path, r.logger)

	if err == nil {
		return reader, nil
	}

	syncErr := &SyncError{
		Err:     err,
		Message: "failed to open reader",
	}

	switch {
	case errors.Is(err, os.ErrNotExist):
		syncErr.UserText = fmt.Sprintf("File does not exist: %s", r.displayPath)

	case errors.Is(err, os.ErrPermission):
		syncErr.UserText = fmt.Sprintf(
			"Permission error opening file for reading: %s",
			r.displayPath,
		)
	}

	return nil, syncErr
}

// nextUpdatedRecord returns the next record in the reader,
// with modifications applied.
//
// Retries ErrUnexpectedEOF in live mode, and also EOF if retryEOF is true.
func (r *RunReader) nextUpdatedRecord(
	ctx context.Context,
	reader *transactionlog.Reader,
	retryEOF bool,
) (record *spb.Record, err error) {
	record, err = reader.Read()

	if r.live {
		op := r.operations.New("waiting for more data")
		defer op.Finish()

		for errors.Is(err, io.ErrUnexpectedEOF) ||
			(retryEOF && errors.Is(err, io.EOF)) {
			r.logger.Info(
				"runsync: retrying read error in live mode",
				"path", r.path,
				"error", err)

			if err := reader.ResetLastRead(); err != nil {
				return nil, fmt.Errorf("failed to seek: %v", err)
			}

			select {
			case <-ctx.Done():
				// NOTE: We don't wrap the original error with errors.Join(...)
				// because the caller interprets errors. An EOF that we stopped
				// retrying because of cancellation should not be treated like
				// a normal EOF.
				return nil, ctx.Err()

			// TODO: Use FS event mechanisms when available instead of polling.
			case <-time.After(time.Second):
			}
			record, err = reader.Read()
		}
	}

	if err != nil {
		return
	}

	r.updates.Modify(record)
	return
}

// parseAndAddWork parses the record and pushes it to RunWork.
func (r *RunReader) parseAndAddWork(record *spb.Record) {
	work := r.recordParser.Parse(record)

	wg := &sync.WaitGroup{}

	// NOTE: Don't use AddWorkOrCancel to avoid setting seenExit for
	// an Exit record that was never sent. We rely on RunWork.Abort()
	// quickly unblocking the pipeline if the operation is cancelled.
	work.Schedule(wg, func() { r.runWork.AddWork(work) })

	// We always process records in reading order.
	wg.Wait()
}

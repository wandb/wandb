package runupserter

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
)

const (
	runUpsertDebounceSeconds = 5
)

type StreamRunUpserter interface {
	// SetRunUpserter is called when a new run is created successfully.
	//
	// It is called from the Sender goroutine and only if GetRunUpserter returns
	// nil.
	SetRunUpserter(upserter *RunUpserter) error

	// GetRunUpserter returns the run set by a previous call to SetRunUpserter.
	//
	// It is called from the Sender goroutine.
	GetRunUpserter() (*RunUpserter, error)
}

// RunUpdateWork implements Work to initialize or update a run.
type RunUpdateWork struct {
	runwork.SimpleScheduleMixin

	// Record contains the RunRecord that triggered this work.
	Record *spb.Record

	// StreamRunUpserter is used to update the stream's run information.
	StreamRunUpserter StreamRunUpserter

	ClientID           string
	Settings           *settings.Settings
	BeforeRunEndCtx    context.Context
	Operations         *wboperation.WandbOperations
	FeatureProvider    *featurechecker.ServerFeaturesCache
	GraphqlClientOrNil graphql.Client
	Logger             *observability.CoreLogger
}

// Accept implements Work.Accept.
func (w *RunUpdateWork) Accept(_ func(*spb.Record)) bool {
	return true
}

// ToRecord implements Work.ToRecord.
func (w *RunUpdateWork) ToRecord() *spb.Record {
	return w.Record
}

// Process implements Work.Process.
func (w *RunUpdateWork) Process(
	_ func(*spb.Record),
	results chan<- *spb.Result,
) {
	if upserter, _ := w.StreamRunUpserter.GetRunUpserter(); upserter != nil {
		w.updateRun(upserter)
	} else {
		w.initRun(results)
	}
}

// updateRun updates an existing run.
func (w *RunUpdateWork) updateRun(run *RunUpserter) {
	run.Update(w.Record.GetRun())
}

// initRun creates a run for the first time.
func (w *RunUpdateWork) initRun(results chan<- *spb.Result) {
	upserter, err := InitRun(w.Record, RunUpserterParams{
		Settings: w.Settings,

		DebounceDelay: waiting.NewDelay(runUpsertDebounceSeconds * time.Second),

		ClientID:           w.ClientID,
		BeforeRunEndCtx:    w.BeforeRunEndCtx,
		Operations:         w.Operations,
		FeatureProvider:    w.FeatureProvider,
		GraphqlClientOrNil: w.GraphqlClientOrNil,
		Logger:             w.Logger,
	})

	if err != nil {
		w.Logger.Error("runupserter: failed to init run", "error", err)

		if w.Record.Control.GetMailboxSlot() != "" {
			respondRunUpdate(results, w.Record, runInitErrorResult(err))
		}

		return
	}

	err = w.StreamRunUpserter.SetRunUpserter(upserter)
	if err != nil {
		w.Logger.CaptureError(
			fmt.Errorf(
				"runupserter: failed to set run after initializing: %v",
				err))

		if w.Record.Control.GetMailboxSlot() != "" {
			respondRunUpdate(results, w.Record, runInitErrorResult(err))
		}

		return
	}

	if w.Record.Control.GetMailboxSlot() != "" {
		updatedRun := proto.CloneOf(w.Record.GetRun())
		upserter.FillRunRecord(updatedRun)
		respondRunUpdate(results, w.Record, &spb.RunUpdateResult{Run: updatedRun})
	}
}

// respondRunUpdate pushes a RunUpdateResult to the result channel.
func respondRunUpdate(
	outChan chan<- *spb.Result,
	record *spb.Record,
	result *spb.RunUpdateResult,
) {
	outChan <- &spb.Result{
		ResultType: &spb.Result_RunResult{
			RunResult: result,
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
}

// runInitErrorResult produces a RunUpdateResult for an initialization error.
//
// If the error is a RunUpdateError, it is used to enhance the message.
// Otherwise, a generic error with an unknown code is returned.
func runInitErrorResult(err error) *spb.RunUpdateResult {
	var runUpdateError *RunUpdateError
	if errors.As(err, &runUpdateError) {
		return runUpdateError.AsResult()
	} else {
		return &spb.RunUpdateResult{
			Error: &spb.ErrorInfo{
				Message: fmt.Sprintf("Error initializing run: %v", err),
				Code:    spb.ErrorInfo_UNKNOWN,
			},
		}
	}
}

// BypassOfflineMode implements Work.BypassOfflineMode.
func (w *RunUpdateWork) BypassOfflineMode() bool {
	return true
}

// DebugInfo implements Work.DebugInfo.
func (w *RunUpdateWork) DebugInfo() string {
	return fmt.Sprintf("RunUpdateWork; Control(%v)", w.Record.GetControl())
}

package runupserter

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/Khan/genqlient/graphql"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	runUpsertDebounceSeconds = 5
)

// RunHandle is the same as runhandle.RunHandle, created to avoid
// a reference cycle.
type RunHandle interface {
	// Init is called when a new run is created successfully.
	//
	// It is called from the Sender goroutine and only if GetRunUpserter returns
	// nil.
	Init(upserter *RunUpserter) error

	// Upserter returns the run set by a previous call to SetRunUpserter.
	//
	// It is called from the Sender goroutine.
	Upserter() (*RunUpserter, error)
}

// RunUpdateWork implements Work to initialize or update a run.
type RunUpdateWork struct {
	runwork.SimpleScheduleMixin

	// Record contains the RunRecord that triggered this work.
	Record *spb.Record

	// RunHandle is used to update the stream's run information.
	RunHandle RunHandle

	ClientID           string
	Settings           *settings.Settings
	BeforeRunEndCtx    context.Context
	Operations         *wboperation.WandbOperations
	FeatureProvider    *featurechecker.FeatureProvider
	GraphqlClientOrNil graphql.Client
	Logger             *observability.CoreLogger
}

// Accept implements WorkImpl.Accept.
func (w *RunUpdateWork) Accept(
	_ *runwork.Request,
	_ func(*spb.Record, *runwork.Request),
) bool {
	return true
}

// ToRecord implements WorkImpl.ToRecord.
func (w *RunUpdateWork) ToRecord() *spb.Record {
	return w.Record
}

// Process implements WorkImpl.Process.
func (w *RunUpdateWork) Process(
	request *runwork.Request,
	_ func(*spb.Record, *runwork.Request),
) {
	if upserter, _ := w.RunHandle.Upserter(); upserter != nil {
		w.updateRun(upserter)
	} else {
		w.initRun(request)
	}
}

// updateRun updates an existing run.
func (w *RunUpdateWork) updateRun(run *RunUpserter) {
	run.Update(w.Record.GetRun())
}

// initRun creates a run for the first time.
func (w *RunUpdateWork) initRun(request *runwork.Request) {
	upserter, err := InitRun(w.Record, RunUpserterParams{
		Settings: w.Settings,

		DebounceDelay: runUpsertDebounceSeconds * time.Second,

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
			respondRunUpdate(request, runInitErrorResult(err))
		}

		return
	}

	err = w.RunHandle.Init(upserter)
	if err != nil {
		w.Logger.CaptureError(
			fmt.Errorf(
				"runupserter: failed to set run after initializing: %v",
				err))

		if w.Record.Control.GetMailboxSlot() != "" {
			respondRunUpdate(request, runInitErrorResult(err))
		}

		return
	}

	if w.Record.Control.GetMailboxSlot() != "" {
		updatedRun := proto.CloneOf(w.Record.GetRun())
		upserter.FillRunRecord(updatedRun)
		respondRunUpdate(request, &spb.RunUpdateResult{Run: updatedRun})
	}
}

// respondRunUpdate responds with a RunUpdateResult to the request.
func respondRunUpdate(
	request *runwork.Request,
	result *spb.RunUpdateResult,
) {
	request.Respond(&spb.ServerResponse{
		ServerResponseType: &spb.ServerResponse_ResultCommunicate{
			ResultCommunicate: &spb.Result{
				ResultType: &spb.Result_RunResult{
					RunResult: result,
				},
			},
		},
	})
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

// BypassOfflineMode implements WorkImpl.BypassOfflineMode.
func (w *RunUpdateWork) BypassOfflineMode() bool {
	return true
}

// DebugInfo implements WorkImpl.DebugInfo.
func (w *RunUpdateWork) DebugInfo() string {
	return fmt.Sprintf("RunUpdateWork; Control(%v)", w.Record.GetControl())
}

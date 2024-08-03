package runbranch

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/core/pkg/utils"
)

type ResumeBranch struct {
	ctx    context.Context
	client graphql.Client
	mode   string
}

// NewResumeBranch creates a new ResumeBranch
func NewResumeBranch(ctx context.Context, client graphql.Client, mode string) *ResumeBranch {
	return &ResumeBranch{ctx: ctx, client: client, mode: mode}
}

// GetUpdates updates the state based on the resume mode
// and the Run resume status we get from the server
func (rb *ResumeBranch) GetUpdates(
	params *RunParams,
	runpath RunPath,
) (*RunParams, error) {

	response, err := gql.RunResumeStatus(
		rb.ctx,
		rb.client,
		&runpath.Project,
		utils.NilIfZero(runpath.Entity),
		runpath.RunID,
	)

	// if we get an error we are in an unknown state and we should raise an error
	if err != nil {
		info := &service.ErrorInfo{
			Code:    service.ErrorInfo_COMMUNICATION,
			Message: fmt.Sprintf("Failed to get resume status for run %s: %s", runpath.RunID, err),
		}
		return nil, &BranchError{Err: err, Response: info}
	}

	var data *gql.RunResumeStatusModelProjectBucketRun
	if runExists(response) {
		data = response.GetModel().GetBucket()
	}

	// if we are not in the resume mode MUST and we didn't get data, we can just
	// return without error
	if data == nil && rb.mode != "must" {
		return nil, nil
	}

	// if we are in the resume mode MUST and we don't have data (the run is not initialized),
	// we need to return an error because we can't resume
	if data == nil && rb.mode == "must" {
		info := &service.ErrorInfo{
			Code: service.ErrorInfo_USAGE,
			Message: fmt.Sprintf("You provided an invalid value for the `resume` argument."+
				" The value 'must' is not a valid option for resuming the run (%s) that has not been initialized."+
				" Please check your inputs and try again with a valid run ID."+
				" If you are trying to start a new run, please omit the `resume` argument or use `resume='allow'`.",
				runpath.RunID),
		}
		err = errors.New("no data but must resume")
		return nil, &BranchError{Err: err, Response: info}
	}

	// if we have data and we are in a never resume mode we need to return an
	// error because we are not allowed to resume
	if data != nil && rb.mode == "never" {
		info := &service.ErrorInfo{
			Code: service.ErrorInfo_USAGE,
			Message: fmt.Sprintf("You provided an invalid value for the `resume` argument."+
				"  The value 'never' is not a valid option for resuming a run (%s) that already exists."+
				"  Please check your inputs and try again with a valid value for the `resume` argument.",
				runpath.RunID),
		}
		err = errors.New("data but cannot resume")
		return nil, &BranchError{Err: err, Response: info}
	}

	// if we have data and we are in the MUST or ALLOW resume mode, we can resume the run
	if data != nil && rb.mode != "never" {
		update, err := processResponse(params, data)
		if err != nil && rb.mode == "must" {
			info := &service.ErrorInfo{
				Code: service.ErrorInfo_USAGE,
				Message: fmt.Sprintf("The run (%s) failed to resume, and the `resume` argument is set to 'must'.",
					runpath.RunID),
			}
			err = fmt.Errorf("could not resume run: %s", err)
			return nil, &BranchError{Err: err, Response: info}
		} else if err != nil {
			return nil, err
		}
		return update, nil
	}

	return nil, nil
}

// runExists checks if the run exists based on the response we get from the server
func runExists(response *gql.RunResumeStatusResponse) bool {
	// If response is nil, run doesn't exist yet
	if response == nil {
		return false
	}

	// if response doesn't have a model, or the model doesn't have a bucket, the run doesn't exist
	// or the backend is not returning the expected data
	if response.GetModel() == nil || response.GetModel().GetBucket() == nil {
		return false
	}

	// If bucket is non-nil but WandbConfig has no "t" key, the run exists but hasn't started
	// (e.g. a sweep run that was created ahead of time)
	bucket := response.GetModel().GetBucket()
	if bucket.GetWandbConfig() == nil {
		return false
	}
	var cfg map[string]any
	if err := json.Unmarshal([]byte(*bucket.GetWandbConfig()), &cfg); err != nil {
		return false
	}
	if _, ok := cfg["t"]; !ok {
		return false
	}
	return true
}

// processResponse extracts the run state from the data we get from the server
func processResponse(params *RunParams, data *gql.RunResumeStatusModelProjectBucketRun) (*RunParams, error) {
	r := params.Clone()

	// Get Config information
	cfg := data.GetConfig()
	if cfg == nil {
		return nil, fmt.Errorf("no config found")
	}
	config, err := processConfig(cfg)
	if err != nil {
		return nil, err
	}
	r.Config = config

	// Get Tags information
	r.Tags = data.GetTags()

	r.Resumed = true

	if r.FileStreamOffset == nil {
		r.FileStreamOffset = make(filestream.FileStreamOffsetMap)
	}

	// update the file stream offsets with the data from the server
	if data.GetHistoryLineCount() != nil {
		r.FileStreamOffset[filestream.HistoryChunk] = *data.GetHistoryLineCount()
	} else {
		return nil, errors.New("no history line count found in resume response")
	}

	if data.GetEventsLineCount() != nil {
		r.FileStreamOffset[filestream.EventsChunk] = *data.GetEventsLineCount()
	} else {
		return nil, errors.New("no events line count found in resume response")
	}

	if data.GetLogLineCount() != nil {
		r.FileStreamOffset[filestream.OutputChunk] = *data.GetLogLineCount()
	} else {
		return nil, errors.New("no log line count found in resume response")
	}

	// extract runtime from the events tail if it exists we will use the maximal
	// value of runtime that we find
	events, err := processEventsTail(data.GetEventsTail())
	if err != nil {
		return nil, err
	}
	if events != nil {
		if runtime, ok := events["_runtime"]; ok {
			r.Runtime = int32(math.Max(extractRuntime(runtime), float64(r.Runtime)))
		}
	}

	// Get Summary information
	summary, err := processSummary(data.GetSummaryMetrics())
	if err != nil {
		return nil, err
	}
	if summary != nil {
		r.Summary = summary

		if step, ok := summary["_step"]; ok {
			// if we are resuming, we need to update the starting step
			// to be the next step after the last step we ran
			if x, ok := step.(int64); ok {
				r.StartingStep = x
			}
		}

		// if summary["wandb"]["runtime"] exists it takes precedence over
		// summary["_runtime"] for the runtime value
		switch x := r.Summary["wandb"].(type) {
		case map[string]any:
			if runtime, ok := x["runtime"]; ok {
				r.Runtime = int32(math.Max(extractRuntime(runtime), float64(r.Runtime)))
			}
		default:
			if runtime, ok := r.Summary["_runtime"]; ok {
				r.Runtime = int32(math.Max(extractRuntime(runtime), float64(r.Runtime)))
			}
		}
	}

	// if we are resuming, we need to update the starting step
	if r.FileStreamOffset[filestream.HistoryChunk] > 0 {
		r.StartingStep += 1
	}

	if !r.StartTime.IsZero() {
		r.StartTime = r.StartTime.Add(time.Duration(-r.Runtime) * time.Second)
	}

	return r, nil
}

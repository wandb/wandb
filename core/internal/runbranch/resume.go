package runbranch

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"maps"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/nullify"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runconfig"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type ResumeBranch struct {
	ctx    context.Context
	client graphql.Client
	mode   string
	logger *observability.CoreLogger
}

// NewResumeBranch creates a new ResumeBranch
func NewResumeBranch(
	ctx context.Context,
	client graphql.Client,
	mode string,
	logger *observability.CoreLogger,
) *ResumeBranch {
	return &ResumeBranch{ctx: ctx, client: client, mode: mode, logger: logger}
}

// UpdateForResume modifies run metadata for resuming.
//
// The metadata should be initialized as if creating a fresh run,
// specifically with Entity, Project and RunID fields set.
//
// On error, the metadata may have been partially modified
// and must be discarded.
func (rb *ResumeBranch) UpdateForResume(
	params *RunParams,
	config *runconfig.RunConfig,
) error {
	response, err := gql.RunResumeStatus(
		rb.ctx,
		rb.client,
		&params.Project,
		nullify.NilIfZero(params.Entity),
		params.RunID,
	)
	// if we get an error we are in an unknown state and we should raise an error
	if err != nil {
		info := &spb.ErrorInfo{
			Code: spb.ErrorInfo_COMMUNICATION,
			Message: fmt.Sprintf(
				"Failed to get resume status for run %s: %s",
				params.RunID, err),
		}
		return &BranchError{Err: err, Response: info}
	}

	data, runExists := runDataFromResponse(response)
	if !runExists {
		return rb.runDoesNotExistError(params.RunID)
	}

	if !rb.allowResume() {
		return rb.resumeNotAllowedError(params.RunID)
	}

	err = processResponse(params, config, data)
	if err != nil && rb.mustResume() {
		return rb.resumeFailedError(params.RunID, err)
	}

	return err
}

// runDataFromResponse checks if the run exists based on the response we get from the server
func runDataFromResponse(
	response *gql.RunResumeStatusResponse,
) (*gql.RunResumeStatusModelProjectBucketRun, bool) {
	// If response is nil, run doesn't exist yet
	if response == nil {
		return nil, false
	}

	// if response doesn't have a model, or the model doesn't have a bucket, the run doesn't exist
	// or the backend is not returning the expected data
	if response.GetModel() == nil || response.GetModel().GetBucket() == nil {
		return nil, false
	}

	// If bucket is non-nil but WandbConfig has no "t" key, the run exists but hasn't started
	// (e.g. a sweep run that was created ahead of time)
	bucket := response.GetModel().GetBucket()
	if bucket.GetWandbConfig() == nil {
		return nil, false
	}
	var cfg map[string]any
	if err := json.Unmarshal([]byte(*bucket.GetWandbConfig()), &cfg); err != nil {
		return nil, false
	}
	if _, ok := cfg["t"]; !ok {
		return nil, false
	}
	return bucket, true
}

func (rb *ResumeBranch) runDoesNotExistError(runID string) error {
	if !rb.mustResume() {
		return nil
	}

	// A strict resume requires the run to exist.
	info := &spb.ErrorInfo{
		Code: spb.ErrorInfo_USAGE,
		Message: fmt.Sprintf(
			"Run (%s) does not exist or has not been initialized, but your"+
				" `resume` setting requires an existing run to resume."+
				" Verify the run ID is correct."+
				" If you are starting a new run, omit `resume` in wandb.init()"+
				" or set `resume` or `WANDB_RESUME` to `allow` or `never`.",
			runID,
		),
	}
	err := errors.New("run does not exist")
	return &BranchError{Err: err, Response: info}
}

func (rb *ResumeBranch) allowResume() bool {
	return rb.mode != "never"
}

func (rb *ResumeBranch) mustResume() bool {
	return rb.mode == "must"
}

func (rb *ResumeBranch) resumeFailedError(runID string, err error) error {
	info := &spb.ErrorInfo{
		Code: spb.ErrorInfo_USAGE,
		Message: fmt.Sprintf(
			"The run (%s) failed to resume, and the `resume` argument is set to 'must'.",
			runID,
		),
	}
	err = fmt.Errorf("could not resume run: %s", err)
	return &BranchError{Err: err, Response: info}
}

func (rb *ResumeBranch) resumeNotAllowedError(runID string) error {
	info := &spb.ErrorInfo{
		Code: spb.ErrorInfo_USAGE,
		Message: fmt.Sprintf(
			"Run (%s) already exists, but your `resume` setting does not allow"+
				" resuming an existing run."+
				" Verify the run ID is correct."+
				" To resume this run, set `resume` in wandb.init() or `WANDB_RESUME`"+
				" to `allow` or `must`."+
				" To start a new run, use a different run ID.",
			runID,
		),
	}
	err := errors.New("run exists but cannot resume")
	return &BranchError{Err: err, Response: info}
}

// processResponse updates run metadata based on the server response.
//
//gocyclo:ignore
func processResponse(
	params *RunParams,
	config *runconfig.RunConfig,
	data *gql.RunResumeStatusModelProjectBucketRun,
) error {
	// Get Config information
	if oldConfig, err := processConfigResume(data.GetConfig()); err != nil {
		return err
	} else if oldConfig != nil {
		config.MergeResumedConfig(oldConfig)
	}

	if filestreamOffset, err := processAllOffsets(
		data.GetHistoryLineCount(),
		data.GetEventsLineCount(),
		data.GetLogLineCount(),
	); err != nil {
		return err
	} else {
		params.FileStreamOffset = filestreamOffset
	}

	// extract runtime from the events tail if it exists we will use the maximal
	// value of runtime that we find
	if events, err := processEventsTail(data.GetEventsTail()); err != nil {
		return err
	} else if events != nil {
		if runtime, ok := events["_runtime"]; ok {
			params.Runtime = max(
				extractRuntime(runtime),
				params.Runtime,
			)
		}
	}

	// Get Summary information
	if summary, err := processSummary(data.GetSummaryMetrics()); err != nil {
		return err
	} else if summary != nil {
		if params.Summary == nil {
			params.Summary = summary
		} else {
			maps.Copy(params.Summary, summary)
		}

		if step, ok := summary["_step"]; ok {
			// if we are resuming, we need to update the starting step
			// to be the next step after the last step we ran
			if x, ok := step.(int64); ok {
				params.StartingStep = x
			}
		}

		// if summary["_wandb"]["runtime"] exists it takes precedence over
		// summary["_runtime"] for the runtime value
		switch x := params.Summary["_wandb"].(type) {
		case map[string]any:
			if runtime, ok := x["runtime"]; ok {
				params.Runtime = max(
					extractRuntime(runtime),
					params.Runtime,
				)
			}
		default:
			if runtime, ok := params.Summary["_runtime"]; ok {
				params.Runtime = max(
					extractRuntime(runtime),
					params.Runtime,
				)
			}
		}
	}

	// TODO: do we need both history and summary? is it a legacy from old
	// versions of the backend?
	if history, err := processHistory(data.GetHistoryTail()); err != nil {
		return err
	} else if history != nil {
		if step, ok := history["_step"]; ok {
			// if we are resuming, we need to update the starting step
			// to be the next step after the last step we ran
			if x, ok := step.(int64); ok {
				params.StartingStep = x
			}
		}

		if runtime, ok := history["_runtime"]; ok {
			params.Runtime = max(
				extractRuntime(runtime),
				params.Runtime,
			)
		}
	}

	// if we are resuming, we need to update the starting step
	if params.FileStreamOffset[filestream.HistoryChunk] > 0 {
		params.StartingStep += 1
	}

	// If the user provided tags when initializing, use them. Otherwise,
	// initialize to the previous run's tags.
	if len(params.Tags) == 0 {
		params.Tags = data.GetTags()
	}

	if params.Notes == "" && data.GetNotes() != nil {
		params.Notes = *data.GetNotes()
	}

	// Get GQL ID, required for auth checks around writing to a run
	params.StorageID = data.GetId()

	params.Resumed = true

	return nil
}

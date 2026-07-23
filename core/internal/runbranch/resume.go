package runbranch

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"math"

	"github.com/Khan/genqlient/graphql"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/nullify"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type ResumeBranch struct {
	ctx      context.Context
	logger   *observability.CoreLogger
	client   graphql.Client
	resume   bool
	settings *settings.Settings
}

// NewResumeBranch creates a ResumeBranch from persisted resume intent and the
// current run settings.
func NewResumeBranch(
	ctx context.Context,
	logger *observability.CoreLogger,
	client graphql.Client,
	resume bool,
	resumeSettings *settings.Settings,
) *ResumeBranch {
	return &ResumeBranch{
		ctx:      ctx,
		logger:   logger,
		client:   client,
		resume:   resume,
		settings: resumeSettings,
	}
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

	var data *gql.RunResumeStatusModelProjectBucketRun
	if runExists(response) {
		data = response.GetModel().GetBucket()
	}

	// Starting a new run is valid when resuming is disabled, or when a
	// lenient resume mode allows creating a missing run.
	if data == nil && (!rb.resume || rb.allowMissingRun()) {
		return nil
	}

	// A strict resume requires the run to exist.
	if data == nil {
		info := &spb.ErrorInfo{
			Code: spb.ErrorInfo_USAGE,
			Message: fmt.Sprintf(
				"Run (%s) does not exist or has not been initialized, but your "+
					"`resume` setting requires an existing run to resume. "+
					"Verify the run ID is correct. "+
					"If you are starting a new run, omit `resume` in wandb.init() "+
					"or set `resume` or `WANDB_RESUME` to `allow` or `never`.",
				params.RunID,
			),
		}
		err = errors.New("no data but must resume")
		return &BranchError{Err: err, Response: info}
	}

	// if we have data and we are in a never resume mode we need to return an
	// error because we are not allowed to resume
	if data != nil && !rb.resume {
		info := &spb.ErrorInfo{
			Code: spb.ErrorInfo_USAGE,
			Message: fmt.Sprintf(
				"Run (%s) already exists, but your `resume` setting does not allow "+
					"resuming an existing run. "+
					"Verify the run ID is correct. "+
					"To resume this run, set `resume` in wandb.init() or `WANDB_RESUME` "+
					"to `allow` or `must`. "+
					"To start a new run, use a different run ID.",
				params.RunID,
			),
		}
		err = errors.New("data but cannot resume")
		return &BranchError{Err: err, Response: info}
	}

	// If the run exists and resuming is enabled, restore its metadata.
	if data != nil {
		err := processResponse(params, config, data, rb.logger)

		if err != nil && !rb.allowMissingRun() {
			info := &spb.ErrorInfo{
				Code: spb.ErrorInfo_USAGE,
				Message: fmt.Sprintf(
					"The run (%s) failed to resume, and the `resume` argument is set to 'must'.",
					params.RunID,
				),
			}
			err = fmt.Errorf("could not resume run: %s", err)
			return &BranchError{Err: err, Response: info}
		}

		return err
	}

	return nil
}

func (rb *ResumeBranch) allowMissingRun() bool {
	if rb.settings == nil {
		return false
	}

	mode := rb.settings.GetResume()
	return mode == "allow" || mode == "auto" || mode == "never"
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

// processResponse updates run metadata based on the server response.
//
//gocyclo:ignore
func processResponse(
	params *RunParams,
	config *runconfig.RunConfig,
	data *gql.RunResumeStatusModelProjectBucketRun,
	logger *observability.CoreLogger,
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
			params.Runtime = int32(
				math.Max(
					extractRuntime(runtime),
					float64(params.Runtime),
				))
		}
	}

	// The highest explicit _step reported by the summary or the history
	// tail, or -1 if neither reports one.
	lastStep := int64(-1)

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
			if x, ok := step.(int64); ok {
				lastStep = max(lastStep, x)
			}
		}

		// if summary["_wandb"]["runtime"] exists it takes precedence over
		// summary["_runtime"] for the runtime value
		switch x := params.Summary["_wandb"].(type) {
		case map[string]any:
			if runtime, ok := x["runtime"]; ok {
				params.Runtime = int32(
					math.Max(
						extractRuntime(runtime),
						float64(params.Runtime),
					))
			}
		default:
			if runtime, ok := params.Summary["_runtime"]; ok {
				params.Runtime = int32(
					math.Max(
						extractRuntime(runtime),
						float64(params.Runtime),
					))
			}
		}
	}

	// TODO: do we need both history and summary? is it a legacy from old
	// versions of the backend?
	if history, err := processHistory(data.GetHistoryTail()); err != nil {
		return err
	} else if history != nil {
		if step, ok := history["_step"]; ok {
			if x, ok := step.(int64); ok {
				lastStep = max(lastStep, x)
			}
		}

		if runtime, ok := history["_runtime"]; ok {
			params.Runtime = int32(
				math.Max(
					extractRuntime(runtime),
					float64(params.Runtime),
				))
		}
	}

	// The number of history rows in the file stream.
	historyRowCount := int64(params.FileStreamOffset[filestream.HistoryChunk])

	// If the history row count the summary and history tail step, then they
	// must be stale, so use the history row count - 1 as a lower bound.
	// Note that this may still not be accurate if the run was logged at
	// sparse steps, so we warn the user.
	if lastStep >= 0 && historyRowCount > lastStep+1 {
		logger.Warn(
			"runbranch: resume: history row count exceeds the last "+
				"reported step + 1; the reported step is stale, using "+
				"the row count as the starting step",
			"historyRowCount", historyRowCount,
			"lastStep", lastStep,
		)
	}

	lastStep = max(lastStep, historyRowCount-1)
	params.StartingStep = lastStep + 1 // next step after the last reported step

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

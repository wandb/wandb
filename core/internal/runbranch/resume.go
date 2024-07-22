package runbranch

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/simplejsonext"
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

// GetUpdates updates the state based on the resume mode
// and the Run resume status we get from the server
func (r *ResumeBranch) GetUpdates(
	entity, project, runID string,
) (*RunParams, error) {

	response, err := gql.RunResumeStatus(
		r.ctx,
		r.client,
		&project,
		utils.NilIfZero(entity),
		runID,
	)

	// if we get an error we are in an unknown state and we should raise an error
	if err != nil {
		info := &service.ErrorInfo{
			Code:    service.ErrorInfo_COMMUNICATION,
			Message: fmt.Sprintf("Failed to get resume status for run %s: %s", runID, err),
		}
		return nil, &BranchError{Err: err, Response: info}
	}

	var data *gql.RunResumeStatusModelProjectBucketRun
	if response != nil && response.GetModel() != nil && response.GetModel().GetBucket() != nil {
		data = response.GetModel().GetBucket()
	}

	// if we are not in the resume mode MUST and we didn't get data, we can just
	// return without error
	if data == nil && r.mode != "must" {
		return nil, nil
	}

	// if we are in the resume mode MUST and we don't have data (the run is not initialized),
	// we need to return an error because we can't resume
	if data == nil && r.mode == "must" {
		info := &service.ErrorInfo{
			Code: service.ErrorInfo_USAGE,
			Message: fmt.Sprintf("You provided an invalid value for the `resume` argument."+
				" The value 'must' is not a valid option for resuming the run (%s) that has not been initialized."+
				" Please check your inputs and try again with a valid run ID."+
				" If you are trying to start a new run, please omit the `resume` argument or use `resume='allow'`.",
				runID),
		}
		err = errors.New("no data but must resume")
		return nil, &BranchError{Err: err, Response: info}
	}

	// if we have data and we are in a never resume mode we need to return an
	// error because we are not allowed to resume
	if data != nil && r.mode == "never" {
		info := &service.ErrorInfo{
			Code: service.ErrorInfo_USAGE,
			Message: fmt.Sprintf("You provided an invalid value for the `resume` argument."+
				"  The value 'never' is not a valid option for resuming a run (%s) that already exists."+
				"  Please check your inputs and try again with a valid value for the `resume` argument.",
				runID),
		}
		err = errors.New("data but cannot resume")
		return nil, &BranchError{Err: err, Response: info}
	}

	// if we have data and we are in the MUST or ALLOW resume mode, we can resume the run
	if data != nil && r.mode != "never" {
		update, err := extractRunState(data)
		if err != nil && r.mode == "must" {
			info := &service.ErrorInfo{
				Code: service.ErrorInfo_USAGE,
				Message: fmt.Sprintf("The run (%s) failed to resume, and the `resume` argument is set to 'must'.",
					runID),
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

// extractRunState extracts the run state from the data we get from the server
//
//gocyclo:ignore
func extractRunState(data *gql.RunResumeStatusModelProjectBucketRun) (*RunParams, error) {
	r := RunParams{FileStreamOffset: make(filestream.FileStreamOffsetMap)}

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

	// Get History information
	history := data.GetHistoryTail()
	if history == nil {
		return nil, errors.New("no history tail found in resume response")
	} else {
		// Since we just expect a list of strings, we unmarshal using the
		// standard JSON library.
		var histories []string
		if err := json.Unmarshal([]byte(*history), &histories); err != nil {
			return nil, err
		}

		if len(histories) > 0 {
			historyTail, err := simplejsonext.UnmarshalObjectString(histories[len(histories)-1])

			if err != nil {
				return nil, err
			}

			if step, ok := historyTail["_step"]; ok {
				// if we are resuming, we need to update the starting step
				// to be the next step after the last step we ran
				if x, ok := step.(int64); ok {
					r.startingStep = x
				}
			}

			if runtime, ok := historyTail["_runtime"]; ok {
				switch x := runtime.(type) {
				case int64:
					r.Runtime = int32(math.Max(float64(x), float64(r.Runtime)))
				case float64:
					r.Runtime = int32(math.Max(x, float64(r.Runtime)))
				}
			}
		}
	}

	// Get Summary information
	summary := data.GetSummaryMetrics()
	if summary == nil {
		return nil, errors.New("no summary metrics found in resume response")
	} else {
		// If we are unable to parse the summary, we should fail if resume is set to
		// must for any other case of resume status, it is fine to ignore it
		summaryVal, err := simplejsonext.UnmarshalString(*summary)
		if err != nil {
			return nil, err
		}

		switch x := summaryVal.(type) {
		case nil: // OK, summary is nil
		case map[string]any:
			r.summary = x
		default:
			return nil, fmt.Errorf("unexpected type %T for %s", x, *summary)
		}
	}

	// Get Config information
	config := data.GetConfig()
	if config == nil {
		return nil, errors.New("no config found in resume response")
	} else {
		// If we are unable to parse the config, we should fail if resume is set to
		// must for any other case of resume status, it is fine to ignore it
		cfgVal, err := simplejsonext.UnmarshalString(*config)
		if err != nil {
			return nil, fmt.Errorf("failed to unmarshal config: %s", err)
		}

		var cfg map[string]any
		switch x := cfgVal.(type) {
		case nil: // OK, cfg is nil
		case map[string]any:
			cfg = x
		default:
			return nil, fmt.Errorf(
				"sender: updateConfig: got type %T for %s",
				x, *config,
			)
		}

		if r.Config == nil {
			r.Config = make(map[string]any)
		}
		for key, value := range cfg {
			valueDict, ok := value.(map[string]any)
			if !ok {
				return nil, fmt.Errorf("unexpected type %T for %s", value, key)
			} else if val, ok := valueDict["value"]; ok {
				r.Config[key] = val
			}
		}
	}

	// Get Events (system metrics) information
	events := data.GetEventsTail()
	if events == nil {
		return nil, errors.New("no events tail found in resume response")
	} else {
		// Since we just expect a list of strings, we unmarshal using the
		// standard JSON library.
		var eventsTail []string
		if err := json.Unmarshal([]byte(*events), &eventsTail); err != nil {
			return nil, err
		}

		if len(eventsTail) > 0 {
			eventTail, err := simplejsonext.UnmarshalObjectString(eventsTail[len(eventsTail)-1])
			if err != nil {
				return nil, err
			}

			if runtime, ok := eventTail["_runtime"]; ok {
				switch x := runtime.(type) {
				case int64:
					r.Runtime = int32(math.Max(float64(x), float64(r.Runtime)))
				case float64:
					r.Runtime = int32(math.Max(x, float64(r.Runtime)))
				}
			}
		}
	}

	// Get Tags information
	r.Tags = data.GetTags()

	// if we are resuming, we need to update the starting step
	if r.FileStreamOffset[filestream.HistoryChunk] > 0 {
		r.startingStep += 1
	}
	r.Resumed = true

	return &r, nil
}

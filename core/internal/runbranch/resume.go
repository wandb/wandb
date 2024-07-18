package runbranch

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/core/pkg/utils"
)

func (r *State) updateRunResumeMode(run *service.RunRecord) {

	// if we are resuming, we need to update the starting step
	if r.FileStreamOffset[filestream.HistoryChunk] > 0 {
		run.StartingStep = r.startingStep + 1
	}

	// r.RunRecord.StartTime = r.startTime

	run.Runtime = r.runtime

	// update the tags
	run.Tags = append(run.Tags, r.Tags...)

	// update the config
	config := service.ConfigRecord{}
	for key, value := range r.Config {
		valueJson, _ := simplejsonext.MarshalToString(value)
		config.Update = append(config.Update, &service.ConfigItem{
			Key:       key,
			ValueJson: valueJson,
		})
	}
	run.Config = &config

	// update the summary
	summary := service.SummaryRecord{}
	for key, value := range r.summary {
		valueJson, _ := simplejsonext.MarshalToString(value)
		summary.Update = append(summary.Update, &service.SummaryItem{
			Key:       key,
			ValueJson: valueJson,
		})
	}
	run.Summary = &summary

}

func (r *State) updateStateResumeMode(branching *BranchingState) (*service.ErrorInfo, error) {

	response, err := gql.RunResumeStatus(
		r.ctx,
		r.client,
		&r.Project,
		utils.NilIfZero(r.Entity),
		r.RunID,
	)
	// TODO: how to handle this error?
	if err != nil {
		return nil, err
	}

	var data *gql.RunResumeStatusModelProjectBucketRun
	if response != nil && response.GetModel() != nil && response.GetModel().GetBucket() != nil {
		data = response.GetModel().GetBucket()
	}

	// if we are not in a must resume mode and we don't have data we can just
	// return without error
	if data == nil && branching.Mode != "must" {
		return nil, nil
	}

	// if we are in a must resume mode and we don't have data we need to return
	// an error because we can't resume
	if data == nil && branching.Mode == "must" {
		info := &service.ErrorInfo{
			Code: service.ErrorInfo_USAGE,
			Message: fmt.Sprintf("You provided an invalid value for the `resume` argument."+
				" The value 'must' is not a valid option for resuming a run (%s) that has not been initialized."+
				" Please check your inputs and try again with a valid run ID."+
				" If you are trying to start a new run, please omit the `resume` argument or use `resume='allow'`.",
				r.RunID),
		}
		return info, errors.New("no data but must resume")
	}

	// if we have data and we are in a never resume mode we need to return an
	// error because we are not allowed to resume
	if data != nil && branching.Mode == "never" {
		info := &service.ErrorInfo{
			Code: service.ErrorInfo_USAGE,
			Message: fmt.Sprintf("You provided an invalid value for the `resume` argument."+
				"  The value 'never' is not a valid option for resuming a run (%s) that already exists."+
				"  Please check your inputs and try again with a valid value for the `resume` argument.",
				r.RunID),
		}
		return info, errors.New("run cannot be resumed")
	}

	// if we have data and we are in a must or allow resume mode we can resume
	// the run
	if data != nil && branching.Mode != "never" {
		err := r.resume(data)
		if err != nil && branching.Mode == "must" {
			info := &service.ErrorInfo{
				Code: service.ErrorInfo_USAGE,
				Message: fmt.Sprintf("The run (%s) failed to resume, and the `resume` argument is set to 'must'.",
					r.RunID),
			}
			return info, fmt.Errorf("could not resume run: %s", err)
		}
		return nil, err
	}

	return nil, nil
}

func (r *State) resume(data *gql.RunResumeStatusModelProjectBucketRun) error {
	// update the file stream offsets with the data from the server
	r.FileStreamOffset[filestream.HistoryChunk] = *data.GetHistoryLineCount()
	r.FileStreamOffset[filestream.EventsChunk] = *data.GetEventsLineCount()
	r.FileStreamOffset[filestream.OutputChunk] = *data.GetLogLineCount()

	var errs []error

	// Get History information
	history := data.GetHistoryTail()
	if history == nil {
		err := errors.New("no history tail found in resume response")
		errs = append(errs, err)
	} else {
		err := r.resumeHistory(history)
		if err != nil {
			errs = append(errs, err)
		}
	}

	// Get Summary information
	summary := data.GetSummaryMetrics()
	if summary != nil {
		err := errors.New("no summary metrics found in resume response")
		errs = append(errs, err)
	} else {
		err := r.resumeSummary(summary)
		if err != nil {
			errs = append(errs, err)
		}
	}

	// Get Config information
	config := data.GetConfig()
	if config != nil {
		err := errors.New("no config found in resume response")
		errs = append(errs, err)
	} else {
		err := r.resumeConfig(config)
		if err != nil {
			errs = append(errs, err)
		}
	}

	// Get Events (system metrics) information
	events := data.GetEventsTail()
	if events != nil {
		err := errors.New("no events tail found in resume response")
		errs = append(errs, err)
	} else {
		err := r.resumeEvents(events)
		if err != nil {
			errs = append(errs, err)
		}
	}

	// Get Tags information
	r.Tags = data.GetTags()

	return errors.Join(errs...)
}

func (r *State) resumeHistory(history *string) error {

	// Since we just expect a list of strings, we unmarshal using the
	// standard JSON library.
	var histories []string
	if err := json.Unmarshal([]byte(*history), &histories); err != nil {
		return err
	}

	if len(histories) == 0 {
		return nil
	}

	historyTail, err := simplejsonext.UnmarshalObjectString(histories[0])
	if err != nil {
		return err
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
			r.runtime = int32(math.Max(float64(x), float64(r.runtime)))
		case float64:
			r.runtime = int32(math.Max(x, float64(r.runtime)))
		}
	}

	fmt.Println(">>>History", historyTail)
	return nil
}

func (r *State) resumeEvents(event *string) error {

	// Since we just expect a list of strings, we unmarshal using the
	// standard JSON library.
	var events []string
	if err := json.Unmarshal([]byte(*event), &events); err != nil {
		return err
	}

	if len(events) == 0 {
		return nil
	}

	eventTail, err := simplejsonext.UnmarshalObjectString(events[0])
	if err != nil {
		return err
	}

	if runtime, ok := eventTail["_runtime"]; ok {
		switch x := runtime.(type) {
		case int64:
			r.runtime = int32(math.Max(float64(x), float64(r.runtime)))
		case float64:
			r.runtime = int32(math.Max(x, float64(r.runtime)))
		}
	}

	fmt.Println(">>>Events", eventTail)
	return nil
}

func (r *State) resumeSummary(summary *string) error {
	// If we are unable to parse the summary, we should fail if resume is set to
	// must for any other case of resume status, it is fine to ignore it
	summaryVal, err := simplejsonext.UnmarshalString(*summary)
	if err != nil {
		return err
	}

	switch x := summaryVal.(type) {
	case nil: // OK, summary is nil
	case map[string]any:
		r.summary = x
	default:
		return fmt.Errorf("unexpected type %T for %s", x, *summary)
	}

	return nil
}

func (r *State) resumeConfig(config *string) error {

	// If we are unable to parse the config, we should fail if resume is set to
	// must for any other case of resume status, it is fine to ignore it
	cfgVal, err := simplejsonext.UnmarshalString(*config)
	if err != nil {
		return fmt.Errorf("failed to unmarshal config: %s", err)
	}

	var cfg map[string]any
	switch x := cfgVal.(type) {
	case nil: // OK, cfg is nil
	case map[string]any:
		cfg = x
	default:
		return fmt.Errorf(
			"sender: updateConfig: got type %T for %s",
			x, *config,
		)
	}

	var errs []error
	r.Config = make(map[string]any)
	for key, value := range cfg {
		valueDict, ok := value.(map[string]any)

		if !ok {
			err := fmt.Errorf("unexpected type %T for %s", value, key)
			errs = append(errs, err)
			continue
		} else if val, ok := valueDict["value"]; ok {
			r.Config[key] = val
		}
	}
	return errors.Join(errs...)
}

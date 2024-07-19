package runbranching

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/pkg/service"
)

type Bucket = gql.RunResumeStatusModelProjectBucketRun

type Mode uint8

const (
	NoResume Mode = iota
	Must
	Allow
	Never
)

func ResumeMode(mode string) Mode {
	switch mode {
	case "must":
		return Must
	case "allow":
		return Allow
	case "never":
		return Never
	default:
		return NoResume
	}
}

func RunHasStarted(bucket *Bucket) bool {
	// If bucket is nil, run doesn't exist yet
	// If bucket is non-nil but WandbConfig has no "t" key, the run exists but hasn't started
	// (e.g. a sweep run that was created ahead of time)
	return bucket != nil && bucket.WandbConfig != nil && strings.Contains(*bucket.WandbConfig, `"t":`)
}

func (r *State) UpdateResume(mode Mode, data *gql.RunResumeStatusResponse) (*service.RunUpdateResult, error) {

	var bucket *Bucket
	if data.GetModel() != nil && data.GetModel().GetBucket() != nil {
		bucket = data.GetModel().GetBucket()
	}

	// If we get that the run is not a resume run, we should fail if resume is set to must
	// for any other case of resume status, it is fine to ignore it
	// If we get that the run is a resume run, we should fail if resume is set to never
	// for any other case of resume status, we should continue to process the resume response
	switch {
	case !RunHasStarted(bucket) && mode != Must:
		return nil, nil
	case !RunHasStarted(bucket) && mode == Must:
		message := fmt.Sprintf(
			"You provided an invalid value for the `resume` argument."+
				" The value 'must' is not a valid option for resuming a run"+
				" (%s/%s) that has never been started. Please check your inputs and"+
				" try again with a valid value for the `resume` argument.\n"+
				"If you are trying to start a new run, please omit the"+
				" `resume` argument or use `resume='allow'`",
			r.RunRecord.Project, r.RunRecord.RunId)
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Message: message,
				Code:    service.ErrorInfo_USAGE,
			}}
		err := fmt.Errorf(
			"sender: Update: resume is 'must' for a run that does not exist")
		return result, err
	case mode == Never && RunHasStarted(bucket):
		message := fmt.Sprintf(
			"You provided an invalid value for the `resume` argument."+
				" The value 'never' is not a valid option for resuming a"+
				" run (%s/%s) that already exists. Please check your inputs"+
				" and try again with a valid value for the `resume` argument.\n",
			r.RunRecord.Project, r.RunRecord.RunId)
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Message: message,
				Code:    service.ErrorInfo_USAGE,
			}}
		err := fmt.Errorf(
			"sender: Update: resume is 'never' for a run that already exists")
		return result, err
	default:
		if err := r.updateResume(bucket); err != nil && mode == Must {
			message := fmt.Sprintf(
				"The run (%s/%s) failed to resume, and the `resume` argument"+
					" was set to 'must'. Please check your inputs and try again"+
					" with a valid value for the `resume` argument.\n",
				r.RunRecord.Project, r.RunRecord.RunId)
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: message,
					Code:    service.ErrorInfo_UNKNOWN,
				},
			}
			return result, err
		}
		r.Mode = ModeResume
		return nil, nil
	}
}

func (r *State) updateResume(bucket *Bucket) error {
	errs := make([]error, 0)

	r.AddOffset(filestream.HistoryChunk, *bucket.GetHistoryLineCount())
	if err := r.updateResumeHistory(bucket); err != nil {
		errs = append(errs, err)
	}

	r.AddOffset(filestream.EventsChunk, *bucket.GetEventsLineCount())

	if err := r.updateResumeSummary(bucket); err != nil {
		errs = append(errs, err)
	}

	r.AddOffset(filestream.OutputChunk, *bucket.GetLogLineCount())
	if err := r.updateResumeConfig(bucket); err != nil {
		errs = append(errs, err)
	}

	if err := r.updateResumeTags(bucket); err != nil {
		errs = append(errs, err)
	}

	return errors.Join(errs...)
}

func (r *State) updateResumeHistory(bucket *Bucket) error {

	resumed := bucket.GetHistoryTail()
	if resumed == nil {
		err := fmt.Errorf(
			"sender: updateHistory: no history tail found in resume response")
		return err
	}

	// Since we just expect a list of strings, we unmarshal using the
	// standard JSON library.
	var history []string
	if err := json.Unmarshal([]byte(*resumed), &history); err != nil {
		return fmt.Errorf(
			"sender: updateHistory: failed to unmarshal history: %v",
			err,
		)
	}

	if len(history) == 0 {
		return nil
	}

	historyTail, err := simplejsonext.UnmarshalObjectString(history[0])
	if err != nil {
		err = fmt.Errorf(
			"sender: updateHistory: failed to unmarshal history tail map: %s",
			err)
		return err
	}

	step, ok := historyTail["_step"]
	if ok {
		// if we are resuming, we need to update the starting step
		// to be the next step after the last step we ran
		if x, ok := step.(int64); ok {
			if x > 0 || r.GetFileStreamOffset()[filestream.HistoryChunk] > 0 {
				r.RunRecord.StartingStep = x + 1
			}
		}
	}

	runtime, ok := historyTail["_runtime"]
	if ok {
		switch x := runtime.(type) {
		case int64:
			r.RunRecord.Runtime = int32(x)
		case float64:
			r.RunRecord.Runtime = int32(x)
		}
	}

	return nil
}

func (r *State) updateResumeSummary(bucket *Bucket) error {

	resumed := bucket.GetSummaryMetrics()
	if resumed == nil {
		return errors.New(
			"sender: updateSummary: no summary metrics found in resume response",
		)
	}

	// If we are unable to parse the summary, we should fail if resume is set to
	// must for any other case of resume status, it is fine to ignore it
	summaryVal, err := simplejsonext.UnmarshalString(*resumed)
	if err != nil {
		return fmt.Errorf(
			"sender: updateSummary: failed to unmarshal summary metrics: %s",
			err,
		)
	}

	var summary map[string]any
	switch x := summaryVal.(type) {
	case nil: // OK, summary is nil
	case map[string]any:
		summary = x
	default:
		return fmt.Errorf(
			"sender: updateSummary: got type %T for %s",
			x, *resumed,
		)
	}

	record := service.SummaryRecord{}
	for key, value := range summary {
		valueJson, _ := simplejsonext.MarshalToString(value)
		record.Update = append(record.Update, &service.SummaryItem{
			Key:       key,
			ValueJson: valueJson,
		})
	}
	r.RunRecord.Summary = &record
	return nil
}

// Merges the original run's config into the current config.
func (r *State) updateResumeConfig(bucket *Bucket) error {
	resumed := bucket.GetConfig()
	if resumed == nil {
		return errors.New(
			"sender: updateConfig: no config found in resume response",
		)
	}

	// If we are unable to parse the config, we should fail if resume is set to
	// must for any other case of resume status, it is fine to ignore it
	cfgVal, err := simplejsonext.UnmarshalString(*resumed)
	if err != nil {
		return fmt.Errorf(
			"sender: updateConfig: failed to unmarshal config: %s",
			err,
		)
	}

	var cfg map[string]any
	switch x := cfgVal.(type) {
	case nil: // OK, cfg is nil
	case map[string]any:
		cfg = x
	default:
		return fmt.Errorf(
			"sender: updateConfig: got type %T for %s",
			x, *resumed,
		)
	}

	var errs []error
	deserializedConfig := make(map[string]any)
	for key, value := range cfg {
		valueDict, ok := value.(map[string]any)

		if !ok {
			errs = append(errs, fmt.Errorf(
				"sender: updateConfig: config value for '%v' is not a map[string]any",
				key,
			))
		} else if val, ok := valueDict["value"]; ok {
			deserializedConfig[key] = val
		}
	}

	r.Config.MergeResumedConfig(deserializedConfig)
	return errors.Join(errs...)
}

func (r *State) updateResumeTags(bucket *Bucket) error {
	resumed := bucket.GetTags()
	if resumed == nil {
		return nil
	}
	// handle tags
	// - when resuming a run, its tags will be overwritten by the tags
	//   passed to `wandb.init()`.
	// - to add tags to a resumed run without overwriting its existing tags
	//   use `run.tags += ["new_tag"]` after `wandb.init()`.
	if r.RunRecord.Tags == nil {
		r.RunRecord.Tags = append(r.RunRecord.Tags, resumed...)
	}
	return nil
}

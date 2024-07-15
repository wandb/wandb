package runresume

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

type Bucket = gql.RunResumeStatusModelProjectBucketRun

type Mode uint8

const (
	None Mode = iota
	Must
	Allow
	Never
)

type State struct {
	resume           Mode
	FileStreamOffset filestream.FileStreamOffsetMap
	logger           *observability.CoreLogger
}

func ResumeMode(mode string) Mode {
	switch mode {
	case "must":
		return Must
	case "allow":
		return Allow
	case "never":
		return Never
	default:
		return None
	}
}

func NewResumeState(logger *observability.CoreLogger, mode Mode) *State {
	return &State{logger: logger, resume: mode}
}

func (r *State) GetFileStreamOffset() filestream.FileStreamOffsetMap {
	if r == nil {
		return nil
	}
	return r.FileStreamOffset
}

func (r *State) AddOffset(key filestream.ChunkTypeEnum, offset int) {
	if r.FileStreamOffset == nil {
		r.FileStreamOffset = make(filestream.FileStreamOffsetMap)
	}
	r.FileStreamOffset[key] = offset
}

func RunHasStarted(bucket *Bucket) bool {
	// If bucket is nil, run doesn't exist yet
	// If bucket is non-nil but WandbConfig has no "t" key, the run exists but hasn't started
	// (e.g. a sweep run that was created ahead of time)
	return bucket != nil && bucket.WandbConfig != nil && strings.Contains(*bucket.WandbConfig, `"t":`)
}

func (r *State) Update(
	data *gql.RunResumeStatusResponse,
	run *service.RunRecord,
	config *runconfig.RunConfig,
) (*service.RunUpdateResult, error) {

	var bucket *Bucket
	if data.GetModel() != nil && data.GetModel().GetBucket() != nil {
		bucket = data.GetModel().GetBucket()
	}

	// If we get that the run is not a resume run, we should fail if resume is set to must
	// for any other case of resume status, it is fine to ignore it
	// If we get that the run is a resume run, we should fail if resume is set to never
	// for any other case of resume status, we should continue to process the resume response
	switch {
	case !RunHasStarted(bucket) && r.resume != Must:
		return nil, nil
	case !RunHasStarted(bucket) && r.resume == Must:
		message := fmt.Sprintf(
			"You provided an invalid value for the `resume` argument."+
				" The value 'must' is not a valid option for resuming a run"+
				" (%s/%s) that has never been started. Please check your inputs and"+
				" try again with a valid value for the `resume` argument.\n"+
				"If you are trying to start a new run, please omit the"+
				" `resume` argument or use `resume='allow'`",
			run.Project, run.RunId)
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Message: message,
				Code:    service.ErrorInfo_USAGE,
			}}
		err := fmt.Errorf(
			"sender: Update: resume is 'must' for a run that does not exist")
		return result, err
	case r.resume == Never && RunHasStarted(bucket):
		message := fmt.Sprintf(
			"You provided an invalid value for the `resume` argument."+
				" The value 'never' is not a valid option for resuming a"+
				" run (%s/%s) that already exists. Please check your inputs"+
				" and try again with a valid value for the `resume` argument.\n",
			run.Project, run.RunId)
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Message: message,
				Code:    service.ErrorInfo_USAGE,
			}}
		err := fmt.Errorf(
			"sender: Update: resume is 'never' for a run that already exists")
		return result, err
	default:
		if err := r.update(bucket, run, config); err != nil && r.resume == Must {
			message := fmt.Sprintf(
				"The run (%s/%s) failed to resume, and the `resume` argument"+
					" was set to 'must'. Please check your inputs and try again"+
					" with a valid value for the `resume` argument.\n",
				run.Project, run.RunId)
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: message,
					Code:    service.ErrorInfo_UNKNOWN,
				},
			}
			return result, err
		}
		run.Resumed = true
		return nil, nil
	}
}

func (r *State) update(bucket *Bucket, run *service.RunRecord, config *runconfig.RunConfig) error {
	errs := make([]error, 0)

	r.AddOffset(filestream.HistoryChunk, *bucket.GetHistoryLineCount())
	if err := r.updateHistory(run, bucket); err != nil {
		r.logger.Error(err.Error())
		errs = append(errs, err)
	}

	r.AddOffset(filestream.EventsChunk, *bucket.GetEventsLineCount())

	if err := r.updateSummary(run, bucket); err != nil {
		r.logger.Error(err.Error())
		errs = append(errs, err)
	}

	r.AddOffset(filestream.OutputChunk, *bucket.GetLogLineCount())
	if err := r.updateConfig(bucket, config); err != nil {
		r.logger.Error(err.Error())
		errs = append(errs, err)
	}

	if err := r.updateTags(run, bucket); err != nil {
		r.logger.Error(err.Error())
		errs = append(errs, err)
	}

	if len(errs) > 0 {
		return errors.Join(errs...)
	}

	return nil
}

func (r *State) updateHistory(run *service.RunRecord, bucket *Bucket) error {

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
				run.StartingStep = x + 1
			}
		}
	}

	runtime, ok := historyTail["_runtime"]
	if ok {
		switch x := runtime.(type) {
		case int64:
			run.Runtime = int32(x)
		case float64:
			run.Runtime = int32(x)
		}
	}

	return nil
}

func (r *State) updateSummary(run *service.RunRecord, bucket *Bucket) error {

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
	run.Summary = &record
	return nil
}

// Merges the original run's config into the current config.
func (r *State) updateConfig(
	bucket *Bucket,
	config *runconfig.RunConfig,
) error {
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

	deserializedConfig := make(map[string]any)
	for key, value := range cfg {
		valueDict, ok := value.(map[string]any)

		if !ok {
			r.logger.Error(
				fmt.Sprintf(
					"sender: updateConfig: config value for '%v'"+
						" is not a map[string]any",
					key,
				),
			)
		} else if val, ok := valueDict["value"]; ok {
			deserializedConfig[key] = val
		}
	}

	config.MergeResumedConfig(deserializedConfig)
	return nil
}

func (r *State) updateTags(run *service.RunRecord, bucket *Bucket) error {
	resumed := bucket.GetTags()
	if resumed == nil {
		return nil
	}
	// handle tags
	// - when resuming a run, its tags will be overwritten by the tags
	//   passed to `wandb.init()`.
	// - to add tags to a resumed run without overwriting its existing tags
	//   use `run.tags += ["new_tag"]` after `wandb.init()`.
	if run.Tags == nil {
		run.Tags = append(run.Tags, resumed...)
	}
	return nil
}

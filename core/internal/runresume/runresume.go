package runresume

import (
	"fmt"
	"strings"

	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/pathtree"
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
	var isErr bool

	r.AddOffset(filestream.HistoryChunk, *bucket.GetHistoryLineCount())
	if err := r.updateHistory(run, bucket); err != nil {
		r.logger.Error(err.Error())
		isErr = true
	}

	r.AddOffset(filestream.EventsChunk, *bucket.GetEventsLineCount())

	if err := r.updateSummary(run, bucket); err != nil {
		r.logger.Error(err.Error())
		isErr = true
	}

	r.AddOffset(filestream.OutputChunk, *bucket.GetLogLineCount())
	if err := r.updateConfig(bucket, config); err != nil {
		r.logger.Error(err.Error())
		isErr = true
	}

	if err := r.updateTags(run, bucket); err != nil {
		r.logger.Error(err.Error())
		isErr = true
	}

	if isErr {
		err := fmt.Errorf("sender: update: failed to update resume state")
		return err
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

	historyAny, err := simplejsonext.UnmarshalString(*resumed)
	history, ok := historyAny.([]string)
	if err != nil || !ok {
		err = fmt.Errorf(
			"sender: updateHistory: failed to unmarshal history tail: %s", err)
		return err
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

	if step, ok := historyTail["_step"].(float64); ok {
		// if we are resuming, we need to update the starting step
		// to be the next step after the last step we ran
		if step > 0 || r.GetFileStreamOffset()[filestream.HistoryChunk] > 0 {
			run.StartingStep = int64(step) + 1
		}
	}

	if runtime, ok := historyTail["_runtime"].(float64); ok {
		run.Runtime = int32(runtime)
	}

	return nil
}

func (r *State) updateSummary(run *service.RunRecord, bucket *Bucket) error {

	resumed := bucket.GetSummaryMetrics()
	if resumed == nil {
		err := fmt.Errorf(
			"sender: updateSummary: no summary metrics found in resume response")
		r.logger.Error(err.Error())
		return err
	}

	// If we are unable to parse the summary, we should fail if resume is set to
	// must for any other case of resume status, it is fine to ignore it
	summary, err := simplejsonext.UnmarshalObjectString(*resumed)
	if err != nil {
		err = fmt.Errorf(
			"sender: updateSummary: failed to unmarshal summary metrics: %s",
			err)
		return err
	}

	record := service.SummaryRecord{}
	for key, value := range summary {
		valueJson, _ := simplejsonext.Marshal(value)
		record.Update = append(record.Update, &service.SummaryItem{
			Key:       key,
			ValueJson: string(valueJson),
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
		err := fmt.Errorf("sender: updateConfig: no config found in resume response")
		return err
	}

	// If we are unable to parse the config, we should fail if resume is set to
	// must for any other case of resume status, it is fine to ignore it
	cfg, err := simplejsonext.UnmarshalObjectString(*resumed)
	if err != nil {
		err = fmt.Errorf(
			"sender: updateConfig: failed to unmarshal config: %s", err)
		return err
	}

	deserializedConfig := make(pathtree.TreeData)
	for key, value := range cfg {
		valueDict, ok := value.(map[string]interface{})

		if !ok {
			r.logger.Error(
				fmt.Sprintf(
					"sender: updateConfig: config value for '%v'"+
						" is not a map[string]interface{}",
					key,
				),
			)
		} else if val, ok := valueDict["value"]; ok {
			deserializedConfig[key] = val
		}
	}

	err = config.MergeResumedConfig(deserializedConfig)
	if err != nil {
		r.logger.Error(
			fmt.Sprintf(
				"sender: updateConfig: failed to merge"+
					" resumed config: %s",
				err,
			),
		)
	}
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

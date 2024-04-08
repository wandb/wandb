package server

import (
	"fmt"

	"github.com/segmentio/encoding/json"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/runconfig"
	fs "github.com/wandb/wandb/core/pkg/filestream"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

type Bucket = gql.RunResumeStatusModelProjectBucketRun

type ResumeMode uint8

const (
	None ResumeMode = iota
	Must
	Allow
	Never
)

type ResumeState struct {
	resume           ResumeMode
	FileStreamOffset fs.FileStreamOffsetMap
	logger           *observability.CoreLogger
}

func resumeMode(mode string) ResumeMode {
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

func NewResumeState(logger *observability.CoreLogger, mode string) *ResumeState {
	return &ResumeState{logger: logger, resume: resumeMode(mode)}
}

func (r *ResumeState) GetFileStreamOffset() fs.FileStreamOffsetMap {
	if r == nil {
		return nil
	}
	return r.FileStreamOffset
}

func (r *ResumeState) AddOffset(key fs.ChunkTypeEnum, offset int) {
	if r.FileStreamOffset == nil {
		r.FileStreamOffset = make(fs.FileStreamOffsetMap)
	}
	r.FileStreamOffset[key] = offset
}

func (r *ResumeState) Update(
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
	case bucket == nil && r.resume != Must:
		return nil, nil
	case bucket == nil && r.resume == Must:
		err := fmt.Errorf(("You provided an invalid value for the `resume` argument. " +
			"The value 'must' is not a valid option for resuming a run (%s/%s) that does not exist. " +
			"Please check your inputs and try again with a valid value for the `resume` argument.\n" +
			"If you are trying to start a new run, please omit the `resume` argument or use `resume='allow'`"),
			run.Project, run.RunId)
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Message: err.Error(),
				Code:    service.ErrorInfo_USAGE,
			}}
		return result, err
	case bucket != nil && r.resume == Never:
		err := fmt.Errorf("You provided an invalid value for the `resume` argument. "+
			"The value 'never' is not a valid option for resuming a run (%s/%s) that already exists. "+
			"Please check your inputs and try again with a valid value for the `resume` argument.\n", run.Project, run.RunId)
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Message: err.Error(),
				Code:    service.ErrorInfo_USAGE,
			}}
		return result, err
	default:
		if err := r.update(bucket, run, config); err != nil && r.resume == Must {
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: err.Error(),
					Code:    service.ErrorInfo_UNKNOWN,
				},
			}
			return result, err
		}
		run.Resumed = true
		return nil, nil
	}
}

func (r *ResumeState) update(bucket *Bucket, run *service.RunRecord, config *runconfig.RunConfig) error {

	r.AddOffset(fs.HistoryChunk, *bucket.GetHistoryLineCount())
	if err := r.updateHistory(run, bucket); err != nil {
		return err
	}

	r.AddOffset(fs.EventsChunk, *bucket.GetEventsLineCount())
	if err := r.updateSummary(run, bucket); err != nil {
		return err
	}

	r.AddOffset(fs.OutputChunk, *bucket.GetLogLineCount())
	if err := r.updateConfig(bucket, config); err != nil {
		return err
	}

	r.updateTags(run, bucket)

	return nil
}

func (r *ResumeState) updateHistory(run *service.RunRecord, bucket *Bucket) error {

	resumed := bucket.GetHistoryTail()
	// TODO: should we error on empty historyTail response?
	if resumed == nil {
		return nil
	}

	var history []string
	if err := json.Unmarshal([]byte(*resumed), &history); err != nil {
		err = fmt.Errorf("failed to unmarshal history tail: %s", err)
		return err
	}

	if len(history) == 0 {
		return nil
	}

	var historyTail map[string]interface{}
	if err := json.Unmarshal([]byte(history[0]), &historyTail); err != nil {
		err = fmt.Errorf("failed to unmarshal history tail map: %s", err)
		return err
	}

	if step, ok := historyTail["_step"].(float64); ok {
		// if we are resuming, we need to update the starting step
		// to be the next step after the last step we ran
		if step > 0 || r.GetFileStreamOffset()[fs.HistoryChunk] > 0 {
			run.StartingStep = int64(step) + 1
		}
	}

	if runtime, ok := historyTail["_runtime"].(float64); ok {
		run.Runtime = int32(runtime)
	}
	return nil
}

func (r *ResumeState) updateSummary(run *service.RunRecord, bucket *Bucket) error {

	resumed := bucket.GetSummaryMetrics()
	// TODO: should we error on empty summaryMetrics response?
	if resumed == nil {
		return nil
	}

	// If we are unable to parse the summary, we should fail if resume is set to
	// must for any other case of resume status, it is fine to ignore it
	// TODO: potential issue with unsupported types like NaN/Inf
	var summary map[string]interface{}
	if err := json.Unmarshal([]byte(*resumed), &summary); err != nil {
		err = fmt.Errorf("failed to unmarshal summary metrics: %s", err)
		return err
	}

	record := service.SummaryRecord{}
	for key, value := range summary {
		valueJson, _ := json.Marshal(value)
		record.Update = append(record.Update, &service.SummaryItem{
			Key:       key,
			ValueJson: string(valueJson),
		})
	}
	run.Summary = &record
	return nil
}

// Merges the original run's config into the current config.
func (r *ResumeState) updateConfig(
	bucket *Bucket,
	config *runconfig.RunConfig,
) error {

	resumed := bucket.GetConfig()
	// TODO: should we error on empty config response?
	if resumed == nil {
		return nil
	}

	// If we are unable to parse the config, we should fail if resume is set to
	// must for any other case of resume status, it is fine to ignore it
	// TODO: potential issue with unsupported types like NaN/Inf
	var cfg map[string]interface{}

	if err := json.Unmarshal([]byte(*resumed), &cfg); err != nil {
		err = fmt.Errorf(
			"sender: checkAndUpdateResumeState: failed to"+
				" unmarshal config: %s", err)
		return err
	}

	deserializedConfig := make(runconfig.RunConfigDict)
	for key, value := range cfg {
		valueDict, ok := value.(map[string]interface{})

		if !ok {
			r.logger.Error(
				fmt.Sprintf(
					"sender: updateResumeState: config value for '%v'"+
						" is not a map[string]interface{}",
					key,
				),
			)
		} else if val, ok := valueDict["value"]; ok {
			deserializedConfig[key] = val
		}
	}

	err := config.MergeResumedConfig(deserializedConfig)
	if err != nil {
		r.logger.Error(
			fmt.Sprintf(
				"sender: updateResumeState: failed to merge"+
					" resumed config: %s",
				err,
			),
		)
	}
	return nil
}

func (r *ResumeState) updateTags(run *service.RunRecord, bucket *Bucket) {
	resumed := bucket.GetTags()
	// TODO: should we error on empty tags response?
	if resumed == nil {
		return
	}
	// handle tags
	// - when resuming a run, its tags will be overwritten by the tags
	//   passed to `wandb.init()`.
	// - to add tags to a resumed run without overwriting its existing tags
	//   use `run.tags += ["new_tag"]` after `wandb.init()`.
	if run.Tags == nil {
		run.Tags = append(run.Tags, resumed...)
	}
}

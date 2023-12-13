package server

import (
	"fmt"

	"github.com/segmentio/encoding/json"

	"github.com/wandb/wandb/core/internal/gql"
	fs "github.com/wandb/wandb/core/pkg/filestream"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

type ResumeState struct {
	ResumeMode       string // must, allow, never
	FileStreamOffset fs.FileStreamOffsetMap
	logger           *observability.CoreLogger
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

func NewResumeState(logger *observability.CoreLogger, mode string) *ResumeState {
	return &ResumeState{logger: logger, ResumeMode: mode}
}

type Bucket = gql.RunResumeStatusModelProjectBucketRun

func (s *Sender) sendRunResult(record *service.Record, runResult *service.RunUpdateResult) {
	result := &service.Result{
		ResultType: &service.Result_RunResult{
			RunResult: runResult,
		},
		Control: record.Control,
		Uuid:    record.Uuid,
	}
	s.outChan <- result

}

func (r *ResumeState) update(
	data *gql.RunResumeStatusResponse,
	run *service.RunRecord,
	config map[string]interface{},
) (*service.RunUpdateResult, error) {
	// If we get that the run is not a resume run, we should fail if resume is set to must
	// for any other case of resume status, it is fine to ignore it
	// If we get that the run is a resume run, we should fail if resume is set to never
	// for any other case of resume status, we should continue to process the resume response
	var err error
	if data.GetModel() == nil || data.GetModel().GetBucket() == nil {
		if r.ResumeMode == "must" {
			err = fmt.Errorf("You provided an invalid value for the `resume` argument. "+
				"The value 'must' is not a valid option for resuming a run (%s/%s) that does not exist. "+
				"Please check your inputs and try again with a valid run ID. "+
				"If you are trying to start a new run, please omit the `resume` argument or use `resume='allow'`.\n", run.Project, run.RunId)
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: err.Error(),
					Code:    service.ErrorInfo_USAGE,
				}}

			return result, err
		}
		return nil, nil
	} else if r.ResumeMode == "never" {
		err = fmt.Errorf("You provided an invalid value for the `resume` argument. "+
			"The value 'never' is not a valid option for resuming a run (%s/%s) that already exists. "+
			"Please check your inputs and try again with a valid value for the `resume` argument.\n", run.Project, run.RunId)
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Message: err.Error(),
				Code:    service.ErrorInfo_USAGE,
			}}
		return result, err
	}

	bucket := data.GetModel().GetBucket()
	run.Resumed = true

	r.AddOffset(fs.HistoryChunk, *bucket.GetHistoryLineCount())
	if result, err := r.handleResumeHistory(run, bucket); err != nil {
		return result, err
	}

	r.AddOffset(fs.EventsChunk, *bucket.GetEventsLineCount())
	if result, err := r.handleSummaryResume(run, bucket); err != nil {
		return result, err
	}

	r.AddOffset(fs.OutputChunk, *bucket.GetLogLineCount())
	if result, err := r.handleConfigResume(bucket, config); err != nil {
		return result, err
	}

	// handle tags
	// - when resuming a run, its tags will be overwritten by the tags
	//   passed to `wandb.init()`.
	// - to add tags to a resumed run without overwriting its existing tags
	//   use `run.tags += ["new_tag"]` after `wandb.init()`.
	if run.Tags == nil {
		run.Tags = append(run.Tags, bucket.GetTags()...)
	}

	return nil, nil
}

func (r *ResumeState) handleResumeHistory(run *service.RunRecord, bucket *Bucket) (*service.RunUpdateResult, error) {
	var historyTail []string
	var historyTailMap map[string]interface{}

	if err := json.Unmarshal([]byte(*bucket.GetHistoryTail()), &historyTail); err != nil {
		err = fmt.Errorf("failed to unmarshal history tail: %s", err)
		if r.ResumeMode == "must" {
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: err.Error(),
					Code:    service.ErrorInfo_UNKNOWN,
				},
			}
			return result, err
		}
	}

	if err := json.Unmarshal([]byte(historyTail[0]), &historyTailMap); err != nil {
		err = fmt.Errorf("failed to unmarshal history tail map: %s", err)
		if r.ResumeMode == "must" {
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: err.Error(),
					Code:    service.ErrorInfo_UNKNOWN,
				},
			}
			return result, err
		}
	}

	if step, ok := historyTailMap["_step"].(float64); ok {
		// if we are resuming, we need to update the starting step
		// to be the next step after the last step we ran
		if step > 0 || r.GetFileStreamOffset()[fs.HistoryChunk] > 0 {
			run.StartingStep = int64(step) + 1
		}
	}

	if runtime, ok := historyTailMap["_runtime"].(float64); ok {
		run.Runtime = int32(runtime)
	}
	return nil, nil
}

func (r *ResumeState) handleSummaryResume(run *service.RunRecord, bucket *Bucket) (*service.RunUpdateResult, error) {
	// If we are unable to parse the config, we should fail if resume is set to must
	// for any other case of resume status, it is fine to ignore it
	var summary map[string]interface{}
	if err := json.Unmarshal([]byte(*bucket.GetSummaryMetrics()), &summary); err != nil {
		err = fmt.Errorf("failed to unmarshal summary metrics: %s", err)
		if r.ResumeMode == "must" {
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: err.Error(),
					Code:    service.ErrorInfo_UNKNOWN,
				},
			}
			return result, err
		}
	}

	summaryRecord := service.SummaryRecord{}
	for key, value := range summary {
		jsonValue, _ := json.Marshal(value)
		summaryRecord.Update = append(summaryRecord.Update, &service.SummaryItem{
			Key:       key,
			ValueJson: string(jsonValue),
		})
	}
	run.Summary = &summaryRecord

	return nil, nil
}

func (r *ResumeState) handleConfigResume(bucket *Bucket, config map[string]interface{}) (*service.RunUpdateResult, error) {
	var cfg map[string]interface{}
	if err := json.Unmarshal([]byte(*bucket.GetConfig()), &cfg); err != nil {
		err = fmt.Errorf("sender: checkAndUpdateResumeState: failed to unmarshal config: %s", err)
		if r.ResumeMode == "must" {
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: err.Error(),
					Code:    service.ErrorInfo_UNKNOWN,
				},
			}
			return result, err
		}
	}

	for key, value := range cfg {
		switch v := value.(type) {
		case map[string]interface{}:
			config[key] = v["value"]
		default:
			r.logger.Error("sender: updateResumeState: config value is not a map[string]interface{}")
		}
	}
	return nil, nil
}

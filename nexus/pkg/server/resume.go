package server

import (
	"fmt"

	"github.com/segmentio/encoding/json"

	"github.com/wandb/wandb/nexus/internal/gql"
	fs "github.com/wandb/wandb/nexus/pkg/filestream"
	"github.com/wandb/wandb/nexus/pkg/service"
	"github.com/wandb/wandb/nexus/pkg/utils"
)

type ResumeState struct {
	FileStreamOffset fs.FileStreamOffsetMap
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

func NewResumeState() *ResumeState {
	return &ResumeState{}
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

func (s *Sender) checkAndUpdateResumeState(record *service.Record, run *service.RunRecord) error {
	if s.graphqlClient == nil {
		return nil
	}
	// There was no resume status set, so we don't need to do anything
	if s.settings.GetResume().GetValue() == "" {
		return nil
	}

	s.resumeState = NewResumeState()
	// If we couldn't get the resume status, we should fail if resume is set
	data, err := gql.RunResumeStatus(s.ctx, s.graphqlClient, &run.Project, utils.NilIfZero(run.Entity), run.RunId)
	if err != nil {
		err = fmt.Errorf("failed to get run resume status: %s", err)
		s.logger.Error("sender:", "error", err)
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Message: err.Error(),
				Code:    service.ErrorInfo_COMMUNICATION,
			}}
		s.sendRunResult(record, result)
		return err
	}

	// If we get that the run is not a resume run, we should fail if resume is set to must
	// for any other case of resume status, it is fine to ignore it
	// If we get that the run is a resume run, we should fail if resume is set to never
	// for any other case of resume status, we should continue to process the resume response
	if data.GetModel() == nil || data.GetModel().GetBucket() == nil {
		if s.settings.GetResume().GetValue() == "must" {
			err = fmt.Errorf("You provided an invalid value for the `resume` argument. "+
				"The value 'must' is not a valid option for resuming a run (%s/%s) that does not exist. "+
				"Please check your inputs and try again with a valid run ID. "+
				"If you are trying to start a new run, please omit the `resume` argument or use `resume='allow'`.\n", run.Project, run.RunId)
			s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: err.Error(),
					Code:    service.ErrorInfo_USAGE,
				}}
			s.sendRunResult(record, result)
			return err
		}
		return nil
	} else if s.settings.GetResume().GetValue() == "never" {
		err = fmt.Errorf("You provided an invalid value for the `resume` argument. "+
			"The value 'never' is not a valid option for resuming a run (%s/%s) that already exists. "+
			"Please check your inputs and try again with a valid value for the `resume` argument.\n", run.Project, run.RunId)
		s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
		result := &service.RunUpdateResult{
			Error: &service.ErrorInfo{
				Message: err.Error(),
				Code:    service.ErrorInfo_USAGE,
			}}
		s.sendRunResult(record, result)
		return err
	}

	bucket := data.GetModel().GetBucket()
	run.Resumed = true

	if err = s.handleResumeHistory(record, run, bucket); err != nil {
		return err
	}

	if err = s.handleSummaryResume(record, run, bucket); err != nil {
		return err
	}

	if err = s.handleConfigResume(record, run, bucket); err != nil {
		return err
	}

	// handle tags
	// - when resuming a run, its tags will be overwritten by the tags
	//   passed to `wandb.init()`.
	// - to add tags to a resumed run without overwriting its existing tags
	//   use `run.tags += ["new_tag"]` after `wandb.init()`.
	if run.Tags == nil {
		run.Tags = append(run.Tags, bucket.GetTags()...)
	}

	s.resumeState.AddOffset(fs.HistoryChunk, *bucket.GetHistoryLineCount())
	s.resumeState.AddOffset(fs.EventsChunk, *bucket.GetEventsLineCount())
	s.resumeState.AddOffset(fs.OutputChunk, *bucket.GetLogLineCount())

	return nil
}

func (s *Sender) handleResumeHistory(record *service.Record, run *service.RunRecord, bucket *Bucket) error {
	var historyTail []string
	var historyTailMap map[string]interface{}

	if err := json.Unmarshal([]byte(*bucket.GetHistoryTail()), &historyTail); err != nil {
		err = fmt.Errorf("failed to unmarshal history tail: %s", err)
		s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
		if s.settings.GetResume().GetValue() == "must" {
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: err.Error(),
					Code:    service.ErrorInfo_UNKNOWN,
				},
			}
			s.sendRunResult(record, result)
			return err
		}
	}

	if err := json.Unmarshal([]byte(historyTail[0]), &historyTailMap); err != nil {
		err = fmt.Errorf("failed to unmarshal history tail map: %s", err)
		s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
		if s.settings.GetResume().GetValue() == "must" {
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: err.Error(),
					Code:    service.ErrorInfo_UNKNOWN,
				},
			}
			s.sendRunResult(record, result)
			return err
		}
	}

	if step, ok := historyTailMap["_step"].(float64); ok {
		// if we are resuming, we need to update the starting step
		// to be the next step after the last step we ran
		if step > 0 {
			run.StartingStep = int64(step) + 1
		}
	}

	if runtime, ok := historyTailMap["_runtime"].(float64); ok {
		run.Runtime = int32(runtime)
	}
	return nil
}

func (s *Sender) handleSummaryResume(record *service.Record, run *service.RunRecord, bucket *Bucket) error {
	// If we are unable to parse the config, we should fail if resume is set to must
	// for any other case of resume status, it is fine to ignore it
	var summary map[string]interface{}
	if err := json.Unmarshal([]byte(*bucket.GetSummaryMetrics()), &summary); err != nil {
		err = fmt.Errorf("failed to unmarshal summary metrics: %s", err)
		s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
		if s.settings.GetResume().GetValue() == "must" {
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: err.Error(),
					Code:    service.ErrorInfo_UNKNOWN,
				},
			}
			s.sendRunResult(record, result)
			return err
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

	return nil
}

func (s *Sender) handleConfigResume(record *service.Record, _ *service.RunRecord, bucket *Bucket) error {
	var config map[string]interface{}
	if err := json.Unmarshal([]byte(*bucket.GetConfig()), &config); err != nil {
		err = fmt.Errorf("sender: checkAndUpdateResumeState: failed to unmarshal config: %s", err)
		s.logger.Error("sender: checkAndUpdateResumeState:", "error", err)
		if s.settings.GetResume().GetValue() == "must" {
			result := &service.RunUpdateResult{
				Error: &service.ErrorInfo{
					Message: err.Error(),
					Code:    service.ErrorInfo_UNKNOWN,
				},
			}
			s.sendRunResult(record, result)
			return err
		}
	}

	for key, value := range config {
		switch v := value.(type) {
		case map[string]interface{}:
			s.configMap[key] = v["value"]
		default:
			s.logger.Error("sender: checkAndUpdateResumeState: config value is not a map[string]interface{}")
		}
	}
	return nil
}

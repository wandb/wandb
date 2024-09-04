package runbranch

import (
	"time"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/filestream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type RunPath struct {
	Entity  string
	Project string
	RunID   string
}

type BranchPoint struct {
	RunID       string
	MetricName  string
	MetricValue float64
}

type BranchError struct {
	Err      error
	Response *spb.ErrorInfo
}

func (re BranchError) Error() string {
	return re.Err.Error()
}

type RunParams struct {
	RunID       string
	Project     string
	Entity      string
	DisplayName string
	StartTime   time.Time
	StorageID   string
	SweepID     string

	// run state fields based on response from the server
	StartingStep int64
	Runtime      int32

	Tags    []string
	Config  map[string]any
	Summary map[string]any

	Resumed bool
	Forked  bool

	FileStreamOffset filestream.FileStreamOffsetMap

	Intialized bool
}

func (r *RunParams) Proto() *spb.RunRecord {

	proto := &spb.RunRecord{}

	// update runID if it exists
	if r.RunID != "" {
		proto.RunId = r.RunID
	}

	// update Entity if it exists
	if r.Entity != "" {
		proto.Entity = r.Entity
	}

	// update Project if it exists
	if r.Project != "" {
		proto.Project = r.Project
	}

	// update DisplayName if it exists
	if r.DisplayName != "" {
		proto.DisplayName = r.DisplayName
	}

	// update StartingStep if it exists
	if r.StartingStep != 0 {
		proto.StartingStep = r.StartingStep
	}

	// update Runtime if it exists
	if r.Runtime != 0 {
		proto.Runtime = r.Runtime
	}

	// update StorageID if it exists
	if r.StorageID != "" {
		proto.StorageId = r.StorageID
	}

	// update SweepID if it exists
	if r.SweepID != "" {
		proto.SweepId = r.SweepID
	}

	// update the config
	if len(r.Config) > 0 {
		config := spb.ConfigRecord{}
		for key, value := range r.Config {
			valueJson, _ := simplejsonext.MarshalToString(value)
			config.Update = append(config.Update, &spb.ConfigItem{
				Key:       key,
				ValueJson: valueJson,
			})
		}
		proto.Config = &config
	}

	// update the summary
	if len(r.Summary) > 0 {
		summary := spb.SummaryRecord{}
		for key, value := range r.Summary {
			valueJson, _ := simplejsonext.MarshalToString(value)
			summary.Update = append(summary.Update, &spb.SummaryItem{
				Key:       key,
				ValueJson: valueJson,
			})
		}
		proto.Summary = &summary
	}

	// Start Time has a special behavior, the current behavior is that start
	// time is the time when the run was resumed and not when it originally
	// started, so we are not updating it here.
	// if !r.StartTime.IsZero() {
	// 	proto.StartTime = timestamppb.New(r.StartTime)
	// }

	// Tags are not updated here, because they have a special behavior,
	// the current behavior is that tags are replaced if provided in init time
	// and only added if provided in the run update.
	// if len(r.Tags) > 0 {
	// 	proto.Tags = r.Tags
	// }

	return proto
}

//gocyclo:ignore
func (r *RunParams) Merge(other *RunParams) {
	if other == nil || r == nil {
		return
	}

	// update runID if it exists
	if other.RunID != "" {
		r.RunID = other.RunID
	}

	// update Entity if it exists
	if other.Entity != "" {
		r.Entity = other.Entity
	}

	// update Project if it exists
	if other.Project != "" {
		r.Project = other.Project
	}

	// update DisplayName if it exists
	if other.DisplayName != "" {
		r.DisplayName = other.DisplayName
	}

	// update StartingStep if it exists
	if other.StartingStep != 0 {
		r.StartingStep = other.StartingStep
	}

	// update Runtime if it exists
	if other.Runtime != 0 {
		r.Runtime = other.Runtime
	}

	// update StorageID if it exists
	if other.StorageID != "" {
		r.StorageID = other.StorageID
	}

	// update SweepID if it exists
	if other.SweepID != "" {
		r.SweepID = other.SweepID
	}

	// update the config
	if len(other.Config) > 0 {
		if r.Config == nil {
			r.Config = make(map[string]any)
		}
		for key, value := range other.Config {
			r.Config[key] = value
		}
	}

	// update the summary
	if len(other.Summary) > 0 {
		if r.Summary == nil {
			r.Summary = make(map[string]any)
		}
		for key, value := range other.Summary {
			r.Summary[key] = value
		}
	}

	// update the tags
	if len(other.Tags) > 0 {
		r.Tags = other.Tags
	}

	// update the filestream offset
	if len(other.FileStreamOffset) > 0 {
		if r.FileStreamOffset == nil {
			r.FileStreamOffset = make(filestream.FileStreamOffsetMap)
		}
		for key, value := range other.FileStreamOffset {
			r.FileStreamOffset[key] = value
		}
	}

	// update the start time
	if !other.StartTime.IsZero() {
		r.StartTime = other.StartTime
	}

	if other.Resumed {
		r.Resumed = true
	}

	if other.Forked {
		r.Forked = true
	}

}

func (r *RunParams) Clone() *RunParams {
	clone := &RunParams{}
	clone.Merge(r)
	return clone
}

func NewRunParams() *RunParams {
	return &RunParams{
		FileStreamOffset: make(filestream.FileStreamOffsetMap),
	}
}

package runbranch

import (
	"slices"
	"time"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/timestamppb"
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
	StorageID              string
	Entity, Project, RunID string

	GroupName   string
	DisplayName string
	Notes       string

	// Commit and RemoteURL contain the run's VCS (git) information.
	Commit, RemoteURL string

	Host    string
	Program string
	JobType string
	SweepID string

	// run state fields based on response from the server
	StartingStep int64
	Runtime      int32

	Tags []string

	// Summary exists only to pass information back to the client when resuming
	// or forking a run, so that it can send it back to us for us to update the
	// Handler and write it to the transaction log.
	//
	// It is ignored when creating or updating RunParams from a RunRecord.
	//
	// TODO: Untangle Summary logic and remove this field.
	Summary map[string]any

	Resumed bool
	Forked  bool

	StartTime time.Time

	// FileStreamOffset exists here only to pass around run-resume info.
	//
	// It is ignored when creating or updating RunParams from a RunRecord
	//
	// TODO: Remove FileStreamOffset from RunParams.
	FileStreamOffset filestream.FileStreamOffsetMap
}

// NewRunParams creates a new params object using a fully filled out record.
//
// Unlike Update(), this requires the record to have all fields set to their
// desired values. Any missing fields will be cleared on records passed to
// SetOnProto().
func NewRunParams(
	record *spb.RunRecord,
	runSettings *settings.Settings,
) *RunParams {
	r := &RunParams{FileStreamOffset: make(filestream.FileStreamOffsetMap)}
	r.Update(record, runSettings)
	return r
}

// SetOnProto overwrites fields on the record.
func (r *RunParams) SetOnProto(record *spb.RunRecord) {
	if r == nil {
		return
	}

	// NOTE: Fields are organized the same as on the struct.
	record.StorageId = r.StorageID

	record.Entity = r.Entity
	record.Project = r.Project
	record.RunId = r.RunID

	record.RunGroup = r.GroupName
	record.DisplayName = r.DisplayName
	record.Notes = r.Notes

	record.Git = &spb.GitRepoRecord{
		Commit:    r.Commit,
		RemoteUrl: r.RemoteURL,
	}

	record.Host = r.Host
	// Program is stored on settings, so skipped here.
	record.JobType = r.JobType
	record.SweepId = r.SweepID

	record.StartingStep = r.StartingStep
	record.Runtime = r.Runtime

	record.Tags = slices.Clone(r.Tags)

	record.Summary = &spb.SummaryRecord{}
	for key, value := range r.Summary {
		valueJson, _ := simplejsonext.MarshalToString(value)
		record.Summary.Update = append(record.Summary.Update, &spb.SummaryItem{
			Key:       key,
			ValueJson: valueJson,
		})
	}

	record.Resumed = r.Resumed
	record.Forked = r.Forked

	record.StartTime = timestamppb.New(r.StartTime)
}

// Update populates fields on the params object using the given record.
//
// The record may be partially filled, in which case only non-empty fields are
// used.
func (r *RunParams) Update(
	record *spb.RunRecord,
	runSettings *settings.Settings,
) {
	// NOTE: Fields are organized the same as on the struct.

	if record.StorageId != "" {
		r.StorageID = record.StorageId
	}

	if record.Entity != "" {
		r.Entity = record.Entity
	}
	if record.Project != "" {
		r.Project = record.Project
	}
	if record.RunId != "" {
		r.RunID = record.RunId
	}

	if record.RunGroup != "" {
		r.GroupName = record.RunGroup
	}
	if record.DisplayName != "" {
		r.DisplayName = record.DisplayName
	}
	if record.Notes != "" {
		r.Notes = record.Notes
	}

	if record.Git.GetCommit() != "" {
		r.Commit = record.Git.GetCommit()
	}
	if record.Git.GetRemoteUrl() != "" {
		r.RemoteURL = record.Git.GetRemoteUrl()
	}

	if !runSettings.IsDisableMachineInfo() && record.Host != "" {
		r.Host = record.Host
	}
	if runSettings.GetProgram() != "" {
		r.Program = runSettings.GetProgram()
	}
	if record.JobType != "" {
		r.JobType = record.JobType
	}
	if record.SweepId != "" {
		r.SweepID = record.SweepId
	}

	if record.StartingStep != 0 {
		r.StartingStep = record.StartingStep
	}
	if record.Runtime != 0 {
		r.Runtime = record.Runtime
	}

	if len(record.Tags) > 0 {
		r.Tags = slices.Clone(record.Tags)
	}

	// NOTE: Summary is ignored; see comment on the field.

	if record.Resumed {
		r.Resumed = true
	}
	if record.Forked {
		r.Forked = true
	}

	if startTime := record.StartTime.AsTime(); !startTime.IsZero() {
		r.StartTime = startTime
	}

	// NOTE: FileStreamOffset is ignored; see comment on the field.
}

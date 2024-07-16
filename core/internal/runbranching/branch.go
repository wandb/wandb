package runbranching

import (
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/pkg/service"
)

const (
	ModeNone   string = "none"
	ModeResume string = "resume"
	ModeFork   string = "fork"
	ModeRewind string = "rewind"
)

type RunBranch interface {
	State() *State
	PreUpsert() error
	PostUpsert() error
}

type State struct {
	Mode             string
	Project          string
	RunId            string
	FileStreamOffset filestream.FileStreamOffsetMap
	StartingStep     int64
	Runtime          int32
	Summary          *service.SummaryRecord
	Config           *runconfig.RunConfig
	Tags             []string
}

func NewState(
	branchMode string,
	project string,
	runId string,
	config *runconfig.RunConfig,
	tags []string,
) *State {
	return &State{
		Mode:    branchMode,
		Project: project,
		RunId:   runId,
		Config:  config,
		Tags:    tags,
	}
}

func (s *State) GetFileStreamOffset() filestream.FileStreamOffsetMap {
	if s == nil {
		return nil
	}
	return s.FileStreamOffset
}

func (s *State) AddOffset(key filestream.ChunkTypeEnum, offset int) {
	if s.FileStreamOffset == nil {
		s.FileStreamOffset = make(filestream.FileStreamOffsetMap)
	}
	s.FileStreamOffset[key] = offset
}

package runbranching

import (
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/pkg/service"
)

type BranchType uint8

const (
	BranchTypeNone BranchType = iota
	BranchTypeResume
	BranchTypeFork
	BranchTypeRewind
)

type State struct {
	Type             BranchType
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
	branchType BranchType,
	project string,
	runId string,
	config *runconfig.RunConfig,
	tags []string,
) *State {
	return &State{
		Type:    branchType,
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

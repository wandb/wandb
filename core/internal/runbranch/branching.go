package runbranch

import (
	"github.com/wandb/wandb/core/pkg/service"
)

type RunPath struct {
	Entity  string
	Project string
	RunID   string
}

type Branching interface {
	GetUpdates(RunPath) (*RunParams, error)
	ApplyUpdates(src, dst *RunParams)
}

type BranchError struct {
	Err      error
	Response *service.ErrorInfo
}

func (re BranchError) Error() string {
	return re.Err.Error()
}

type NoBranch struct {
}

func (nb NoBranch) GetUpdates(_ RunPath) (*RunParams, error) {
	return nil, nil
}

func (nb NoBranch) ApplyUpdates(src, dst *RunParams) {
}

type InvalidBranch struct {
	err      error
	response *service.ErrorInfo
}

func (ib InvalidBranch) GetUpdates(_ RunPath) (*RunParams, error) {
	return nil, &BranchError{
		Err:      ib.err,
		Response: ib.response,
	}
}

func (ib InvalidBranch) ApplyUpdates(src, dst *RunParams) {
}

package runbranch

import (
	"github.com/wandb/wandb/core/pkg/service"
)

type Branching interface {
	GetUpdates(string, string, string) (*RunParams, error)
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

func (nb NoBranch) GetUpdates(
	entity, project, runID string,
) (*RunParams, error) {
	return nil, nil
}

type InvalidBranch struct {
	err      error
	response *service.ErrorInfo
}

func (ib InvalidBranch) GetUpdates(
	entity, project, runID string,
) (*RunParams, error) {
	return nil, &BranchError{
		Err:      ib.err,
		Response: ib.response,
	}
}

package runbranch

import (
	"context"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/pkg/service"
)

type Branching interface {
	GetUpdates(context.Context, graphql.Client, string, string, string) (*RunParams, error)
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
	ctx context.Context,
	client graphql.Client,
	entity, project, runID string,
) (*RunParams, error) {
	return nil, nil
}

type InvalidBranch struct {
	err      error
	response *service.ErrorInfo
}

func (ib InvalidBranch) GetUpdates(
	ctx context.Context,
	client graphql.Client,
	entity, project, runID string,
) (*RunParams, error) {
	return nil, &BranchError{
		Err:      ib.err,
		Response: ib.response,
	}
}

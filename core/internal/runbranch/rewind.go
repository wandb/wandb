package runbranch

import (
	"context"

	"github.com/Khan/genqlient/graphql"
)

type RewindBranch struct {
	runid  string
	metric string
	value  float64
}

func (r RewindBranch) GetUpdates(ctx context.Context,
	client graphql.Client,
	entity, project, runID string,
) (*RunParams, error) {
	return nil, nil
}

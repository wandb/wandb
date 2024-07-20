package runbranch

import (
	"context"

	"github.com/Khan/genqlient/graphql"
)

type ForkBranch struct {
	runid  string
	metric string
	value  float64
}

func (f ForkBranch) GetUpdates(ctx context.Context,
	client graphql.Client,
	entity, project, runID string,
) (*RunParams, error) {
	return nil, nil
}

package runbranch

type ForkBranch struct {
	runid  string
	metric string
	value  float64
}

func (f ForkBranch) GetUpdates(
	entity, project, runID string,
) (*RunParams, error) {
	return nil, nil
}

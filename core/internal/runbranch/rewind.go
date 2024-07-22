package runbranch

type RewindBranch struct {
	runid  string
	metric string
	value  float64
}

func (r RewindBranch) GetUpdates(
	entity, project, runID string,
) (*RunParams, error) {
	return nil, nil
}

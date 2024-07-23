package runbranch

type ForkBranch struct {
	runid  string
	metric string
	value  float64
}

func (f ForkBranch) GetUpdates(
	_ RunPath,
) (*RunParams, error) {
	return nil, nil
}

func (f ForkBranch) ApplyUpdates(src, dst *RunParams) {
}

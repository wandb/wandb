package runbranch

type RewindBranch struct {
	runid  string
	metric string
	value  float64
}

func (r RewindBranch) GetUpdates(_ RunPath) (*RunParams, error) {
	return nil, nil
}

func (r RewindBranch) ApplyUpdates(src, dst *RunParams) {
}

package gowandb

type RunParams struct {
}

type RunOption func(*RunParams)

func (s *Session) NewRun(opts ...RunOption) (*Run, error) {
	runParams := &RunParams{}
	for _, opt := range opts {
		opt(runParams)
	}
	run := s.manager.NewRun()
	return run, nil
}

func WithConfig() RunOption {
	return func(o *RunParams) {
	}
}

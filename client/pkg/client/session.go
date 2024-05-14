package client

type Session struct {
	settings map[string]interface{}
}

func NewSession() *Session {
	return &Session{
		settings: make(map[string]interface{}),
	}
}

// start wandb-core

// add a new run

func (s *Session) NewRun(id string) *Run {
	return NewRun(id)
}

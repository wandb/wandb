package client

type Run struct {
	id       string
	settings map[string]interface{}
}

func NewRun(id string) *Run {
	return &Run{
		id:       id,
		settings: make(map[string]interface{}),
	}
}

func (r *Run) GetId() string {
	return r.id
}

package run

type Run struct {
	id       string
	settings map[string]interface{}
}

func New(id string) *Run {
	return &Run{
		id:       id,
		settings: make(map[string]interface{}),
	}
}

func (r *Run) GetId() string {
	return r.id
}

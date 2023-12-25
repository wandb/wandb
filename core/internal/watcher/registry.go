package watcher

type registry struct {
	events map[string]func(Event) error
}

func (r *registry) register(name string, fn func(Event) error) {
	if r.events == nil {
		r.events = make(map[string]func(Event) error)
	}
	r.events[name] = fn
}

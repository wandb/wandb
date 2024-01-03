package watcher

import "sync"

type registry struct {
	events map[string]func(Event) error
	mutex  sync.RWMutex
}

func (r *registry) register(name string, fn func(Event) error) {
	r.mutex.Lock()
	defer r.mutex.Unlock()
	if r.events == nil {
		r.events = make(map[string]func(Event) error)
	}
	r.events[name] = fn
}

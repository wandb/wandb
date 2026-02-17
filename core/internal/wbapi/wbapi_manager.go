package wbapi

import (
	"fmt"
	"sync"
)

// WbApiManager is a manager for wandbAPI instances.
// It is thread-safe and is used to ensure that
// only one wandbAPI instance exists for a given streamId.
type WbApiManager struct {
	mu sync.Mutex

	// apis is a map of ids to wandbAPI instances.
	apis map[string]*WandbAPI

	// nextId is the next id to assign to a wandbAPI instance.
	nextId int
}

// NewWbApiManager creates a new WbApiManager.
func NewWbApiManager() *WbApiManager {
	return &WbApiManager{
		apis: make(map[string]*WandbAPI),
	}
}

// AddWandbAPI adds a wandbAPI instance to the mux if it doesn't already exist.
// If the wandbAPI instance already exists, it returns an error.
func (mgr *WbApiManager) AddWandbAPI(
	wandbAPI *WandbAPI,
) (string, error) {
	mgr.mu.Lock()
	defer mgr.mu.Unlock()

	id := fmt.Sprintf("api-%d", mgr.nextId)
	mgr.nextId++

	mgr.apis[id] = wandbAPI
	return id, nil
}

// GetWandbAPI gets a wandbAPI instance from the mux.
// If the wandbAPI instance does not exist, it returns an error.
func (mgr *WbApiManager) GetWandbAPI(id string) (*WandbAPI, error) {
	mgr.mu.Lock()
	defer mgr.mu.Unlock()

	if wandbAPI, ok := mgr.apis[id]; !ok {
		return nil, fmt.Errorf("wandbAPI not found")
	} else {
		return wandbAPI, nil
	}
}

// RemoveWandbAPI removes a wandbAPI instance from the mux, and return it.
// If the wandbAPI instance does not exist, it returns an error.
func (mgr *WbApiManager) RemoveWandbAPI(id string) (*WandbAPI, error) {
	mgr.mu.Lock()
	defer mgr.mu.Unlock()
	if wandbAPI, ok := mgr.apis[id]; !ok {
		return nil, fmt.Errorf("wandbAPI not found")
	} else {
		delete(mgr.apis, id)
		return wandbAPI, nil
	}
}

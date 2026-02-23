package wbapi

import (
	"fmt"
	"sync"
)

// WbApiManager is a manager for wandbAPI instances.
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

// AddWandbAPI creates a new WandbAPI instance and returns the id assigned to it.
func (mgr *WbApiManager) AddWandbAPI(
	wandbAPI *WandbAPI,
) string {
	mgr.mu.Lock()
	defer mgr.mu.Unlock()

	id := fmt.Sprintf("api-%d", mgr.nextId)
	mgr.nextId++

	mgr.apis[id] = wandbAPI
	return id
}

// GetWandbAPI gets a wandbAPI instance for the given id.
//
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

// RemoveWandbAPI removes a wandbAPI instance for the given id from the mapping and returns it.
//
// If the wandbAPI instance does not exist, it returns an error.
func (mgr *WbApiManager) RemoveWandbAPI(id string) *WandbAPI {
	mgr.mu.Lock()
	defer mgr.mu.Unlock()

	if wandbAPI, ok := mgr.apis[id]; !ok {
		return nil
	} else {
		delete(mgr.apis, id)
		return wandbAPI
	}
}

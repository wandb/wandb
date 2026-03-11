package wbapi

import (
	"fmt"
	"sync"
)

// WandbAPIManager routes API requests to WandbAPI instances.
//
// Different WandbAPI instances may communicate with different accounts on
// different W&B deployments, and may have different configurations.
//
// The WandbAPIManager assigns IDs to WandbAPI instances and uses them
// to route requests.
type WandbAPIManager struct {
	mu sync.Mutex

	// apis is a map of IDs to WandbAPI instances.
	apis map[string]*WandbAPI

	// nextId is the next ID to assign to a WandbAPI instance.
	nextId int
}

// NewManager creates a new WandbAPIManager.
func NewManager() *WandbAPIManager {
	return &WandbAPIManager{
		apis: make(map[string]*WandbAPI),
	}
}

// AddWandbAPI registers a WandbAPI instance to a new ID.
func (mgr *WandbAPIManager) AddWandbAPI(
	wandbAPI *WandbAPI,
) string {
	mgr.mu.Lock()
	defer mgr.mu.Unlock()

	id := fmt.Sprintf("api-%d", mgr.nextId)
	mgr.nextId++

	mgr.apis[id] = wandbAPI
	return id
}

// GetWandbAPI returns the WandbAPI instance for the given ID.
//
// Returns an error if no WandbAPI is registered for the ID.
func (mgr *WandbAPIManager) GetWandbAPI(id string) (*WandbAPI, error) {
	mgr.mu.Lock()
	defer mgr.mu.Unlock()

	if wandbAPI, ok := mgr.apis[id]; !ok {
		return nil, fmt.Errorf("wbapi: no WandbAPI for ID %s", id)
	} else {
		return wandbAPI, nil
	}
}

// RemoveWandbAPI forgets and returns the WandbAPI instance for the ID.
//
// Returns nil if no WandbAPI is registered for the ID.
func (mgr *WandbAPIManager) RemoveWandbAPI(id string) *WandbAPI {
	mgr.mu.Lock()
	defer mgr.mu.Unlock()

	if wandbAPI, ok := mgr.apis[id]; !ok {
		return nil
	} else {
		delete(mgr.apis, id)
		return wandbAPI
	}
}

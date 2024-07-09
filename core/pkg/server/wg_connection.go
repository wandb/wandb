package server

import "sync"

type WGConnection struct {
	// wgConn is the WireGuard connection.
	wg sync.WaitGroup

	connIDs map[string]struct{}
}

// NewWGConnection creates a new WireGuard connection.
func NewWGConnection() *WGConnection {
	return &WGConnection{
		connIDs: make(map[string]struct{}),
		wg:      sync.WaitGroup{},
	}
}

// Add adds a connection ID to the WireGuard connection.
func (c *WGConnection) Add(connID string) {
	// check if the connection ID already exists
	if _, ok := c.connIDs[connID]; ok {
		return
	}

	c.connIDs[connID] = struct{}{}
	c.wg.Add(1)
}

// Remove removes a connection ID from the WireGuard connection.
func (c *WGConnection) Remove(connID string) {
	// check if the connection ID does not exist
	if _, ok := c.connIDs[connID]; !ok {
		return
	}

	delete(c.connIDs, connID)
	c.wg.Done()
}

// Wait waits for all connections to be removed.
func (c *WGConnection) Wait() {
	c.wg.Wait()
}

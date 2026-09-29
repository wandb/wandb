package sharedmode

import "github.com/google/uuid"

// ClientID is a unique ID for a writer in "shared" mode.
//
// This identifies the process that uploaded a set of metrics when
// running in "shared" mode, where there may be multiple writers for
// the same run.
//
// It is a UUIDv7, so IDs of writers to the same run sort by the time
// each writer started.
type ClientID string

// RandomClientID generates a new client ID.
func RandomClientID() ClientID {
	return ClientID(uuid.Must(uuid.NewV7()).String())
}

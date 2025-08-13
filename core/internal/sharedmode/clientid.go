package sharedmode

import "github.com/wandb/wandb/core/internal/randomid"

// ClientID is a unique ID for a writer in "shared" mode.
//
// This identifies the process that uploaded a set of metrics when
// running in "shared" mode, where there may be multiple writers for
// the same run.
type ClientID string

// RandomClientID generates a new client ID.
func RandomClientID() ClientID {
	return ClientID(randomid.GenerateUniqueID(32))
}

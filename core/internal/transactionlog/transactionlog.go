// Package transactionlog implements reading and writing .wandb files.
package transactionlog

import (
	"errors"

	"github.com/wandb/wandb/core/internal/settings"
)

// VersionForSettings returns the version for a transaction log (.wandb file)
// written with the given settings.
//
// The current SDK supports transaction log versions 0 and 1.
//
// Version 0 MUST include JSON history values for backwards compatibility, and
// MAY include typed history values as well. Older SDKs can still read version 0
// files, but they will not interpret typed history values.
//
// Version 1 MUST include typed history values only, and omits JSON history
// values. This is not compatible with SDKs versions that predate typed history
// values, which will reject version 1 files.
func VersionForSettings(s *settings.Settings) uint8 {
	if s.IsHistoryValueEncodingJSON() {
		return 0
	}
	return 1 // typed history values only
}

// ensureSupportedVersion returns an error for an unsupported version.
//
// The error does not have the conventional prefix ("transactionlog:") and one
// should not be added because that would add noise. The message is shown to
// the user when using `wandb sync`.
func ensureSupportedVersion(version uint8) error {
	switch {
	case version <= 1:
		return nil
	default:
		return errors.New("a newer wandb version is required to read this file")
	}
}

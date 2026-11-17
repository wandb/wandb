// Package transactionlog implements reading and writing .wandb files.
package transactionlog

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/settings"
)

// VersionForSettings returns the version for a transaction log written
// with the given settings.
//
// Readers that predate typed history values need JSON values, so only
// files without JSON values require VersionTypedHistory.
func VersionForSettings(s *settings.Settings) uint8 {
	if s.IsHistoryValueEncodingJSON() {
		return byte(0)
	}
	return byte(1)
}

// ensureSupportedVersion returns an error for an unsupported version.
func ensureSupportedVersion(version uint8) error {
	switch {
	case version <= 1:
		return nil
	default:
		return fmt.Errorf("a newer wandb version is required to read this file: %d", version)
	}
}

// Package transactionlog implements reading and writing .wandb files.
package transactionlog

import "github.com/wandb/wandb/core/internal/settings"

const (
	// VersionLegacy permits readers that require JSON history values.
	VersionLegacy uint8 = 0
	// VersionTypedHistory requires a reader that supports typed history values.
	VersionTypedHistory uint8 = 1
)

// VersionForSettings returns the version for a transaction log written
// with the given settings.
//
// Readers that predate typed history values need JSON values, so only
// files without JSON values require VersionTypedHistory.
func VersionForSettings(s *settings.Settings) uint8 {
	if s.IsHistoryValueEncodingJSON() {
		return VersionLegacy
	}
	return VersionTypedHistory
}

// UnsupportedVersionError reports a file version that this SDK cannot read.
type UnsupportedVersionError struct {
	Version uint8
}

// Error omits the package prefix because sync shows this message to users.
// The file version does not identify which SDK version the reader needs.
func (e *UnsupportedVersionError) Error() string {
	return "a newer wandb version is required to read this file"
}

// ensureSupportedVersion returns an error for an unsupported version.
func ensureSupportedVersion(version uint8) error {
	switch version {
	case VersionLegacy, VersionTypedHistory:
		return nil
	default:
		return &UnsupportedVersionError{Version: version}
	}
}

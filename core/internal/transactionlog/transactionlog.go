// Package transactionlog implements reading and writing .wandb files.
package transactionlog

const (
	// VersionLegacy permits readers that require JSON history values.
	VersionLegacy uint8 = 0
	// VersionTypedHistory requires a reader that supports typed history values.
	VersionTypedHistory uint8 = 1
)

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

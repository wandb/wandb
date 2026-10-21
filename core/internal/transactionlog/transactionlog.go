// Package transactionlog implements reading and writing .wandb files.
package transactionlog

// wandbStoreVersion is written into .wandb file headers.
//
// Incrementing this prevents older SDKs from attempting to read .wandb
// files in a new format. It may also prevent the next SDK version from reading
// old .wandb files, depending on the implementation of ensureSupportedVersion.
// Update the error messages below.
const wandbStoreVersion = 0

// UnsupportedVersionError reports a file version that this SDK cannot read.
type UnsupportedVersionError struct {
	Version uint8
}

// Error omits the package prefix because sync shows this message to users.
// The file version does not identify which SDK version the reader needs.
func (e *UnsupportedVersionError) Error() string {
	if e.Version > wandbStoreVersion {
		return "a newer wandb version is required to read this file"
	}

	return "an older wandb version is required to read this file"
}

// ensureSupportedVersion returns an error for an unsupported version.
func ensureSupportedVersion(version uint8) error {
	if version != wandbStoreVersion {
		return &UnsupportedVersionError{Version: version}
	}
	return nil
}

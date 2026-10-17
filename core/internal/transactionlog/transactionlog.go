// Package transactionlog implements reading and writing .wandb files.
package transactionlog

import "errors"

// wandbStoreVersion is written into .wandb file headers.
//
// Incrementing this prevents older SDKs from attempting to read .wandb
// files in a new format. It may also prevent the next SDK version from reading
// old .wandb files, depending on the implementation of ensureSupportedVersion.
// Update the error messages below.
const wandbStoreVersion = 1

// ensureSupportedVersion returns an error for an unsupported version.
//
// The error does not have the conventional prefix ("transactionlog:") and one
// should not be added because that would add noise. The message is shown to
// the user when using `wandb sync`.
func ensureSupportedVersion(version uint8) error {
	switch {
	case version < 1:
		return errors.New("wandb<=0.30.0 is required to read this file")

	case version > wandbStoreVersion:
		// In this case, we can't provide any more useful info unless we
		// attempt to read the SDK version from the file.
		//
		// Hopefully the user knows which version was used to generate it!
		return errors.New("a newer wandb version is required to read this file")

	case version < wandbStoreVersion:
		// This is a fallback that should never be reached.
		//
		// Add cases above for specific old versions.
		return errors.New("an older wandb version is required to read this file")

	default:
		return nil
	}
}

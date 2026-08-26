// Package transactionlog implements reading and writing .wandb files.
package transactionlog

import "errors"

// wandbStoreVersion is written into .wandb file headers.
//
// Incrementing this prevents older SDKs from attempting to read .wandb
// files in a new format. It may also prevent the next SDK version from reading
// old .wandb files, depending on the implementation of ensureSupportedVersion.
// Update the error messages below.
const wandbStoreVersion = 0

// ensureSupportedVersion returns an error for an unsupported version.
//
// The error does not have the conventional prefix ("transactionlog:") and one
// should not be added because that would add noise. The message is shown to
// the user when using `wandb sync`.
func ensureSupportedVersion(version uint8) error {
	switch {
	case version > wandbStoreVersion:
		// In this case, we can't provide any more useful info unless we
		// attempt to read the SDK version from the file.
		//
		// Hopefully the user knows which version was used to generate it!
		return errors.New("a newer wandb version is required to read this file")

	case version < wandbStoreVersion:
		// This is not currently possible, but it's here as a safe default.
		//
		// When we do bump `wandbStoreVersion`, we should ensure this message
		// includes the required wandb Python version.
		return errors.New("an older wandb version is required to read this file")

	default:
		return nil
	}
}

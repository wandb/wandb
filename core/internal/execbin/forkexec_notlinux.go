//go:build !linux

package execbin

import (
	"os"
)

func doForkExec(filePayload []byte, args []string) (WaitFunc, error) {
	file, err := os.CreateTemp("", "wandb-core-")
	if err != nil {
		return nil, err
	}
	_, err = file.Write(filePayload)
	if err != nil {
		return nil, err
	}
	file.Close()
	err = os.Chmod(file.Name(), 0500)
	if err != nil {
		return nil, err
	}

	wait, err := runCommand(file.Name(), args)
	// TODO(beta): We are not able to remove this file here, look into this
	// we could remove it when wait finishes
	// defer os.Remove(file.Name())
	return wait, err
}

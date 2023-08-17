//go:build !linux

package execbin

import (
	"os"
)

func fork_exec(filePayload []byte, args []string) (WaitFunc, error) {
	file, err := os.CreateTemp("", "wandb-core-")
	if err != nil {
		return nil, err
	}
	defer os.Remove(file.Name())
	_, err = file.Write(filePayload)
	if err != nil {
		return nil, err
	}
	file.Close()
	err = os.Chmod(file.Name(), 0500)
	if err != nil {
		return nil, err
	}

	return run_command(file.Name(), args)
}

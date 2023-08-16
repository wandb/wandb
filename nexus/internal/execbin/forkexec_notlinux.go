//go:build !linux

package execbin

import (
	"fmt"
	"os"
	"os/exec"
	"syscall"
)

func fork_exec(filePayload []byte, args []string) (*exec.Cmd, error) {
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
	cmd := exec.Command(file.Name(), args...)
	cmd.Env = os.Environ()
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	err = cmd.Start()
	if err != nil {
		switch e := err.(type) {
		case *exec.Error:
			fmt.Println("failed executing:", err)
		case *exec.ExitError:
			fmt.Println("command exit rc =", e.ExitCode())
		default:
			panic(err)
		}
	}
	fmt.Printf("write %+v\n", file.Name())
	return cmd, nil
}

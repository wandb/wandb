package launcher

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"syscall"
)

type waitFunc func() error
type forkExecCmd struct {
	waitFunc waitFunc
}

// ExecCommand executes a command with the given arguments and returns a
// ForkExecCmd object that can be used to wait for the command to finish.
func execCommand(command string, args []string) (*forkExecCmd, error) {
	path, err := exec.LookPath(command)
	if err != nil {
		return nil, err
	}
	waitFunc, err := runCommand(path, args)
	if err != nil {
		return nil, err
	}
	return &forkExecCmd{waitFunc: waitFunc}, nil
}

// waitcmd waits for the command to finish and returns an error if the command
// fails.
func waitcmd(waitFunc waitFunc) error {
	if err := waitFunc(); err != nil {
		var exiterr *exec.ExitError
		if errors.As(err, &exiterr) {
			if status, ok := exiterr.Sys().(syscall.WaitStatus); ok {
				err = fmt.Errorf("command failed with exit code %d", status.ExitStatus())
				return err
			}
		}
		return err
	}
	return nil
}

// wait waits for the command to finish and returns an error if the command fails.
func (c *forkExecCmd) wait() error {
	// TODO: add error handling
	if c.waitFunc != nil {
		err := waitcmd(c.waitFunc)
		if err != nil {
			return err
		}
	}
	return nil
}

// runCommand runs the command with the given arguments.
func runCommand(command string, args []string) (waitFunc, error) {
	cmd := exec.Command(command, args...)
	cmd.Env = os.Environ()
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	err := cmd.Start()
	if err != nil {
		switch e := err.(type) {
		case *exec.Error:
			err = fmt.Errorf("failed executing: %w", err)
			return nil, err
		case *exec.ExitError:
			err = fmt.Errorf("command exit rc = %d", e.ExitCode())
			return nil, err
		default:
			err = fmt.Errorf("failed executing: %w", err)
			return nil, err
		}
	}
	return cmd.Wait, nil
}

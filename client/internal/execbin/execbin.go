// package execbin implements forking and executing a binary.
package execbin

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"syscall"
)

type WaitFunc func() error
type ForkExecCmd struct {
	waitFunc WaitFunc
}

func ExecCommand(command string, args []string) (*ForkExecCmd, error) {
	path, err := exec.LookPath(command)
	if err != nil {
		panic(err)
	}
	waitFunc, err := runCommand(path, args)
	if err != nil {
		panic(err)
	}
	return &ForkExecCmd{waitFunc: waitFunc}, err
}

func waitcmd(waitFunc WaitFunc) error {
	if err := waitFunc(); err != nil {
		var exiterr *exec.ExitError
		if errors.As(err, &exiterr) {
			if status, ok := exiterr.Sys().(syscall.WaitStatus); ok {
				fmt.Printf("Exit Status: %+v\n", status.ExitStatus())
				return err
			}
		}
		return err
	}
	return nil
}

func (c *ForkExecCmd) Wait() error {
	// TODO: add error handling
	if c.waitFunc != nil {
		err := waitcmd(c.waitFunc)
		if err != nil {
			panic(err)
		}
	}
	return nil
}

func runCommand(command string, args []string) (WaitFunc, error) {
	cmd := exec.Command(command, args...)
	cmd.Env = os.Environ()
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	err := cmd.Start()
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
	return cmd.Wait, nil
}

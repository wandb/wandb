// package execbin fork and execs a binary image dealing with system differences.
package execbin

import (
	"fmt"
	"os/exec"
	"syscall"
)

type WaitFunc func() error
type ForkExecCmd struct {
	waitFunc WaitFunc
}

func ForkExec(filePayload []byte, args []string) (*ForkExecCmd, error) {
	var err error
	waitFunc, err := fork_exec(filePayload, args)
	if err != nil {
		panic(err)
	}
	return &ForkExecCmd{waitFunc: waitFunc}, err
}

func waitcmd(waitFunc WaitFunc) error {
	if err := waitFunc(); err != nil {
		if exiterr, ok := err.(*exec.ExitError); ok {
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

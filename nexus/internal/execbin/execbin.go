// package execbin fork and execs a binary image dealing with system differences.
package execbin

import (
	"fmt"
	"syscall"
	"os/exec"
)

type ForkExecCmd struct {
	cmd *exec.Cmd
}

func ForkExec(filePayload []byte, args []string) (*ForkExecCmd, error) {
	var err error
	var cmd *exec.Cmd

	cmd, err = fork_exec(filePayload, args)
	if err != nil {
		panic(err)
	}
	return &ForkExecCmd{cmd: cmd}, err
}

func waitcmd(command *exec.Cmd) error {
	if err := command.Wait(); err != nil {
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
	if c.cmd != nil {
		err := waitcmd(c.cmd)
		if err != nil {
			panic(err)
		}
	}
	return nil
}

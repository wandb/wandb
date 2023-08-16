// package execbin fork and execs a binary image dealing with system differences.
package execbin

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"runtime"
	"syscall"
	"unsafe"
)

func MemfdCreate(path string) (r1 uintptr, err error) {
	s, err := syscall.BytePtrFromString(path)
	if err != nil {
		return 0, err
	}

	r1, _, errno := syscall.Syscall(319, uintptr(unsafe.Pointer(s)), 0, 0)

	if int(r1) == -1 {
		return r1, errno
	}

	return r1, nil
}

func CopyToMem(fd uintptr, buf []byte) (err error) {
	_, err = syscall.Write(int(fd), buf)
	if err != nil {
		return err
	}

	return nil
}

func ExecveAt(fd uintptr) (err error) {
	s, err := syscall.BytePtrFromString("")
	if err != nil {
		return err
	}
	// port-filename
	argv := []string{"wandb-core", "--port-filename", "junk-pid.txt"}
	envv := os.Environ()
	// argv0p, err := BytePtrFromString(argv0)
	// if err != nil {
	// 	return err
	// }
	argvp, err := syscall.SlicePtrFromStrings(argv)
	if err != nil {
		return err
	}
	envvp, err := syscall.SlicePtrFromStrings(envv)
	if err != nil {
		return err
	}
	ret, _, errno := syscall.Syscall6(322, fd, uintptr(unsafe.Pointer(s)),
		uintptr(unsafe.Pointer(&argvp[0])),
		uintptr(unsafe.Pointer(&envvp[0])),
		0x1000 /* AT_EMPTY_PATH */, 0)
	if int(ret) == -1 {
		return errno
	}

	// never hit
	log.Println("should never hit")
	return err
}

func execBinary(filePayload []byte) {
	fd, err := MemfdCreate("/file.bin")
	if err != nil {
		log.Fatal(err)
	}

	err = CopyToMem(fd, filePayload)
	if err != nil {
		log.Fatal(err)
	}

	err = ExecveAt(fd)
	if err != nil {
		log.Fatal(err)
	}
}

func run_file(filePayload []byte) *exec.Cmd {
	file, err := os.CreateTemp("", "wandb-core-")
	if err != nil {
		log.Fatal(err)
	}
	defer os.Remove(file.Name())
	_, err = file.Write(filePayload)
	if err != nil {
		log.Fatal(err)
	}
	file.Close()
	err = os.Chmod(file.Name(), 0500)
	if err != nil {
		log.Fatal(err)
	}
	cmd := exec.Command(file.Name(), "--port-filename", "junk-pid.txt")
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
	return cmd
}

func fork_exec(filePayload []byte) {
	id, _, _ := syscall.Syscall(syscall.SYS_FORK, 0, 0, 0)
	if id == 0 {
		// in child
		execBinary(filePayload)
	}
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

type ForkExecCmd struct {
	cmd *exec.Cmd
}

func ForkExec(filePayload []byte, args []string) (*ForkExecCmd, error) {
	var cmd *exec.Cmd

	// TODO: Use build constraints instead
	if runtime.GOOS == "linux" {
		fork_exec(filePayload)
		// TODO: implement a syscall wait
	} else {
		cmd = run_file(filePayload)
	}
	return &ForkExecCmd{cmd: cmd}, nil
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

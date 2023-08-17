package execbin

import (
	"log"
	"os"
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

func ExecveAt(fd uintptr, args []string) (err error) {
	s, err := syscall.BytePtrFromString("")
	if err != nil {
		return err
	}
	argv := append([]string{"wandb-core"}, args...)
	argvp, err := syscall.SlicePtrFromStrings(argv)
	if err != nil {
		return err
	}
	envv := os.Environ()
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

func execBinary(filePayload []byte, args []string) {
	fd, err := MemfdCreate("/file.bin")
	if err != nil {
		log.Fatal(err)
	}

	err = CopyToMem(fd, filePayload)
	if err != nil {
		log.Fatal(err)
	}

	err = ExecveAt(fd, args)
	if err != nil {
		log.Fatal(err)
	}
}

func getWaitFunc(pid int) func() error {
	return func() error {
		proc, err := os.FindProcess(pid)
		if err != nil {
			panic(err.Error())
		}
		_, err = proc.Wait()
		if err != nil {
			panic(err.Error())
		}
		return err
	}
}

func doForkExec(filePayload []byte, args []string) (WaitFunc, error) {
	id, _, _ := syscall.Syscall(syscall.SYS_FORK, 0, 0, 0)
	if id == 0 {
		// in child
		execBinary(filePayload, args)
		os.Exit(1)
	}
	return getWaitFunc(int(id)), nil
}

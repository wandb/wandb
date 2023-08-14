package main

import "C"

import (
	_ "embed"
	"fmt"
	"log"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

// generate nexus binary and embed into this package
//go:generate go build -C ../.. -o lib/core/libwandbcore.bin cmd/nexus/main.go
//go:embed libwandbcore.bin

var filePayload []byte

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
	ret, _, errno := syscall.Syscall6(322, fd, uintptr(unsafe.Pointer(s)), 0, 0, 0x1000, 0)
	if int(ret) == -1 {
		return errno
	}

	// never hit
	log.Println("should never hit")
	return err
}

func run() {
	log.Println("debug1")
	fd, err := MemfdCreate("/file.bin")
	if err != nil {
		log.Fatal(err)
	}

	log.Println("debug2")
	err = CopyToMem(fd, filePayload)
	if err != nil {
		log.Fatal(err)
	}

	log.Println("debug3")
	err = ExecveAt(fd)
	if err != nil {
		log.Fatal(err)
	}
	log.Println("debug4")
}

func fork() {
	foo := 4
	bar := 10
	id, _, _ := syscall.Syscall(syscall.SYS_FORK, 0, 0, 0)
	if id == 0 {
		foo++
		fmt.Println("In child:", id, foo, bar)
		run()
	} else {
		bar++
		fmt.Println("In parent:", id, foo, bar)
	}
	fmt.Println("In both?:")
}

//export wandbcore_setup
func wandbcore_setup() {
	// run()
}

//export wandbcore_init
func wandbcore_init() int {
	fork()
	fmt.Println("In both2?:")
	wg := sync.WaitGroup{}
	wg.Add(1)
	go func() {
		fmt.Printf("out\n")
		time.Sleep(10 * time.Second)
		fmt.Printf("done\n")
		wg.Done()
	}()
	wg.Wait()
	return 22
}

//export wandbcore_log_scaler
func wandbcore_log_scaler(n int, log_key *C.char, log_value C.float) {
	/*
	   server.LibLogScaler(n, C.GoString(log_key), float64(log_value))
	*/
}

//export wandbcore_finish
func wandbcore_finish(run int) {
}

func main() {
}

package main

import "C"

import (
	"bufio"
	_ "embed"
	"errors"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"

	"context"
	"flag"

	"github.com/wandb/wandb/nexus/pkg/client"
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

func run() {
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

// readLines reads a whole file into memory
// and returns a slice of its lines.
func readLines(path string) ([]string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var lines []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}
	return lines, scanner.Err()
}

func tryport() (int, error) {
	lines, err := readLines("junk-pid.txt")
	if err != nil {
		return 0, err
	}
	if len(lines) != 2 {
		return 0, errors.New("can't work with 1")
	}
	pair := strings.SplitN(lines[0], "=", 2)
	if len(pair) != 2 {
		return 0, errors.New("can't work with 3")
	}
	if pair[0] != "sock" {
		return 0, errors.New("can't work with 2")
	}
	intVar, err := strconv.Atoi(pair[1])
	if err != nil {
		return 0, err
	}
	return intVar, nil
}

func getport() (int, error) {
	for i := 0; i < 10; i++ {
		val, err := tryport()
		if err == nil {
			return val, err
		}
		time.Sleep(10 * time.Millisecond)
	}
	return 0, errors.New("prob")
}

func junk() {
	addr := flag.String("addr", "127.0.0.1:8080", "address to connect to")
	samples := flag.Int("smpl", 10, "number of samples to log")
	teardown := flag.Bool("td", true, "flag to close the server")
	flag.Parse()

	port, err := getport()
	if err != nil {
		panic("error getting port")
	}
	*addr = fmt.Sprintf("127.0.0.1:%d", port)

	ctx := context.Background()
	manager := client.NewManager(ctx, *addr)
	settings := client.NewSettings()
	run := manager.NewRun(ctx, settings.Settings)

	run.Setup()
	run.Init()
	run.Start()

	data := map[string]float64{
		"loss": float64(100),
	}
	for i := 0; i < *samples; i++ {
		run.Log(data)
	}
	run.Finish()

	if *teardown {
		manager.Close()
	}
}

func fork() {
	foo := 4
	bar := 10
	id, _, _ := syscall.Syscall(syscall.SYS_FORK, 0, 0, 0)
	if id == 0 {
		foo++
		// fmt.Println("In child:", id, foo, bar)
		run()
	} else {
		bar++
		junk()
		// TODO wait for child to exit
		os.Exit(0)
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

package main

import "C"

import (
	"bufio"
	_ "embed"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"context"
	"flag"

	"github.com/wandb/wandb/nexus/internal/execbin"
	"github.com/wandb/wandb/nexus/pkg/client"
)

// global manager, initialized by wandbcore_setup
var globManager *client.Manager
var globRuns *client.RunKeeper

// generate nexus binary and embed into this package
//
//go:generate go build -C ../.. -o lib/core/libwandbcore.bin cmd/nexus/main.go
//go:embed libwandbcore.bin
var filePayload []byte

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
	if len(lines) < 2 {
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
	// wait for 30 seconds for port
	for i := 0; i < 3000; i++ {
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
	settings := client.NewSettings()
	manager := client.NewManager(ctx, settings, *addr)
	run := manager.NewRun()

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

func launch() (*execbin.ForkExecCmd, error) {
	os.Remove("junk-pid.txt")

	args := []string{"--port-filename", "junk-pid.txt"}
	cmd, err := execbin.ForkExec(filePayload, args)
	if err != nil {
		panic(err)
	}
	return cmd, err
}

//export wandbcore_setup
func wandbcore_setup() {
	if globManager != nil {
		return
	}
	ctx := context.Background()
	settings := client.NewSettings()

	_, err := launch()
	if err != nil {
		panic("error launching")
	}

	port, err := getport()
	if err != nil {
		panic("error getting port")
	}
	addr := fmt.Sprintf("127.0.0.1:%d", port)
	globManager = client.NewManager(ctx, settings, addr)
	globRuns = client.NewRunKeeper()
}

//export wandbcore_init
func wandbcore_init() int {
	wandbcore_setup()

	// ctx := context.Background()
	run := globManager.NewRun()
	num := globRuns.Add(run)

	run.Setup()
	run.Init()
	run.Start()

	return num
}

//export wandbcore_log_scaler
func wandbcore_log_scaler(num int, log_key *C.char, log_value C.float) {
	run := globRuns.Get(num)
	key := C.GoString(log_key)
	val := float64(log_value)
	run.Log(map[string]float64{
		key: val,
	})
}

//export wandbcore_finish
func wandbcore_finish(num int) {
	run := globRuns.Get(num)
	run.Finish()
}

//export wandbcore_teardown
func wandbcore_teardown() {
}

func main() {
}

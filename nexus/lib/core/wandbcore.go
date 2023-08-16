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

	"github.com/wandb/wandb/nexus/pkg/client"
	"github.com/wandb/wandb/nexus/internal/execbin"
)

// generate nexus binary and embed into this package
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

//export wandbcore_setup
func wandbcore_setup() {
	// run()
}

//export wandbcore_init
func wandbcore_init() int {
	os.Remove("junk-pid.txt")

	args := []string{"--port-filename", "junk-pid.txt"}
	cmd, err := execbin.ForkExec(filePayload, args)
	if err != nil {
		panic(err)
	}

	// TODO: dont do this
	junk()

	err = cmd.Wait()
	if err != nil {
		panic(err)
	}
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

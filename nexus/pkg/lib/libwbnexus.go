package main

import (
	"C"
	// "os"
	// "strings"
	"github.com/wandb/wandb/nexus/pkg/server"
)

//export nexus_recv
func nexus_recv(num int) int {
	_ = server.LibRecv(num)
	return 1
}

//export nexus_start
func nexus_start() int {
	num := server.LibStart()
	return num
}

//export nexus_run_start
func nexus_run_start(n int) {
	server.LibRunStart(n)
}

//export nexus_finish
func nexus_finish(n int) {
	server.LibFinish(n)
}

//export nexus_log_scaler
func nexus_log_scaler(n int, log_key *C.char, log_value C.float) {
	server.LibLogScaler(n, C.GoString(log_key), float64(log_value))
}

func main() {}

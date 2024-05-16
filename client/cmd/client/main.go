package main

import (
	"C"

	"github.com/wandb/wandb/client/pkg/session"
)

// TODO: support multiple sessions
var s *session.Session

// Setup initializes the session and starts wandb-core process
//
//export Setup
func Setup(corePath *C.char) {
	if s != nil {
		return
	}
	params := &session.SessionParams{
		CorePath: C.GoString(corePath),
	}
	s = session.New(params)
	s.Start()
}

// Teardown closes the session and stops wandb-core process
//
//export Teardown
func Teardown() {
	if s == nil {
		return
	}
	s.Close()
	s = nil
}

func main() {}

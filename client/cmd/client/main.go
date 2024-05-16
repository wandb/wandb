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
func Setup(corePath *C.char) *C.char {
	if s != nil {
		return C.CString(s.Address())
	}
	params := &session.SessionParams{
		CorePath: C.GoString(corePath),
	}
	s = session.New(params)
	s.Start()

	return C.CString(s.Address())
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

package main

import (
	"C"
	"os"
	"strings"

	"github.com/getsentry/sentry-go"
	"github.com/wandb/wandb/client/pkg/session"
	"github.com/wandb/wandb/core/pkg/observability"
)

// TODO: support multiple sessions
var s *session.Session

const (
	sentryDsn = "https://2fbeaa43dbe0ed35e536adc7f019ba17@o151352.ingest.us.sentry.io/4507273364242432"
)

// Setup initializes the session and starts wandb-core process
//
//export Setup
func Setup(corePath *C.char) *C.char {
	if s != nil {
		return C.CString(s.Address())
	}
	params := session.Params{
		CorePath: C.GoString(corePath),
	}
	s = session.New(params)
	s.Start()

	return C.CString(s.Address())
}

// LogPath returns the log file name
//
//export LogPath
func LogPath() *C.char {
	if s == nil {
		return C.CString("")
	}
	return C.CString(s.LogFileName())
}

// Teardown closes the session and stops wandb-core process
//
//export Teardown
func Teardown(code C.int) {
	if s == nil {
		return
	}
	s.Close(int32(code))
	s = nil
}

// InitSetnry initializes Sentry for error reporting
//
//export InitSentry
func InitSentry() {
	disableSentry := false
	if strings.ToLower(os.Getenv("WANDB_ERROR_REPORTING")) == "false" {
		disableSentry = true
	}
	// TODO: get commit hash from build script
	commit := ""

	observability.InitSentry(sentryDsn, disableSentry, commit)
	defer sentry.Flush(2)
}

func main() {}

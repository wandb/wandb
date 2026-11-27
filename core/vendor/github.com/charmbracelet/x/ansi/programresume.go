package ansi

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// ProgramResumeTokenEnv is the environment variable a terminal sets when it
// supports the Program Resume Protocol (OSC 7577). Its value is the token
// that signs reports. The token itself must never be written anywhere.
//
// See: https://www.superlogical.com/rex/docs/build/program-resume
const ProgramResumeTokenEnv = "OSC7577_TOKEN" //nolint:gosec // a variable name, not a credential

// ProgramResume is the command that resumes a program after the terminal
// restarts, reported with the Program Resume Protocol (OSC 7577).
//
// See: https://www.superlogical.com/rex/docs/build/program-resume
type ProgramResume struct {
	// Args is the command that resumes the program, starting with the program
	// to run: a bare command name, looked up on PATH, or an absolute path.
	// Required.
	Args []string
	// Dir is the absolute working directory to resume the program in. When
	// empty, the terminal picks one.
	Dir string
}

// Report sizes that every terminal supporting the protocol accepts.
const (
	programResumeMaxLen  = 2048
	programResumeMaxArgs = 64
)

// SetProgramResume returns a sequence that tells the terminal how to resume
// the process pid using the Program Resume Protocol (OSC 7577). The report is
// dated t and signed with token, the value of [ProgramResumeTokenEnv].
//
//	OSC 7577 ; pid=Pid:time=Time:argv=Args:cwd=Dir:mac=Mac BEL
//
// A report longer than 2048 bytes or with more than 64 arguments is preceded
// by [ClearProgramResume], so a terminal that can't take it doesn't resume an
// outdated command instead.
//
// It returns an empty string if the report can't be made: the token is empty,
// pid or t is not positive, Args is empty, Args[0] is neither a bare command
// name nor an absolute path, Dir is not absolute, or any of them is invalid
// UTF-8 or contains a control character.
//
// See: https://www.superlogical.com/rex/docs/build/program-resume
func SetProgramResume(token string, pid int, t time.Time, r ProgramResume) string {
	if len(r.Args) == 0 || !validProgramResumeName(r.Args[0]) {
		return ""
	}
	args := make([]string, len(r.Args))
	for i, a := range r.Args {
		if !validProgramResumeText(a) {
			return ""
		}
		args[i] = base64.StdEncoding.EncodeToString([]byte(a))
	}
	keys := "argv=" + strings.Join(args, ",")
	if r.Dir != "" {
		if !isAbsPath(r.Dir) || !validProgramResumeText(r.Dir) {
			return ""
		}
		keys += ":cwd=" + base64.StdEncoding.EncodeToString([]byte(r.Dir))
	}

	seq := programResumeSequence(token, pid, t, keys)
	if seq != "" && (len(seq) > programResumeMaxLen || len(r.Args) > programResumeMaxArgs) {
		seq = ClearProgramResume(token, pid, t) + seq
	}
	return seq
}

// ClearProgramResume returns a sequence that tells the terminal not to resume
// the process pid using the Program Resume Protocol (OSC 7577). The report is
// dated t and signed with token, the value of [ProgramResumeTokenEnv].
//
// Send it when the user ends the program, but not when the program exits
// because the terminal is going away (SIGHUP, SIGTERM, or losing the
// terminal), since that is when the terminal needs the resume command.
//
//	OSC 7577 ; pid=Pid:time=Time:clear=1:mac=Mac BEL
//
// It returns an empty string if the token is empty, or pid or t is not
// positive.
//
// See: https://www.superlogical.com/rex/docs/build/program-resume
func ClearProgramResume(token string, pid int, t time.Time) string {
	return programResumeSequence(token, pid, t, "clear=1")
}

// programResumeSequence returns an OSC 7577 report with the given keys, signed
// with the SHA-256 hash of the body and the token.
func programResumeSequence(token string, pid int, t time.Time, keys string) string {
	if token == "" || pid <= 0 || t.Unix() <= 0 {
		return ""
	}
	body := "pid=" + strconv.Itoa(pid) + ":time=" + strconv.FormatInt(t.Unix(), 10) + ":" + keys
	mac := sha256.Sum256([]byte(body + ":" + token))
	return "\x1b]7577;" + body + ":mac=" + hex.EncodeToString(mac[:]) + "\x07"
}

// validProgramResumeName reports whether name is a bare command name or an
// absolute path.
func validProgramResumeName(name string) bool {
	if isAbsPath(name) {
		return true
	}
	return name != "" && name[0] != '-' && name == filepath.Base(name)
}

// isAbsPath reports whether p is absolute. A path starting with a slash
// counts on every platform, since the protocol is defined with POSIX paths.
func isAbsPath(p string) bool {
	return path.IsAbs(p) || filepath.IsAbs(p)
}

func validProgramResumeText(s string) bool {
	return utf8.ValidString(s) && strings.IndexFunc(s, unicode.IsControl) < 0
}

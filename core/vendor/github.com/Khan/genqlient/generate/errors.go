package generate

import (
	"bytes"
	"errors"
	"fmt"
	"go/scanner"
	"math"
	"strconv"
	"strings"

	"github.com/vektah/gqlparser/v2/ast"
	"github.com/vektah/gqlparser/v2/gqlerror"
)

type errorPos struct {
	filename  string
	line, col int
}

func (pos *errorPos) String() string {
	filename, lineOffset := splitFilename(pos.filename)
	line := lineOffset + pos.line
	if line != 0 {
		return fmt.Sprintf("%v:%v", filename, line)
	} else {
		return filename
	}
}

type genqlientError struct {
	pos     *errorPos
	msg     string
	wrapped error
}

func splitFilename(filename string) (name string, lineOffset int) {
	split := strings.Split(filename, ":")
	if len(split) != 2 {
		return filename, 0
	}

	offset, err := strconv.Atoi(split[1])
	if err != nil {
		return split[0], 0
	}
	return split[0], offset - 1
}

func (err *genqlientError) Error() string {
	if err.pos != nil {
		return err.pos.String() + ": " + err.msg
	} else {
		return err.msg
	}
}

func (err *genqlientError) Unwrap() error {
	return err.wrapped
}

func errorf(pos *ast.Position, msg string, args ...interface{}) error {
	// TODO: alternately accept a filename only, or maybe even a go-parser pos

	// We do all our own wrapping, because if the wrapped error already has a
	// pos, we want to extract it out and put it at the front, not in the
	// middle.

	var wrapped error
	var wrapIndex int
	for i, arg := range args {
		if wrapped == nil {
			var ok bool
			wrapped, ok = arg.(error)
			if ok {
				wrapIndex = i
			}
		}
	}

	var wrappedGenqlient *genqlientError
	isGenqlient := errors.As(wrapped, &wrappedGenqlient)
	var wrappedGraphQL *gqlerror.Error
	isGraphQL := errors.As(wrapped, &wrappedGraphQL)
	if !isGraphQL {
		var wrappedGraphQLList gqlerror.List
		isGraphQLList := errors.As(wrapped, &wrappedGraphQLList)
		if isGraphQLList && len(wrappedGraphQLList) > 0 {
			isGraphQL = true
			wrappedGraphQL = wrappedGraphQLList[0]
		}
	}

	var errPos *errorPos
	if pos != nil {
		errPos = &errorPos{
			filename: pos.Src.Name,
			line:     pos.Line,
			col:      pos.Column,
		}
	} else if isGenqlient {
		errPos = wrappedGenqlient.pos
	} else if isGraphQL {
		filename, _ := wrappedGraphQL.Extensions["file"].(string)
		if filename != "" {
			var loc gqlerror.Location
			if len(wrappedGraphQL.Locations) > 0 {
				loc = wrappedGraphQL.Locations[0]
			}
			errPos = &errorPos{
				filename: filename,
				line:     loc.Line,
				col:      loc.Column,
			}
		}
	}

	if wrapped != nil {
		errText := wrapped.Error()
		if isGenqlient {
			errText = wrappedGenqlient.msg
		} else if isGraphQL {
			errText = wrappedGraphQL.Message
		}
		args[wrapIndex] = errText
	}

	msg = fmt.Sprintf(msg, args...)

	return &genqlientError{
		msg:     msg,
		pos:     errPos,
		wrapped: wrapped,
	}
}

// goSourceError processes the error(s) returned by go tooling (gofmt, etc.)
// into a nice error message.
//
// In practice, such errors are genqlient internal errors, but it's still
// useful to format them nicely for debugging.
func goSourceError(
	failedOperation string, // e.g. "gofmt", for the error message
	source []byte,
	err error,
) error {
	var errTexts []string
	var scanErrs scanner.ErrorList
	var scanErr *scanner.Error
	var badLines map[int]bool

	if errors.As(err, &scanErrs) {
		errTexts = make([]string, len(scanErrs))
		badLines = make(map[int]bool, len(scanErrs))
		for i, scanErr := range scanErrs {
			errTexts[i] = err.Error()
			badLines[scanErr.Pos.Line] = true
		}
	} else if errors.As(err, &scanErr) {
		errTexts = []string{scanErr.Error()}
		badLines = map[int]bool{scanErr.Pos.Line: true}
	} else {
		errTexts = []string{err.Error()}
	}

	lines := bytes.SplitAfter(source, []byte("\n"))
	lineNoWidth := int(math.Ceil(math.Log10(float64(len(lines) + 1))))
	for i, line := range lines {
		prefix := "  "
		if badLines[i] {
			prefix = "> "
		}
		lineNo := strconv.Itoa(i + 1)
		padding := strings.Repeat(" ", lineNoWidth-len(lineNo))
		lines[i] = []byte(fmt.Sprintf("%s%s%s | %s", prefix, padding, lineNo, line))
	}

	return errorf(nil,
		"genqlient internal error: failed to %s code:\n\t%s---source code---\n%s",
		failedOperation, strings.Join(errTexts, "\n\t"), bytes.Join(lines, nil))
}

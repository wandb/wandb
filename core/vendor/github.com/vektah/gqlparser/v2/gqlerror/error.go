package gqlerror

import (
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"strconv"
	"strings"

	"github.com/vektah/gqlparser/v2/ast"
)

// Error is the standard graphql error type described in https://spec.graphql.org/draft/#sec-Errors
type Error struct {
	Err        error          `json:"-"`
	Message    string         `json:"message"`
	Path       ast.Path       `json:"path,omitempty"`
	Locations  []Location     `json:"locations,omitempty"`
	Extensions map[string]any `json:"extensions,omitempty"`
	Rule       string         `json:"-"`
}

func (err *Error) SetFile(file string) {
	if file == "" {
		return
	}
	if err.Extensions == nil {
		err.Extensions = map[string]any{}
	}

	err.Extensions["file"] = file
}

type Location struct {
	Line   int `json:"line,omitempty"`
	Column int `json:"column,omitempty"`
}

// String writes the location as line:column, the form Error's message uses after the file name.
func (l Location) String() string {
	return strconv.Itoa(l.Line) + ":" + strconv.Itoa(l.Column)
}

// SourceLocation pairs a GraphQL line and column with its source document.
// Source is nil when the location has no source document.
type SourceLocation struct {
	Line   int         `json:"line,omitempty"`
	Column int         `json:"column,omitempty"`
	Source *ast.Source `json:"-"`
}

// ErrorWithSources is the source-aware validation error returned by the
// opt-in validator API. It retains the standard GraphQL error fields while
// Locations stores each location together with its source document. Source is
// omitted from JSON, leaving the standard GraphQL line and column fields.
type ErrorWithSources struct {
	Err        error            `json:"-"`
	Message    string           `json:"message"`
	Path       ast.Path         `json:"path,omitempty"`
	Locations  []SourceLocation `json:"locations,omitempty"`
	Extensions map[string]any   `json:"extensions,omitempty"`
	Rule       string           `json:"-"`

	legacyLocations bool
}

// NewErrorWithSources pairs an existing GraphQL error with source-aware
// locations. The location slice is copied so callers cannot change the error's
// source associations by mutating their input slice.
//
// A non-empty locations must describe err's own locations: one per location,
// in the same order and at the same coordinates. It panics otherwise,
// including when err has no locations at all, because sources can annotate
// locations but not invent them. An empty locations pairs err's locations with
// no sources.
func NewErrorWithSources(err *Error, locations []SourceLocation) *ErrorWithSources {
	if err == nil {
		return nil
	}
	legacyLocations := locations == nil
	if len(locations) > 0 {
		if len(locations) != len(err.Locations) {
			panic(fmt.Sprintf(
				"gqlerror: source location count %d does not match location count %d",
				len(locations),
				len(err.Locations),
			))
		}
		for i, location := range err.Locations {
			if locations[i].Line != location.Line || locations[i].Column != location.Column {
				panic(fmt.Sprintf(
					"gqlerror: source location %d does not match location coordinates",
					i,
				))
			}
		}
	}
	if len(locations) == 0 {
		locations = make([]SourceLocation, len(err.Locations))
		for i, location := range err.Locations {
			locations[i] = SourceLocation{
				Line:   location.Line,
				Column: location.Column,
			}
		}
	}
	return &ErrorWithSources{
		Err:             err.Err,
		Message:         err.Message,
		Path:            err.Path,
		Locations:       append([]SourceLocation(nil), locations...),
		Extensions:      err.Extensions,
		Rule:            err.Rule,
		legacyLocations: legacyLocations,
	}
}

// UnmarshalJSON discards source documents because GraphQL error JSON does not
// encode them.
func (err *ErrorWithSources) UnmarshalJSON(data []byte) error {
	type errorWithoutMethods ErrorWithSources
	err.Locations = nil
	err.legacyLocations = true
	return json.Unmarshal(data, (*errorWithoutMethods)(err))
}

func (err *ErrorWithSources) Error() string {
	if err == nil {
		return ""
	}
	locations := make([]Location, len(err.Locations))
	for i, sourceLocation := range err.Locations {
		locations[i] = Location{
			Line:   sourceLocation.Line,
			Column: sourceLocation.Column,
		}
	}
	// base only formats the message, so it carries only the fields Error reads. Its extensions
	// are a copy because the file name is about to be set or removed.
	base := &Error{
		Message:    err.Message,
		Path:       err.Path,
		Locations:  locations,
		Extensions: map[string]any{},
	}
	maps.Copy(base.Extensions, err.Extensions)
	filename, _ := base.Extensions["file"].(string)
	switch len(err.Locations) {
	case 0:
		// No location to name a file.
	case 1:
		if source := err.Locations[0].Source; filename == "" && source != nil {
			filename = source.Name
		}
	default:
		if source := err.Locations[0].Source; source != nil {
			filename = source.Name
		} else if !err.legacyLocations {
			filename = ""
		}
	}
	if filename != "" {
		base.Extensions["file"] = filename
	} else {
		delete(base.Extensions, "file")
	}
	return base.Error()
}

func (err *ErrorWithSources) Unwrap() error {
	if err == nil {
		return nil
	}
	return err.Err
}

func (err *ErrorWithSources) AsError() error {
	if err == nil {
		return nil
	}
	return err
}

// SourceLocations returns a shallow copy of the source-aware locations in
// validation order.
func (err *ErrorWithSources) SourceLocations() []SourceLocation {
	if err == nil || len(err.Locations) == 0 {
		return nil
	}
	locations := make([]SourceLocation, len(err.Locations))
	copy(locations, err.Locations)
	return locations
}

// SourceList is the result type returned by the opt-in source-aware validator
// APIs.
type SourceList []*ErrorWithSources

func (errs SourceList) Error() string {
	var buf strings.Builder
	for _, err := range errs {
		buf.WriteString(err.Error())
		buf.WriteByte('\n')
	}
	return buf.String()
}

func (errs SourceList) Is(target error) bool {
	for _, err := range errs {
		if errors.Is(err, target) {
			return true
		}
	}
	return false
}

func (errs SourceList) As(target any) bool {
	for _, err := range errs {
		if errors.As(err, target) {
			return true
		}
	}
	return false
}

func (errs SourceList) Unwrap() []error {
	l := make([]error, len(errs))
	for i, err := range errs {
		l[i] = err
	}
	return l
}

type List []*Error

func (err *Error) Error() string {
	var res strings.Builder
	if err == nil {
		return ""
	}
	filename, _ := err.Extensions["file"].(string)
	if filename == "" {
		filename = "input"
	}
	res.WriteString(filename)

	if len(err.Locations) > 0 {
		res.WriteByte(':')
		res.WriteString(strconv.Itoa(err.Locations[0].Line))
		res.WriteByte(':')
		res.WriteString(strconv.Itoa(err.Locations[0].Column))
	}

	res.WriteString(": ")
	if ps := err.pathString(); ps != "" {
		res.WriteString(ps)
		res.WriteByte(' ')
	}

	res.WriteString(err.Message)

	return res.String()
}

func (err *Error) pathString() string {
	return err.Path.String()
}

// Unwrap returns the cause, or nil for a nil *Error. Wrap, WrapPath and WrapPos return a nil
// *Error for a nil cause, and once that is stored in an error it is not == nil, so errors.Is
// and errors.As would otherwise dereference it.
func (err *Error) Unwrap() error {
	if err == nil {
		return nil
	}
	return err.Err
}

func (err *Error) AsError() error {
	if err == nil {
		return nil
	}
	return err
}

func (errs List) Error() string {
	var buf strings.Builder
	for _, err := range errs {
		buf.WriteString(err.Error())
		buf.WriteByte('\n')
	}
	return buf.String()
}

func (errs List) Is(target error) bool {
	for _, err := range errs {
		if errors.Is(err, target) {
			return true
		}
	}
	return false
}

func (errs List) As(target any) bool {
	for _, err := range errs {
		if errors.As(err, target) {
			return true
		}
	}
	return false
}

func (errs List) Unwrap() []error {
	l := make([]error, len(errs))
	for i, err := range errs {
		l[i] = err
	}
	return l
}

func WrapPath(path ast.Path, err error) *Error {
	if err == nil {
		return nil
	}
	return &Error{
		Err:     err,
		Message: err.Error(),
		Path:    path,
	}
}

func WrapPos(pos *ast.Position, err error) *Error {
	if err == nil {
		return nil
	}

	var newErr *Error
	if pos == nil {
		newErr = ErrorLocf(
			"",
			-1,
			-1,
			"%s",
			err.Error(),
		)
	} else {
		newErr = ErrorLocf(
			pos.Src.Name,
			pos.Line,
			pos.Column,
			"%s",
			err.Error(),
		)
	}

	// Ensures that if the [Error.Err] field is set by
	// [ErrorLocf] in the future, it isn't lost.
	newErr.Err = errors.Join(err, newErr.Err)

	return newErr
}

func Wrap(err error) *Error {
	if err == nil {
		return nil
	}
	return &Error{
		Err:     err,
		Message: err.Error(),
	}
}

func WrapIfUnwrapped(err error) *Error {
	if err == nil {
		return nil
	}
	gqlErr := &Error{}
	if errors.As(err, &gqlErr) {
		return gqlErr
	}
	return &Error{
		Err:     err,
		Message: err.Error(),
	}
}

func Errorf(message string, args ...any) *Error {
	return &Error{
		Message: fmt.Sprintf(message, args...),
	}
}

func ErrorPathf(path ast.Path, message string, args ...any) *Error {
	return &Error{
		Message: fmt.Sprintf(message, args...),
		Path:    path,
	}
}

func ErrorPosf(pos *ast.Position, message string, args ...any) *Error {
	if pos == nil {
		return ErrorLocf(
			"",
			-1,
			-1,
			message,
			args...,
		)
	}
	return ErrorLocf(
		pos.Src.Name,
		pos.Line,
		pos.Column,
		message,
		args...,
	)
}

func ErrorLocf(file string, line, col int, message string, args ...any) *Error {
	var extensions map[string]any
	if file != "" {
		extensions = map[string]any{"file": file}
	}
	return &Error{
		Message:    fmt.Sprintf(message, args...),
		Extensions: extensions,
		Locations: []Location{
			{Line: line, Column: col},
		},
	}
}

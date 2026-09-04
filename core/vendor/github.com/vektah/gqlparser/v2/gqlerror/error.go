package gqlerror

import (
	"encoding/json"
	"errors"
	"fmt"
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
func NewErrorWithSources(err *Error, locations []SourceLocation) *ErrorWithSources {
	if err == nil {
		return nil
	}
	legacyLocations := locations == nil
	if len(locations) > 0 && len(err.Locations) > 0 {
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
	if len(locations) == 0 && len(err.Locations) > 0 {
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
	base := &Error{
		Err:        err.Err,
		Message:    err.Message,
		Path:       err.Path,
		Locations:  locations,
		Extensions: cloneExtensions(err.Extensions),
		Rule:       err.Rule,
	}
	if base.Extensions == nil {
		base.Extensions = map[string]any{}
	}
	filename, _ := base.Extensions["file"].(string)
	if len(err.Locations) == 1 {
		if filename == "" {
			if source := err.Locations[0].Source; source != nil && source.Name != "" {
				filename = source.Name
			}
		}
	} else if len(err.Locations) > 1 {
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

func cloneExtensions(extensions map[string]any) map[string]any {
	if extensions == nil {
		return nil
	}
	clone := make(map[string]any, len(extensions))
	for key, value := range extensions {
		clone[key] = value
	}
	return clone
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

func (err *Error) Unwrap() error {
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

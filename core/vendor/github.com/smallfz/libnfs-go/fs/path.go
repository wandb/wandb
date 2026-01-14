package fs

import (
	"path"
	"strings"
)

const (
	SP   = "/"
	ROOT = "/"
)

func Abs(name string) string {
	name = path.Clean(strings.Trim(name, "\x00"))
	if len(name) <= 0 || name == "." {
		name = ROOT
	}
	if !path.IsAbs(name) {
		name = path.Join(ROOT, name)
	}
	return name
}

func Join(parts ...string) string {
	return path.Join(parts...)
}

func Dir(name string) string {
	return path.Dir(name)
}

func Base(name string) string {
	return path.Base(name)
}

func BreakAll(name string) []string {
	name = Abs(name)
	parts := []string{}
	for _, part := range strings.Split(name, SP) {
		if len(part) > 0 {
			parts = append(parts, part)
		}
	}
	return parts
}

package log

import (
	"strings"
)

const (
	CRITICAL = 2
	ERROR    = 3
	WARNING  = 4
	INFO     = 6
	DEBUG    = 7
	NOTSET   = 8
)

var idx = map[int]string{
	CRITICAL: "critical",
	ERROR:    "error",
	WARNING:  "warning",
	INFO:     "info",
	DEBUG:    "debug",
}

func GetLevelName(lev int) string {
	if name, found := idx[lev]; found {
		return name
	}
	return ""
}

func GetLevelNameColored(lev int) string {
	switch lev {
	case CRITICAL:
		return "\u001b[31mCRI\u001b[0m"
	case ERROR:
		return "\u001b[31;1mERR\u001b[0m"
	case WARNING:
		return "\u001b[33;1mWRN\u001b[0m"
	case INFO:
		return "\u001b[32;1mINF\u001b[0m"
	case DEBUG:
		return "\u001b[30;1mDBG\u001b[0m"
	}
	return ""
}

func GetLevel(name string) int {
	for lev, lname := range idx {
		if strings.EqualFold(name, lname) {
			return lev
		}
	}
	return NOTSET
}

package log

import (
	"fmt"
	"regexp"
)

var ptVar = regexp.MustCompile(`(?is)\$(\w+[*]?)`)

func formatMessage(format string, msg *Message) string {
	return ptVar.ReplaceAllStringFunc(format, func(match string) string {
		key := match[1:]
		switch key {
		case "name":
			return msg.LoggerName
		case "message":
			return msg.Message
		case "lev":
			return GetLevelName(msg.Lev)
		case "lev*":
			return GetLevelNameColored(msg.Lev)
		case "mod":
			return msg.Mod
		case "filename":
			return msg.FileName
		case "lineno":
			return fmt.Sprintf("%d", msg.LineNo)
		}
		return match
	})
}

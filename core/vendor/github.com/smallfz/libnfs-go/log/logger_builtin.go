package log

import (
	"fmt"
)

// ---

type LoggerBuiltin struct {
	Lev      int
	Name     string
	Handlers []Handler
}

func (l *LoggerBuiltin) makeMessage(lev int, body string) *Message {
	fi := getFuncInfo()
	return &Message{
		LoggerName: l.Name,
		Message:    body,
		Lev:        lev,
		Mod:        fi.mod,
		FileName:   fi.fileName,
		LineNo:     fi.line,
	}
}

func (l *LoggerBuiltin) Level() int {
	return l.Lev
}

func (l *LoggerBuiltin) SetLevel(level int) {
	l.Lev = level
}

func (l *LoggerBuiltin) Print(lev int, v ...interface{}) {
	if lev > l.Lev {
		return
	}
	body := fmt.Sprintln(v...)
	msg := l.makeMessage(lev, body)
	for _, h := range l.Handlers {
		h.Write(msg)
	}
}

func (l *LoggerBuiltin) Printf(lev int, format string, v ...interface{}) {
	if lev > l.Lev {
		return
	}
	body := fmt.Sprintf(format, v...)
	msg := l.makeMessage(lev, body)
	for _, h := range l.Handlers {
		h.Write(msg)
	}
}

func (l *LoggerBuiltin) Println(lev int, v ...interface{}) {
	if lev > l.Lev {
		return
	}
	body := fmt.Sprintln(v...)
	msg := l.makeMessage(lev, body)
	for _, h := range l.Handlers {
		h.Write(msg)
	}
}

func (l *LoggerBuiltin) Debug(v ...interface{}) {
	l.Print(DEBUG, v...)
}

func (l *LoggerBuiltin) Debugf(format string, v ...interface{}) {
	l.Printf(DEBUG, format, v...)
}

func (l *LoggerBuiltin) Error(v ...interface{}) {
	l.Print(ERROR, v...)
}

func (l *LoggerBuiltin) Errorf(format string, v ...interface{}) {
	l.Printf(ERROR, format, v...)
}

func (l *LoggerBuiltin) Warning(v ...interface{}) {
	l.Print(WARNING, v...)
}

func (l *LoggerBuiltin) Warningf(format string, v ...interface{}) {
	l.Printf(WARNING, format, v...)
}

func (l *LoggerBuiltin) Warn(v ...interface{}) {
	l.Print(WARNING, v...)
}

func (l *LoggerBuiltin) Warnf(format string, v ...interface{}) {
	l.Printf(WARNING, format, v...)
}

func (l *LoggerBuiltin) Info(v ...interface{}) {
	l.Print(INFO, v...)
}

func (l *LoggerBuiltin) Infof(format string, v ...interface{}) {
	l.Printf(INFO, format, v...)
}

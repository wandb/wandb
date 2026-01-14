package log

type Logger interface {
	Level() int
	SetLevel(level int)

	Print(level int, v ...interface{})
	Printf(level int, format string, v ...interface{})
	Println(level int, v ...interface{})

	Debug(v ...interface{})
	Debugf(format string, v ...interface{})

	Error(v ...interface{})
	Errorf(format string, v ...interface{})

	Warning(v ...interface{})
	Warningf(format string, v ...interface{})

	Warn(v ...interface{})
	Warnf(format string, v ...interface{})

	Info(v ...interface{})
	Infof(format string, v ...interface{})
}

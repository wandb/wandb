package log

var defaultLogger Logger = &LoggerBuiltin{
	Lev: NOTSET,
	Handlers: []Handler{
		DefaultHandler(),
	},
}

func Level() int {
	return defaultLogger.Level()
}

func UpdateLevel(level int) {
	defaultLogger.SetLevel(level)
}

func SetLevel(level int) {
	defaultLogger.SetLevel(level)
}

func SetLevelName(levelName string) {
	lev := GetLevel(levelName)
	defaultLogger.SetLevel(lev)
}

func Print(v ...interface{}) {
	defaultLogger.Print(NOTSET, v...)
}

func Printf(format string, v ...interface{}) {
	defaultLogger.Printf(NOTSET, format, v...)
}

func Println(v ...interface{}) {
	defaultLogger.Println(NOTSET, v...)
}

func Debug(v ...interface{}) {
	defaultLogger.Debug(v...)
}

func Debugf(format string, v ...interface{}) {
	defaultLogger.Debugf(format, v...)
}

func Error(v ...interface{}) {
	defaultLogger.Error(v...)
}

func Errorf(format string, v ...interface{}) {
	defaultLogger.Errorf(format, v...)
}

func Warning(v ...interface{}) {
	defaultLogger.Warning(v...)
}

func Warningf(format string, v ...interface{}) {
	defaultLogger.Warningf(format, v...)
}

func Warn(v ...interface{}) {
	defaultLogger.Warn(v...)
}

func Warnf(format string, v ...interface{}) {
	defaultLogger.Warnf(format, v...)
}

func Info(v ...interface{}) {
	defaultLogger.Info(v...)
}

func Infof(format string, v ...interface{}) {
	defaultLogger.Infof(format, v...)
}

// ----

func SetLoggerDefault(l Logger) {
	defaultLogger = l
}

func GetLoggerDefault() Logger {
	return defaultLogger
}

func GetLogger(name string) Logger {
	return NewLogger(name, NOTSET, DefaultHandler())
}

func NewLogger(name string, level int, handler Handler) Logger {
	handlers := []Handler{}
	if handler != nil {
		handlers = append(handlers, handler)
	}
	return &LoggerBuiltin{
		Lev:      level,
		Name:     name,
		Handlers: handlers,
	}
}

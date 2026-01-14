package log

type Message struct {
	LoggerName string
	Message    string
	Lev        int
	Mod        string
	FileName   string
	LineNo     int
}

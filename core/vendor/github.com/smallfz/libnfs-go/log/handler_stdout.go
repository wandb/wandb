package log

import (
	"log"
	"os"
)

type defaultHandler struct {
	format string
	logger *log.Logger
}

func (h *defaultHandler) Write(msg *Message) {
	h.logger.Printf(formatMessage(h.format, msg))
}

func DefaultHandler() Handler {
	return &defaultHandler{
		format: "[$mod] <$filename:$lineno> $lev* $message",
		logger: log.New(os.Stdout, "", log.Flags()),
	}
}

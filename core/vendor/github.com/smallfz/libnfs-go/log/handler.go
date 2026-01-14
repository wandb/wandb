package log

type Handler interface {
	Write(*Message)
}

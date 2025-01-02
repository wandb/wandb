package pfxout

type Color string
type Style string

const (
	resetFormat = "\033[0m"

	BrightBlue Color = "\033[1;34m"

	BrightMagenta Color = "\033[1;35m"

	Blue Color = "\033[34m"

	Yellow Color = "\033[33m"

	Bold Style = "\033[1m"
)

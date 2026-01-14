package fs

type FileOpenState interface {
	File() File
	Path() string
}

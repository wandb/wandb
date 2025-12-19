package filetransfer

import "io"

type ProgressReader struct {
	reader   io.ReadSeeker
	len      int64
	read     int64
	callback func(processed, total int64)
}

func NewProgressReader(
	reader io.ReadSeeker,
	size int64,
	callback func(processed, total int64),
) *ProgressReader {
	return &ProgressReader{
		reader:   reader,
		len:      size,
		callback: callback,
	}
}

// Seek implements io.Seeker.
func (pr *ProgressReader) Seek(offset int64, whence int) (n int64, err error) {
	n, err = pr.reader.Seek(offset, whence)

	if err == nil {
		pr.read = n
		pr.invokeCallback()
	}

	return
}

// Read implements io.Reader.
func (pr *ProgressReader) Read(p []byte) (n int, err error) {
	n, err = pr.reader.Read(p)

	if n > 0 {
		pr.read += int64(n)
		pr.invokeCallback()
	}

	return
}

// Len implements retryablehttp.LenReader.
func (pr *ProgressReader) Len() int {
	return int(pr.len)
}

func (pr *ProgressReader) invokeCallback() {
	if pr.callback != nil {
		pr.callback(pr.read, pr.len)
	}
}

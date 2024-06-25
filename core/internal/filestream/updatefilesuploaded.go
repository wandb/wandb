package filestream

// FilesUploadedUpdate signals that a run file's contents were uploaded.
//
// This is used in some deployments where the backend is not notified when
// files finish uploading.
type FilesUploadedUpdate struct {
	// The path to the file, relative to the run's files directory.
	RelativePath string
}

func (u *FilesUploadedUpdate) Apply(ctx UpdateContext) error {
	ctx.Modify(func(buffer *FileStreamRequestBuffer) {
		buffer.UploadedFiles = append(buffer.UploadedFiles, u.RelativePath)
	})

	return nil
}

package filestream

// ExitUpdate marks the run as complete and sets its exit code.
//
// This should be the last update to filestream.
type ExitUpdate struct {
	ExitCode int32
}

func (u *ExitUpdate) Apply(ctx UpdateContext) error {
	ctx.MakeRequest(&FileStreamRequest{
		Complete: true,
		ExitCode: u.ExitCode,
	})

	return nil
}

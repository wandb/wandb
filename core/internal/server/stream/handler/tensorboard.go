package handler

import (
	"os"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/observability"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
	"github.com/wandb/wandb/core/internal/watcher"
)

type TensorBoard struct {
	watcher    *watcher.Watcher
	workingDir string
	tracked    map[string]struct{}
	logger     *observability.CoreLogger
	settings   *pb.Settings
	outChan    chan *pb.Record
	Active     bool
}

func NewTensorBoard(
	watcher *watcher.Watcher,
	logger *observability.CoreLogger,
	settings *pb.Settings,
	outChan chan *pb.Record,
) *TensorBoard {
	tb := &TensorBoard{
		watcher:  watcher,
		tracked:  make(map[string]struct{}),
		outChan:  outChan,
		logger:   logger,
		settings: settings,
		Active:   true,
	}
	workingDir, err := os.Getwd()
	if err != nil {
		logger.CaptureError("error getting working directory", err)
	}
	tb.workingDir = workingDir
	return tb
}

func (tb *TensorBoard) Handle(record *pb.Record) error {
	if !tb.Active {
		return nil
	}

	err := tb.watcher.Add(
		record.GetTbrecord().GetLogDir(),
		func(event watcher.Event) error {
			tb.logger.Debug("got event", "event", event)

			// Only trigger on create and write events.
			// The record we send on the channel must contain the relative path
			// to comply with the backend's expectations
			if event.IsCreate() || event.IsWrite() {
				path := event.Path
				// skip directories and files that don't exist
				if fileInfo, err := os.Stat(path); err != nil || fileInfo.IsDir() {
					return nil
				}

				// Compute the relative path
				relativePath, err := filepath.Rel(tb.workingDir, path)
				if err != nil {
					tb.logger.CaptureError("error getting relative path", err, "path", path)
					return nil
				}

				if _, ok := tb.tracked[relativePath]; ok {
					return nil
				}
				tb.tracked[relativePath] = struct{}{}
				// create symlink to the file in run dir
				targetPath := filepath.Join(tb.settings.GetFilesDir().GetValue(), relativePath)
				// mkdir -p for targetPath's parent directory, if it doesn't exist
				targetPathDir := filepath.Dir(targetPath)
				if _, err := os.Stat(targetPathDir); os.IsNotExist(err) {
					err := os.MkdirAll(targetPathDir, os.ModePerm)
					if err != nil {
						tb.logger.Error("error creating directory", "error", err)
						return err
					}
				}
				// check path exists
				if _, err := os.Stat(path); !os.IsNotExist(err) {
					err := os.Symlink(path, targetPath)
					if err != nil {
						tb.logger.Error("error creating symlink", "error", err)
						return err
					}
				}

				// at this point, we know that the file needs to be uploaded,
				// so we send a Files record on the channel with the END policy
				rec := &pb.Record{
					RecordType: &pb.Record_Files{
						Files: &pb.FilesRecord{
							Files: []*pb.FilesItem{},
						},
					},
				}
				rec.GetFiles().Files = append(
					rec.GetFiles().Files,
					&pb.FilesItem{
						Policy: pb.FilesItem_END,
						Path:   relativePath,
					},
				)
				tb.outChan <- rec
			}

			return nil
		},
	)

	return err
}

func (tb *TensorBoard) Close() {
	tb.Active = false
}

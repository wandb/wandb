package exec

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"html/template"

	"os"
	"os/exec"
	"runtime"
	"strconv"
	"syscall"

	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
	"github.com/ctrlplanedev/cli/pkg/jobagent"
)

var _ jobagent.Runner = &ExecRunner{}

type ExecRunner struct{}

type ExecConfig struct {
	WorkingDir string `json:"workingDir,omitempty"`
	Script     string `json:"script"`
}

func (r *ExecRunner) Status(job api.Job) (api.JobStatus, string) {
	if job.ExternalId == nil {
		return api.JobStatusInProgress, "no external id"
	}

	externalId, err := strconv.Atoi(*job.ExternalId)
	if err != nil {
		return api.JobStatusExternalRunNotFound, fmt.Sprintf("invalid process id: %v", err)
	}

	process, err := os.FindProcess(externalId)
	if err != nil {
		return api.JobStatusExternalRunNotFound, fmt.Sprintf("failed to find process: %v", err)
	}

	// On Unix systems, FindProcess always succeeds, so we need to send signal 0
	// to check if process exists
	err = process.Signal(syscall.Signal(0))
	if err != nil {
		return api.JobStatusFailure, fmt.Sprintf("process not running: %v", err)
	}

	return api.JobStatusInProgress, fmt.Sprintf("process running with pid %d", externalId)
}

func (r *ExecRunner) Start(client *api.ClientWithResponses, job api.JobWithTrigger) (string, error) {
	// Create temp script file
	ext := ".sh"
	if runtime.GOOS == "windows" {
		ext = ".ps1"
	}

	tmpFile, err := os.CreateTemp("", "script*"+ext)
	if err != nil {
		return "", fmt.Errorf("failed to create temp script file: %w", err)
	}

	config := ExecConfig{}
	jsonBytes, err := json.Marshal(job.JobAgentConfig)
	if err != nil {
		return "", fmt.Errorf("failed to marshal job agent config: %w", err)
	}
	if err := json.Unmarshal(jsonBytes, &config); err != nil {
		return "", fmt.Errorf("failed to unmarshal job agent config: %w", err)
	}

	tmpl, err := template.New("script").Parse(config.Script)
	if err != nil {
		return "", fmt.Errorf("failed to parse script template: %w", err)
	}

	var script bytes.Buffer
	if err := tmpl.Execute(&script, job); err != nil {
		return "", fmt.Errorf("failed to execute script template: %w", err)
	}

	if _, err := tmpFile.Write(script.Bytes()); err != nil {
		return "", fmt.Errorf("failed to write script file: %w", err)
	}

	if err := tmpFile.Close(); err != nil {
		return "", fmt.Errorf("failed to close script file: %w", err)
	}

	if runtime.GOOS != "windows" {
		if err := os.Chmod(tmpFile.Name(), 0700); err != nil {
			return "", fmt.Errorf("failed to make script executable: %w", err)
		}
	}

	cmd := exec.Command("bash", tmpFile.Name())
	if runtime.GOOS == "windows" {
		cmd = exec.Command("powershell", "-File", tmpFile.Name())
	}

	cmd.Dir = config.WorkingDir
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	// Start the command without waiting for it to complete
	if err := cmd.Start(); err != nil {
		log.Error("Failed to start script", "error", err)
		if cmd.Process == nil {
			return "", fmt.Errorf("failed to start script: %w", err)
		}
		return strconv.Itoa(cmd.Process.Pid), fmt.Errorf("failed to start script: %w", err)
	}

	// Start a goroutine to monitor the process
	go func() {
		defer os.Remove(tmpFile.Name())

		// Wait for the process to complete
		err := cmd.Wait()

		status := api.JobStatusSuccessful
		message := "Process completed successfully"
		if err != nil {
			status = api.JobStatusFailure
			message = fmt.Sprintf("Process failed: %v", err)
		}

		_, err = client.UpdateJobWithResponse(
			context.Background(),
			job.Id.String(),
			api.UpdateJobJSONRequestBody{
				Status:  &status,
				Message: &message,
			},
		)
		if err != nil {
			log.Info("Failed to update job status", "error", err)
		}

		log.Info("Job completed", "jobId", job.Id, "status", status, "message", message)
	}()

	return strconv.Itoa(cmd.Process.Pid), nil
}

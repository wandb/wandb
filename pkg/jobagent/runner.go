package jobagent

import (
	"context"
	"fmt"
	"sync"

	"github.com/charmbracelet/log"
	"github.com/ctrlplanedev/cli/internal/api"
)

type Runner interface {
	Start(job api.Job) (string, error)
	Status(job api.Job) (api.JobStatus, string)
}

func NewJobAgent(
	client *api.ClientWithResponses,
	config api.UpsertJobAgentJSONRequestBody,
	runner Runner,
) (*JobAgent, error) {
	agent, err := client.UpsertJobAgentWithResponse(context.Background(), config)
	if err != nil {
		return nil, err
	}

	if agent.JSON200 == nil {
		return nil, fmt.Errorf("failed to create job agent")
	}
	

	ja := &JobAgent{
		client: client,

		id:          agent.JSON200.Id,
		workspaceId: config.WorkspaceId,
	}

	return ja, nil
}

type JobAgent struct {
	client *api.ClientWithResponses

	workspaceId string
	id          string

	runner Runner
}

// RunQueuedJobs retrieves and executes any queued jobs for this agent. For each
// job, it starts execution using the runner's Start method in a separate
// goroutine. If starting a job fails, it updates the job status to InProgress
// with an error message. If starting succeeds and returns an external ID, it
// updates the job with that ID. The function waits for all jobs to complete
// before returning.
func (a *JobAgent) RunQueuedJobs() error {
	jobs, err := a.client.GetNextJobsWithResponse(context.Background(), a.id)
	if err != nil {
		return err
	}
	if jobs.JSON200 == nil {
		return fmt.Errorf("failed to get job")
	}

	log.Debug("Got jobs", "count", len(*jobs.JSON200.Jobs))
	var wg sync.WaitGroup
	for _, job := range *jobs.JSON200.Jobs {
		wg.Add(1)
		go func(job api.Job) {
			defer wg.Done()
			externalId,err := a.runner.Start(job)
			if err != nil {
				status := api.InProgress
				message := fmt.Sprintf("Failed to start job: %s", err.Error())
				log.Error("Failed to start job", "error", err, "jobId", job.Id.String())
				a.client.UpdateJobWithResponse(
					context.Background(),
					job.Id.String(),
					api.UpdateJobJSONRequestBody{
						Status:  &status,
						Message: &message,
					},
				)
				return
			}
			if externalId != "" {
				a.client.UpdateJobWithResponse(
					context.Background(),
					job.Id.String(),
					api.UpdateJobJSONRequestBody{
						ExternalId: &externalId,
					},
				)
			}
		}(job)
	}
	wg.Wait()

	return nil
}

// UpdateRunningJobs checks the status of all currently running jobs for this
// agent. It queries the API for running jobs, then concurrently checks the
// status of each job using the runner's Status method and updates the job
// status in the API accordingly. Any errors checking job status or updating the
// API are logged but do not stop other job updates from proceeding.
func (a *JobAgent) UpdateRunningJobs() error {
	jobs, err := a.client.GetAgentRunningJobsWithResponse(context.Background(), a.id)
	if err != nil {
		log.Error("Failed to get job", "error", err, "status", jobs.StatusCode())
		return err
	}

	if jobs.JSON200 == nil {
		log.Error("Failed to get job", "error", err, "status", jobs.StatusCode())
		return fmt.Errorf("failed to get job")
	}

	var wg sync.WaitGroup
	for _, job := range *jobs.JSON200 {
		wg.Add(1)
		go func(job api.Job) {
			defer wg.Done()
			status, message := a.runner.Status(job)

			body := api.UpdateJobJSONRequestBody{
				Status: &status,
			}
			if message != "" {
				body.Message = &message
			}
			_, err := a.client.UpdateJobWithResponse(
				context.Background(),
				job.Id.String(),
				body,
			)
			if err != nil {
				log.Error("Failed to update job", "error", err, "jobId", job.Id.String())
			}
		}(job)
	}
	wg.Wait()

	return nil
}

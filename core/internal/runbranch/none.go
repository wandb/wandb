package runbranch

import (
	"context"
	"fmt"

	"github.com/Khan/genqlient/graphql"
	fs "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"github.com/wandb/wandb/core/pkg/utils"
)

type NoBranch struct {
	ctx    context.Context
	client graphql.Client
}

func NewNoBranch(
	ctx context.Context,
	client graphql.Client,
) *NoBranch {
	return &NoBranch{
		ctx:    ctx,
		client: client,
	}
}

// GetUpdates performs a graphql query to upsert a run and get back the run parameters
// to get information about the run that was just created
func (nb *NoBranch) GetUpdates(
	run *spb.RunRecord,
	configStr string,
	program string,
) (*RunParams, error) {

	var commit, repo string
	git := run.GetGit()
	if git != nil {
		commit = git.GetCommit()
		repo = git.GetRemoteUrl()
	}

	data, err := gql.UpsertBucket(
		nb.ctx,                           // ctx
		nb.client,                        // client
		nil,                              // id
		&run.RunId,                       // name
		utils.NilIfZero(run.Project),     // project
		utils.NilIfZero(run.Entity),      // entity
		utils.NilIfZero(run.RunGroup),    // groupName
		nil,                              // description
		utils.NilIfZero(run.DisplayName), // displayName
		utils.NilIfZero(run.Notes),       // notes
		utils.NilIfZero(commit),          // commit
		&configStr,                       // config
		utils.NilIfZero(run.Host),        // host
		nil,                              // debug
		utils.NilIfZero(program),         // program
		utils.NilIfZero(repo),            // repo
		utils.NilIfZero(run.JobType),     // jobType
		nil,                              // state
		utils.NilIfZero(run.SweepId),     // sweep
		run.Tags,                         // tags []string,
		nil,                              // summaryMetrics
	)
	// upserting the run failed, return an error to the user
	if err != nil {
		return nil, &BranchError{
			Err:      err,
			Response: &spb.ErrorInfo{Code: spb.ErrorInfo_COMMUNICATION, Message: err.Error()},
		}
	}

	// if the data returned from the server is nil, this is not fatal, but we should return an error
	// TODO: should we return an error to the user here?
	if data == nil || data.GetUpsertBucket() == nil || data.GetUpsertBucket().GetBucket() == nil {
		err := fmt.Errorf("No data returned from server, unable to create run")
		return nil, err
	}

	bucket := data.GetUpsertBucket().GetBucket()

	project := bucket.GetProject()
	var projectName, entityName string
	if project != nil {
		entity := project.GetEntity()
		entityName = entity.GetName()
		projectName = project.GetName()
	}

	fileStreamOffset := make(fs.FileStreamOffsetMap)
	fileStreamOffset[fs.HistoryChunk] = utils.ZeroIfNil(bucket.GetHistoryLineCount())

	return &RunParams{
		StorageID:        bucket.GetId(),
		Entity:           utils.ZeroIfNil(&entityName),
		Project:          utils.ZeroIfNil(&projectName),
		RunID:            bucket.GetName(),
		DisplayName:      utils.ZeroIfNil(bucket.GetDisplayName()),
		SweepID:          utils.ZeroIfNil(bucket.GetSweepName()),
		FileStreamOffset: fileStreamOffset,
	}, nil
}

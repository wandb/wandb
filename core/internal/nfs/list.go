package nfs

import (
	"context"
	"fmt"
	"strings"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/gql"
)

// ProjectPath represents entity/project.
type ProjectPath struct {
	Entity  string
	Project string
}

// ParseProjectPath parses "entity/project" string.
func ParseProjectPath(path string) (*ProjectPath, error) {
	parts := strings.Split(path, "/")
	if len(parts) != 2 {
		return nil, fmt.Errorf("invalid project path: expected entity/project, got %q", path)
	}
	if parts[0] == "" || parts[1] == "" {
		return nil, fmt.Errorf("invalid project path: entity and project cannot be empty")
	}
	return &ProjectPath{
		Entity:  parts[0],
		Project: parts[1],
	}, nil
}

// CollectionInfo holds information about an artifact collection.
type CollectionInfo struct {
	Name     string
	TypeName string
	Versions []VersionInfo
}

// VersionInfo holds information about an artifact version.
type VersionInfo struct {
	Index int
	ID    string
}

// Lister handles listing artifacts and runs.
type Lister struct {
	client graphql.Client
}

// NewLister creates a new Lister.
func NewLister(client graphql.Client) *Lister {
	return &Lister{client: client}
}

// ListCollections lists all artifact collections in a project with their versions.
func (l *Lister) ListCollections(ctx context.Context, p *ProjectPath) ([]CollectionInfo, error) {
	// First, get all artifact types
	types, err := l.listArtifactTypes(ctx, p)
	if err != nil {
		return nil, fmt.Errorf("listing artifact types: %w", err)
	}

	var collections []CollectionInfo

	// For each type, get collections
	for _, typeName := range types {
		typeCollections, err := l.listCollectionsForType(ctx, p, typeName)
		if err != nil {
			return nil, fmt.Errorf("listing collections for type %s: %w", typeName, err)
		}
		collections = append(collections, typeCollections...)
	}

	return collections, nil
}

// listArtifactTypes fetches all artifact type names in a project.
func (l *Lister) listArtifactTypes(ctx context.Context, p *ProjectPath) ([]string, error) {
	var types []string
	var cursor *string
	perPage := 100

	for {
		resp, err := gql.NFSArtifactTypes(ctx, l.client, p.Entity, p.Project, cursor, &perPage)
		if err != nil {
			return nil, err
		}
		if resp.Project == nil {
			return nil, fmt.Errorf("project not found: %s/%s", p.Entity, p.Project)
		}

		for _, edge := range resp.Project.ArtifactTypes.Edges {
			types = append(types, edge.Node.Name)
		}

		if !resp.Project.ArtifactTypes.PageInfo.HasNextPage {
			break
		}
		cursor = resp.Project.ArtifactTypes.PageInfo.EndCursor
	}

	return types, nil
}

// listCollectionsForType fetches all collections for a specific artifact type.
func (l *Lister) listCollectionsForType(ctx context.Context, p *ProjectPath, typeName string) ([]CollectionInfo, error) {
	var collections []CollectionInfo
	var cursor *string
	perPage := 100

	for {
		resp, err := gql.NFSArtifactCollections(ctx, l.client, p.Entity, p.Project, typeName, cursor, &perPage)
		if err != nil {
			return nil, err
		}
		if resp.Project == nil || resp.Project.ArtifactType == nil || resp.Project.ArtifactType.ArtifactCollections == nil {
			break
		}

		for _, edge := range resp.Project.ArtifactType.ArtifactCollections.Edges {
			if edge.Node == nil {
				continue
			}
			collName := (*edge.Node).GetName()

			// Get versions for this collection
			versions, err := l.listVersionsForCollection(ctx, p, typeName, collName)
			if err != nil {
				return nil, fmt.Errorf("listing versions for collection %s: %w", collName, err)
			}

			collections = append(collections, CollectionInfo{
				Name:     collName,
				TypeName: typeName,
				Versions: versions,
			})
		}

		if !resp.Project.ArtifactType.ArtifactCollections.PageInfo.HasNextPage {
			break
		}
		cursor = resp.Project.ArtifactType.ArtifactCollections.PageInfo.EndCursor
	}

	return collections, nil
}

// listVersionsForCollection fetches all versions for a specific collection.
func (l *Lister) listVersionsForCollection(ctx context.Context, p *ProjectPath, typeName, collName string) ([]VersionInfo, error) {
	var versions []VersionInfo
	var cursor *string
	perPage := 100

	for {
		resp, err := gql.NFSArtifacts(ctx, l.client, p.Entity, p.Project, typeName, collName, cursor, &perPage)
		if err != nil {
			return nil, err
		}
		if resp.Project == nil || resp.Project.ArtifactType == nil ||
			resp.Project.ArtifactType.ArtifactCollection == nil {
			break
		}

		artifacts := (*resp.Project.ArtifactType.ArtifactCollection).GetArtifacts()
		if artifacts == nil {
			break
		}

		for _, edge := range artifacts.Edges {
			versionIndex := 0
			if edge.Node.VersionIndex != nil {
				versionIndex = *edge.Node.VersionIndex
			}
			versions = append(versions, VersionInfo{
				Index: versionIndex,
				ID:    edge.Node.Id,
			})
		}

		if !artifacts.PageInfo.HasNextPage {
			break
		}
		cursor = artifacts.PageInfo.EndCursor
	}

	return versions, nil
}

// listRuns fetches all runs in a project.
func (l *Lister) listRuns(ctx context.Context, p *ProjectPath) ([]RunInfo, error) {
	var runs []RunInfo
	var cursor *string
	perPage := 100

	for {
		resp, err := gql.NFSRuns(ctx, l.client, p.Entity, p.Project, cursor, &perPage)
		if err != nil {
			return nil, err
		}
		if resp.Project == nil || resp.Project.Runs == nil {
			break
		}

		for _, edge := range resp.Project.Runs.Edges {
			node := edge.Node

			displayName := ""
			if node.DisplayName != nil {
				displayName = *node.DisplayName
			}
			sweepName := ""
			if node.SweepName != nil {
				sweepName = *node.SweepName
			}
			username := ""
			if node.User != nil && node.User.Username != nil {
				username = *node.User.Username
			}
			state := ""
			if node.State != nil {
				state = *node.State
			}
			config := ""
			if node.Config != nil {
				config = *node.Config
			}
			summaryMetrics := ""
			if node.SummaryMetrics != nil {
				summaryMetrics = *node.SummaryMetrics
			}

			runs = append(runs, RunInfo{
				ID:             node.Id,
				Name:           node.Name,
				DisplayName:    displayName,
				State:          state,
				Config:         config,
				SummaryMetrics: summaryMetrics,
				CreatedAt:      node.CreatedAt,
				HeartbeatAt:    node.HeartbeatAt,
				SweepName:      sweepName,
				Username:       username,
			})
		}

		if !resp.Project.Runs.PageInfo.HasNextPage {
			break
		}
		cursor = resp.Project.Runs.PageInfo.EndCursor
	}

	return runs, nil
}

// listSweeps fetches all sweeps in a project.
func (l *Lister) listSweeps(ctx context.Context, p *ProjectPath) ([]SweepInfo, error) {
	var sweeps []SweepInfo
	var cursor *string
	perPage := 100

	for {
		resp, err := gql.NFSSweeps(ctx, l.client, p.Entity, p.Project, cursor, &perPage)
		if err != nil {
			return nil, err
		}
		if resp.Project == nil || resp.Project.Sweeps == nil {
			break
		}

		for _, edge := range resp.Project.Sweeps.Edges {
			node := edge.Node

			displayName := ""
			if node.DisplayName != nil {
				displayName = *node.DisplayName
			}

			sweeps = append(sweeps, SweepInfo{
				ID:          node.Id,
				Name:        node.Name,
				DisplayName: displayName,
				State:       node.State,
				Config:      node.Config,
				RunCount:    node.RunCount,
				BestLoss:    node.BestLoss,
				CreatedAt:   node.CreatedAt,
			})
		}

		if !resp.Project.Sweeps.PageInfo.HasNextPage {
			break
		}
		cursor = resp.Project.Sweeps.PageInfo.EndCursor
	}

	return sweeps, nil
}

// listRunFiles fetches all files for a run.
func (l *Lister) listRunFiles(ctx context.Context, p *ProjectPath, runName string) ([]RunFileInfo, error) {
	var files []RunFileInfo
	var cursor *string
	perPage := 100

	for {
		resp, err := gql.NFSRunFiles(ctx, l.client, p.Entity, p.Project, runName, cursor, &perPage)
		if err != nil {
			return nil, err
		}
		if resp.Project == nil || resp.Project.Run == nil || resp.Project.Run.Files == nil {
			break
		}

		for _, edge := range resp.Project.Run.Files.Edges {
			if edge.Node == nil {
				continue
			}
			node := edge.Node

			md5 := ""
			if node.Md5 != nil {
				md5 = *node.Md5
			}

			files = append(files, RunFileInfo{
				Name:      node.Name,
				SizeBytes: node.SizeBytes,
				DirectURL: node.DirectUrl,
				MD5:       md5,
			})
		}

		if !resp.Project.Run.Files.PageInfo.HasNextPage {
			break
		}
		cursor = resp.Project.Run.Files.PageInfo.EndCursor
	}

	return files, nil
}

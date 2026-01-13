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

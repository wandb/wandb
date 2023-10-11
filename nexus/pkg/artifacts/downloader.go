package artifacts

import (
	"context"
	"fmt"
	"path/filepath"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/nexus/internal/gql"
	"github.com/wandb/wandb/nexus/pkg/env"
)

type ArtifactDownloader struct {
	// Resources
	Ctx           context.Context
	GraphqlClient graphql.Client
	//Input
	QualifiedName          string
	DownloadRoot           *string
	Recursive              *bool
	AllowMissingReferences *bool
}

func NewArtifactDownloader(
	ctx context.Context,
	graphQLClient graphql.Client,
	QualifiedName string,
	DownloadRoot *string,
	Recursive *bool,
	AllowMissingReferences *bool,
) ArtifactDownloader {
	return ArtifactDownloader{
		Ctx:                    ctx,
		GraphqlClient:          graphQLClient,
		QualifiedName:          QualifiedName,
		DownloadRoot:           DownloadRoot,
		Recursive:              Recursive,
		AllowMissingReferences: AllowMissingReferences,
	}
}

func (ad *ArtifactDownloader) getArtifact() (attrs gql.ArtifactByNameProjectArtifact, rerr error) {
	fmt.Printf("\nQualified Name ===> %s\n", ad.QualifiedName)
	entityName, projectName, artifactName, err := parseArtifactQualifiedName(ad.QualifiedName)
	if err != nil {
		return gql.ArtifactByNameProjectArtifact{}, err
	}
	response, err := gql.ArtifactByName(
		ad.Ctx,
		ad.GraphqlClient,
		entityName,
		projectName,
		artifactName,
	)
	if err != nil {
		return gql.ArtifactByNameProjectArtifact{}, err
	}
	return *response.GetProject().GetArtifact(), nil
}

func (ad *ArtifactDownloader) getArtifactManifest() (artifactManifest Manifest, rerr error) {
	entityName, projectName, artifactName, err := parseArtifactQualifiedName(ad.QualifiedName)
	if err != nil {
		return Manifest{}, err
	}
	response, err := gql.ArtifactManifest(
		ad.Ctx,
		ad.GraphqlClient,
		entityName,
		projectName,
		artifactName,
	)
	if err != nil {
		return Manifest{}, err
	} else if response == nil {
		return Manifest{}, fmt.Errorf("Could not get manifest from server")
	}
	directURL := response.GetProject().GetArtifact().GetCurrentManifest().GetFile().DirectUrl
	return loadManifestFromURL(directURL)
}

func (ad *ArtifactDownloader) setDefaultDownloadRoot(artifactAttrs gql.ArtifactByNameProjectArtifact) (rerr error) {
	// set absolute path to source_artifact_name:v{versionIndex} as default root
	sourceArtifactName := artifactAttrs.GetArtifactSequence().Name
	versionIndex := artifactAttrs.GetVersionIndex()
	if versionIndex == nil {
		return fmt.Errorf("Invalid artifact download, missing version index")
	}
	artifactDir, err := env.GetArtifactDir()
	if err != nil {
		return err
	}
	fmt.Printf("\n\n Artifacts_dir ===> %v \n\n", artifactDir)
	downloadRoot := filepath.Join(artifactDir, fmt.Sprintf("%s:v%d", sourceArtifactName, *versionIndex))
	// todo: the utils are not tested. are probably incorrect
	path := CheckExists(downloadRoot)
	if path == nil {
		downloadRoot = SystemPreferredPath(downloadRoot, false)
	}
	ad.DownloadRoot = &downloadRoot
	return nil
}

func (ad *ArtifactDownloader) getArtifactManifestEntries() (map[string]ManifestEntry, error) {
	artifactManifest, err := ad.getArtifactManifest()
	if err != nil {
		return map[string]ManifestEntry{}, err
	}
	fmt.Printf("\n\n manifest ===> %v \n\n", artifactManifest)
	return artifactManifest.Contents, nil
}

func (ad *ArtifactDownloader) DownloadEntry() error {
	return nil
}

func (ad *ArtifactDownloader) Download() (FileDownloadPath string, rerr error) {
	artifactAttrs, err := ad.getArtifact()
	if err != nil {
		return "", err
	}

	if ad.DownloadRoot == nil {
		err = ad.setDefaultDownloadRoot(artifactAttrs)
		if err != nil {
			return "", err
		}
	}
	fmt.Printf("\n\n Download root ===> %v \n\n", *ad.DownloadRoot)

	artifactManifestEntries, err := ad.getArtifactManifestEntries()
	if err != nil {
		return "", err
	}
	fmt.Printf("\n\n manifest ===> %v \n\n", artifactManifestEntries)

	nFiles := len(artifactManifestEntries)
	fmt.Printf("\n\n manifest size ===> %v \n\n", nFiles)
	size := 0
	for _, file := range artifactManifestEntries {
		size += int(file.Size)
	}
	// todo: ArtifactDownloadLogger
	// if nFiles > 5000 || size > 50*1024*1024 {
	// 	ad.logger.Info("downloadArtifact: downloading large artifact %s, %d MB, %d files", ad.QualifiedName, size/(1024*1024), nFiles)
	// }
	return "", nil
}

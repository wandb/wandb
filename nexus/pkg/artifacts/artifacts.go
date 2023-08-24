package artifacts

import (
	"context"
	"crypto/md5"
	b64 "encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/nexus/internal/gql"
	"github.com/wandb/wandb/nexus/internal/uploader"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
)

type ArtifactSaver struct {
	Ctx           context.Context
	Logger        *observability.NexusLogger
	Artifact      *service.ArtifactRecord
	GraphqlClient graphql.Client
	UploadManager *uploader.UploadManager
	WgOutstanding sync.WaitGroup
}

type ArtifactSaverResult struct {
	ArtifactId string
}

type ManifestStoragePolicyConfig struct {
	StorageLayout string `json:"storageLayout"`
}

type ManifestEntry struct {
	Digest          string `json:"digest"`
	BirthArtifactID string `json:"birthArtifactID"`
	Size            int64  `json:"size"`
}

type ManifestV1 struct {
	Version             int32                       `json:"version"`
	StoragePolicy       string                      `json:"storagePolicy"`
	StoragePolicyConfig ManifestStoragePolicyConfig `json:"storagePolicyConfig"`
	Contents            map[string]ManifestEntry    `json:"contents"`
}

type ArtifactLinker struct {
	Ctx           context.Context
	Logger        *observability.NexusLogger
	Artifact      *service.LinkArtifactRecord
	GraphqlClient graphql.Client
}

func computeB64MD5(manifestFile string) (string, error) {
	file, err := os.ReadFile(manifestFile)
	if err != nil {
		return "", err
	}
	hasher := md5.New()
	hasher.Write(file)
	encodedString := b64.StdEncoding.EncodeToString(hasher.Sum(nil))
	return encodedString, nil
}

func (as *ArtifactSaver) createArtifact() (string, *string) {
	enableDedup := false
	aliases := []gql.ArtifactAliasInput{}
	for _, alias := range as.Artifact.Aliases {
		aliases = append(aliases,
			gql.ArtifactAliasInput{
				ArtifactCollectionName: as.Artifact.Name,
				Alias:                  alias,
			},
		)
	}

	response, err := gql.CreateArtifact(
		as.Ctx,
		as.GraphqlClient,
		as.Artifact.Type,
		[]string{as.Artifact.Name},
		as.Artifact.Entity,
		as.Artifact.Project,
		&as.Artifact.RunId,
		&as.Artifact.Description,
		as.Artifact.Digest,
		nil, // Labels
		aliases,
		nil, // metadata
		// 0,   // historyStep
		// &as.Artifact.DistributedId,
		as.Artifact.ClientId,
		as.Artifact.SequenceClientId,
		&enableDedup, // enableDigestDeduplication
	)
	if err != nil {
		err = fmt.Errorf("CreateArtifact: %s, error: %+v response: %+v", as.Artifact.Name, err, response)
		as.Logger.CaptureFatalAndPanic("createArtifact", err)
	}
	artifact := response.GetCreateArtifact().GetArtifact()
	latest := artifact.ArtifactSequence.GetLatestArtifact()

	var baseId *string
	if latest != nil {
		baseId = &latest.Id
	}
	return artifact.Id, baseId
}

func (as *ArtifactSaver) createManifest(artifactId string, baseArtifactId *string, manifestDigest string, includeUpload bool) (string, *string, []string) {
	const manifestFilename = "wandb_manifest.json"
	manifestType := gql.ArtifactManifestTypeFull

	response, err := gql.CreateArtifactManifest(
		as.Ctx,
		as.GraphqlClient,
		manifestFilename,
		manifestDigest,
		artifactId,
		baseArtifactId,
		as.Artifact.Entity,
		as.Artifact.Project,
		as.Artifact.RunId,
		includeUpload,
		&manifestType,
	)
	if err != nil {
		err = fmt.Errorf("CreateArtifactManifest: %s, error: %+v response: %+v", as.Artifact.Name, err, response)
		as.Logger.CaptureFatalAndPanic("createManifest", err)
	}
	createManifest := response.GetCreateArtifactManifest()
	manifest := createManifest.ArtifactManifest

	var upload *string
	var headers []string
	if includeUpload {
		upload = manifest.File.GetUploadUrl()
		headers = manifest.File.GetUploadHeaders()
	}

	return manifest.Id, upload, headers
}

func (as *ArtifactSaver) sendManifestFiles(artifactID string, manifestID string) {
	artifactFiles := []gql.CreateArtifactFileSpecInput{}
	man := as.Artifact.Manifest
	for _, entry := range man.Contents {
		as.Logger.Info("sendfiles", "entry", entry)
		md5Checksum := ""
		artifactFiles = append(
			artifactFiles,
			gql.CreateArtifactFileSpecInput{
				ArtifactID:         artifactID,
				Name:               entry.Path,
				Md5:                md5Checksum,
				ArtifactManifestID: &manifestID,
			},
		)
	}
	response, err := gql.CreateArtifactFiles(
		as.Ctx,
		as.GraphqlClient,
		gql.ArtifactStorageLayoutV2,
		artifactFiles,
	)
	if err != nil {
		err = fmt.Errorf("CreateArtifactFiles: %s, error: %+v response: %+v", as.Artifact.Name, err, response)
		as.Logger.CaptureFatalAndPanic("sendManifestFiles", err)
	}
	for n, edge := range response.GetCreateArtifactFiles().GetFiles().Edges {
		task := uploader.UploadTask{
			Url:           *edge.Node.GetUploadUrl(),
			Path:          man.Contents[n].LocalPath,
			WgOutstanding: &as.WgOutstanding,
		}
		as.UploadManager.AddTask(&task)
	}
}

func (as *ArtifactSaver) writeManifest() (string, error) {
	man := as.Artifact.Manifest

	m := &ManifestV1{
		Version:       man.Version,
		StoragePolicy: man.StoragePolicy,
		StoragePolicyConfig: ManifestStoragePolicyConfig{
			StorageLayout: "V2",
		},
		Contents: make(map[string]ManifestEntry),
	}

	for _, entry := range man.Contents {
		m.Contents[entry.Path] = ManifestEntry{
			Digest: entry.Digest,
			Size:   entry.Size,
		}
	}

	jsonBytes, _ := json.MarshalIndent(m, "", "    ")

	f, err := os.CreateTemp("", "tmpfile-")
	if err != nil {
		return "", err
	}

	defer f.Close()

	if _, err := f.Write(jsonBytes); err != nil {
		return "", err
	}

	return f.Name(), nil
}

func (as *ArtifactSaver) sendManifest(manifestFile string, uploadUrl *string, uploadHeaders []string) {
	task := uploader.UploadTask{
		Url:           *uploadUrl,
		Path:          manifestFile,
		Headers:       uploadHeaders,
		WgOutstanding: &as.WgOutstanding,
	}
	as.UploadManager.AddTask(&task)
}

func (as *ArtifactSaver) commitArtifact(artifactId string) {
	response, err := gql.CommitArtifact(
		as.Ctx,
		as.GraphqlClient,
		artifactId,
	)
	if err != nil {
		err = fmt.Errorf("CommitArtifact: %s, error: %+v response: %+v", as.Artifact.Name, err, response)
		as.Logger.CaptureFatalAndPanic("commitArtifact", err)
	}
}

func (as *ArtifactSaver) Save() (ArtifactSaverResult, error) {
	artifactId, baseArtifactId := as.createArtifact()
	manifestId, _, _ := as.createManifest(artifactId, baseArtifactId, "", false)
	as.sendManifestFiles(artifactId, manifestId)
	manifestFile, err := as.writeManifest()
	if err != nil {
		return ArtifactSaverResult{}, err
	}
	manifestDigest, err := computeB64MD5(manifestFile)
	if err != nil {
		return ArtifactSaverResult{}, err
	}
	defer os.Remove(manifestFile)
	_, uploadUrl, uploadHeaders := as.createManifest(artifactId, baseArtifactId, manifestDigest, true)
	as.sendManifest(manifestFile, uploadUrl, uploadHeaders)
	// wait on all outstanding requests before commit
	as.WgOutstanding.Wait()
	as.commitArtifact(artifactId)

	return ArtifactSaverResult{ArtifactId: artifactId}, nil
}

func (al *ArtifactLinker) Link() error {
	client_id := al.Artifact.ClientId
	server_id := al.Artifact.ServerId
	portfolio_name := al.Artifact.PortfolioName
	portfolio_entity := al.Artifact.PortfolioEntity
	portfolio_project := al.Artifact.PortfolioProject
	portfolio_aliases := []gql.ArtifactAliasInput{}

	for _, alias := range al.Artifact.PortfolioAliases {
		portfolio_aliases = append(portfolio_aliases,
			gql.ArtifactAliasInput{
				ArtifactCollectionName: portfolio_name,
				Alias:                  alias,
			},
		)
	}
	// Todo: Remove log
	al.Logger.Info("sendLinker", "link record info", client_id, server_id, portfolio_name, portfolio_entity, portfolio_project, portfolio_aliases)
	var err error
	var response interface{}
	if server_id != "" {
		response, err = gql.LinkArtifact(
			al.Ctx,
			al.GraphqlClient,
			portfolio_name,
			portfolio_entity,
			portfolio_project,
			portfolio_aliases,
			nil,
			&server_id,
		)
	} else if client_id != "" {
		response, err = gql.LinkArtifact(
			al.Ctx,
			al.GraphqlClient,
			portfolio_name,
			portfolio_entity,
			portfolio_project,
			portfolio_aliases,
			&client_id,
			nil,
		)
	}
	if err != nil {
		err = fmt.Errorf("LinkArtifact: %s, error: %+v response: %+v", portfolio_name, err, response)
		al.Logger.CaptureFatalAndPanic("sendLinkArtifact", err)
	}

	// Todo: can both server id and client id be nil?
	// Todo: Return?
	return nil
}

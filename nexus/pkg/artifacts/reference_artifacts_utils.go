package artifacts

import (
	"net/url"

	"github.com/wandb/wandb/nexus/pkg/utils"
)

func isArtifactReference(ref *string) (bool, error) {
	if ref == nil {
		return false, nil
	}
	u, err := url.Parse(*ref)
	if err != nil {
		return false, err
	}
	if u.Scheme == "wandb-artifact" {
		return true, nil
	}
	return false, nil
}

func getReferencedID(ref *string) (*string, error) {
	isRef, err := isArtifactReference(ref)
	if err != nil {
		return nil, err
	} else if !isRef {
		return nil, nil
	}
	u, err := url.Parse(*ref)
	if err != nil {
		return nil, err
	}
	refID, err := utils.HexToB64(u.Host)
	if err != nil {
		return nil, err
	}
	return &refID, nil
}

package artifacts

import (
	"context"
	"fmt"
	"strings"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/gql"
)

const RegistryProjectPrefix = "wandb-registry-"

func IsArtifactRegistryProject(project string) bool {
	return strings.HasPrefix(project, RegistryProjectPrefix)
}

func GetGraphQLInputFields(ctx context.Context, client graphql.Client, typeName string) ([]string, error) {
	response, err := gql.InputFields(ctx, client, typeName)
	if err != nil {
		return nil, err
	}
	typeInfo := response.GetTypeInfo()
	if typeInfo == nil {
		return nil, fmt.Errorf("unable to verify allowed fields for %s", typeName)
	}
	fields := typeInfo.GetInputFields()
	fieldNames := make([]string, len(fields))
	for i, field := range fields {
		fieldNames[i] = field.GetName()
	}
	return fieldNames, nil
}

func GetGraphQLFields(ctx context.Context, client graphql.Client, typeName string) ([]string, error) {
	response, err := gql.TypeFields(ctx, client, typeName)
	if err != nil {
		return nil, err
	}
	typeInfo := response.GetTypeInfo()
	if typeInfo == nil {
		return nil, fmt.Errorf("unable to verify allowed fields for %s", typeName)
	}
	fields := typeInfo.GetFields()
	fieldNames := make([]string, len(fields))
	for i, field := range fields {
		fieldNames[i] = field.GetName()
	}
	return fieldNames, nil
}

package utils

import (
	"context"
	"fmt"
	"math/rand"
	"strings"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/gql"
)

const alphanumericChars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
const registryProjectPrefix = "wandb-registry-"

func NilIfZero[T comparable](x T) *T {
	var zero T
	if x == zero {
		return nil
	}
	return &x
}

func ZeroIfNil[T comparable](x *T) T {
	if x == nil {
		// zero value of T
		var zero T
		return zero
	}
	return *x
}

func GenerateAlphanumericSequence(length int) string {
	var result string
	for i := 0; i < length; i++ {
		index := rand.Intn(len(alphanumericChars))
		result += string(alphanumericChars[index])
	}

	return result
}

func GetInputFields(ctx context.Context, client graphql.Client, typeName string) ([]string, error) {
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

func IsArtifactRegistryProject(project string) bool {
	return strings.HasPrefix(project, registryProjectPrefix)
}

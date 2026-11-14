// File generated from our OpenAPI spec by Stainless.

package cwevals_test

import (
	"context"
	"errors"
	"os"
	"testing"

	"github.com/wandb/cwevals-go"
	"github.com/wandb/cwevals-go/internal/testutil"
	"github.com/wandb/cwevals-go/option"
)

func TestDatasetCaseAddWithOptionalParams(t *testing.T) {
	baseURL := "http://localhost:4010"
	if envURL, ok := os.LookupEnv("TEST_API_BASE_URL"); ok {
		baseURL = envURL
	}
	if !testutil.CheckTestServer(t, baseURL) {
		return
	}
	client := cwevals.NewClient(
		option.WithBaseURL(baseURL),
		option.WithBearerToken("My Bearer Token"),
		option.WithUsername("My Username"),
		option.WithAPIKey("My API Key"),
	)
	_, err := client.Datasets.Cases.Add(
		context.TODO(),
		"182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e",
		cwevals.DatasetCaseAddParams{
			Namespace: cwevals.F("wandb"),
			ScopeID:   cwevals.F("scope_id"),
			Cases: cwevals.F([]cwevals.DatasetCaseAddParamsCase{
				{
					Attributes: cwevals.F(map[string]interface{}{
						"foo": "bar",
					}),
					ExampleKey: cwevals.F("x"),
					Input: cwevals.F[cwevals.CaseValueUnionParam](
						cwevals.CaseValueMapParam(map[string]cwevals.CaseFieldValueUnionParam{
							"foo": cwevals.WandbImageV1Param{
								ExtensionType: cwevals.F(cwevals.WandbImageV1ExtensionTypeWandbImage),
								Format:        cwevals.F("x"),
								SchemaVersion: cwevals.F(cwevals.WandbImageV1SchemaVersion1),
								Sha256: cwevals.F(
									"210b9798eb53baa4e69d31c1071cf03d212b8ad0ca30cf321e0ea82e120aac26",
								),
								Size:        cwevals.F(int64(0)),
								Uri:         cwevals.F("x"),
								WbMediaType: cwevals.F(cwevals.WandbImageV1WbMediaTypeImageFile),
								Boxes: cwevals.F(map[string]cwevals.WandbImageBoxesV1Param{
									"foo": {
										Sha256: cwevals.F(
											"210b9798eb53baa4e69d31c1071cf03d212b8ad0ca30cf321e0ea82e120aac26",
										),
										Size: cwevals.F(int64(0)),
										Uri:  cwevals.F("x"),
										Type: cwevals.F(cwevals.WandbImageBoxesV1_TypeBoxes2D),
									},
								}),
								Caption: cwevals.F("caption"),
								Height:  cwevals.F(int64(0)),
								Masks: cwevals.F(map[string]cwevals.WandbImageMaskV1Param{
									"foo": {
										Sha256: cwevals.F(
											"210b9798eb53baa4e69d31c1071cf03d212b8ad0ca30cf321e0ea82e120aac26",
										),
										Size: cwevals.F(int64(0)),
										Uri:  cwevals.F("x"),
										Type: cwevals.F(cwevals.WandbImageMaskV1_TypeMask),
									},
								}),
								Width: cwevals.F(int64(0)),
							},
						}),
					),
					Output: cwevals.F[cwevals.CaseValueUnionParam](
						cwevals.CaseValueMapParam(map[string]cwevals.CaseFieldValueUnionParam{
							"foo": cwevals.WandbImageV1Param{
								ExtensionType: cwevals.F(cwevals.WandbImageV1ExtensionTypeWandbImage),
								Format:        cwevals.F("x"),
								SchemaVersion: cwevals.F(cwevals.WandbImageV1SchemaVersion1),
								Sha256: cwevals.F(
									"210b9798eb53baa4e69d31c1071cf03d212b8ad0ca30cf321e0ea82e120aac26",
								),
								Size:        cwevals.F(int64(0)),
								Uri:         cwevals.F("x"),
								WbMediaType: cwevals.F(cwevals.WandbImageV1WbMediaTypeImageFile),
								Boxes: cwevals.F(map[string]cwevals.WandbImageBoxesV1Param{
									"foo": {
										Sha256: cwevals.F(
											"210b9798eb53baa4e69d31c1071cf03d212b8ad0ca30cf321e0ea82e120aac26",
										),
										Size: cwevals.F(int64(0)),
										Uri:  cwevals.F("x"),
										Type: cwevals.F(cwevals.WandbImageBoxesV1_TypeBoxes2D),
									},
								}),
								Caption: cwevals.F("caption"),
								Height:  cwevals.F(int64(0)),
								Masks: cwevals.F(map[string]cwevals.WandbImageMaskV1Param{
									"foo": {
										Sha256: cwevals.F(
											"210b9798eb53baa4e69d31c1071cf03d212b8ad0ca30cf321e0ea82e120aac26",
										),
										Size: cwevals.F(int64(0)),
										Uri:  cwevals.F("x"),
										Type: cwevals.F(cwevals.WandbImageMaskV1_TypeMask),
									},
								}),
								Width: cwevals.F(int64(0)),
							},
						}),
					),
					TrajectoryID: cwevals.F("182bd5e5-6e1a-4fe4-a799-aa6d9a6ab26e"),
					Variant:      cwevals.F("x"),
				},
			}),
			ExampleKeyFields: cwevals.F(
				[]cwevals.DatasetCaseAddParamsExampleKeyField{cwevals.DatasetCaseAddParamsExampleKeyFieldInput},
			),
		},
	)
	if err != nil {
		var apierr *cwevals.Error
		if errors.As(err, &apierr) {
			t.Log(string(apierr.DumpRequest(true)))
		}
		t.Fatalf("err should be nil: %s", err.Error())
	}
}

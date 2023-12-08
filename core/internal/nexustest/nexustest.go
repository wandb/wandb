package nexustest

import (
	"context"
	"testing"

	"github.com/segmentio/encoding/json"

	"github.com/Khan/genqlient/graphql"
	"github.com/golang/mock/gomock"
	"github.com/wandb/wandb/nexus/internal/gqltest"
	"github.com/wandb/wandb/nexus/pkg/service"
)

type RequestVars = map[string]interface{}

type TestObject struct {
	t          *testing.T
	mockCtrl   *gomock.Controller
	MockClient *gqltest.MockClient
}

func MakeTestObject(t *testing.T) TestObject {
	tst := TestObject{
		t: t,
	}
	tst.setupTest()
	return tst
}

func (to *TestObject) setupTest() {
	to.mockCtrl = gomock.NewController(to.t)
	to.MockClient = gqltest.NewMockClient(to.mockCtrl)
}

func (to *TestObject) TeardownTest() {
	to.mockCtrl.Finish()
}

func (to *TestObject) MakeConfig() *service.ConfigRecord {
	config := &service.ConfigRecord{
		Update: []*service.ConfigItem{
			&service.ConfigItem{
				Key:       "_wandb",
				ValueJson: "{}",
			},
		},
	}
	return config
}

func StrPtr(s string) *string {
	return &s
}

func IntPtr(i int) *int {
	return &i
}

func InjectResponse(respEncode *graphql.Response, matchFunc func(RequestVars)) func(context.Context, *graphql.Request, *graphql.Response) {
	return func(ctx context.Context, req *graphql.Request, resp *graphql.Response) {
		// check request
		if matchFunc != nil {
			body, err := json.Marshal(req.Variables)
			if err != nil {
				panic("bad")
			}
			var vars RequestVars
			err = json.Unmarshal(body, &vars)
			if err != nil {
				panic("bad")
			}
			matchFunc(vars)
		}

		// fill response
		body, err := json.Marshal(respEncode)
		if err != nil {
			panic("bad")
		}
		err = json.Unmarshal(body, resp)
		if err != nil {
			panic("bad")
		}
	}
}

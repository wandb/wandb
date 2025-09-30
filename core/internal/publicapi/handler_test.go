package publicapi

import (
	"testing"

	"github.com/stretchr/testify/assert"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestHandleRequest_InvalidRequest(t *testing.T) {
	responseChan := make(chan *spb.ServerResponse)

	request := &spb.ApiRequest{}

	handler := NewApiRequestHandler()
	handler.HandleRequest("test", request, func(response *spb.ServerResponse) {
		responseChan <- response
	})

	response := <-responseChan
	assert.Equal(t, response.RequestId, "test")
	assert.IsType(
		t,
		&spb.ServerResponse_ApiResponse{},
		response.ServerResponseType,
	)
	assert.IsType(t, &spb.ApiResponse{}, response.GetApiResponse())
}

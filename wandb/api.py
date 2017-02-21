import jsonapi_requests

class Api(object):
    """W&B Api wrapper"""
    def __init__(self):
        self.connection = jsonapi_requests.Api.config({
            'API_ROOT': 'http://localhost:3000/v1',
            'TIMEOUT': 2
        })

    def create_model(self, attrs):
        """Creates a model in W&B"""
        endpoint = self.connection.endpoint("models")
        return endpoint.post(object=jsonapi_requests.JsonApiObject(
            attributes=attrs,
            type="models"
        ))
        
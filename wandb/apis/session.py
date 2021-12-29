from google.auth.transport.requests import AuthorizedSession


class WandbSession(AuthorizedSession):
    def rebuild_auth(self, prepared_request, response):
        """Rebuilding auth will overwrite our authorization header,
        we override it to allow our sweet auth to come through."""
        pass

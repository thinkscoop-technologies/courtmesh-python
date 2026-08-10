"""Shared test helpers: a minimal stand-in for `requests.Response`."""


class FakeResponse:
    """Just enough of `requests.Response` for the SDK's transport code:
    `status_code`, `headers`, `reason` and a `json()` method.
    """

    def __init__(self, status_code, json_data=None, headers=None, reason=""):
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers or {}
        self.reason = reason

    def json(self):
        if self._json_data is None:
            raise ValueError("no JSON body")
        return self._json_data

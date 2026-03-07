class FakeResponse:
    def __init__(self, status_code=200, json_data=None, json_error=None):
        self.status_code = status_code
        self._json_data = json_data
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_data


class FakeAsyncClient:
    def __init__(self, *, get_responses=None, post_responses=None, record=None, **_kwargs):
        self._get_responses = get_responses if get_responses is not None else []
        self._post_responses = post_responses if post_responses is not None else []
        self._record = record if record is not None else {"get": [], "post": []}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *args, **kwargs):
        self._record["get"].append({"args": args, "kwargs": kwargs})
        return self._pop(self._get_responses, "GET")

    async def post(self, *args, **kwargs):
        self._record["post"].append({"args": args, "kwargs": kwargs})
        return self._pop(self._post_responses, "POST")

    @staticmethod
    def _pop(queue, method):
        if not queue:
            raise AssertionError(f"Unexpected {method} request in test")

        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

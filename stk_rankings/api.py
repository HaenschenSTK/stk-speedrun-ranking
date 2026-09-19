"""Small read-only client for the public speedrun.com v1 API."""

import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://www.speedrun.com/api/v1/"


class Api:
    def __init__(self):
        self.requests = 0
        self.last_request = 0.0

    def get(self, path, **params):
        url = path if path.startswith(BASE_URL) else BASE_URL + path
        if params:
            url += "?" + urlencode(params)
        # Under 100 requests/minute; HTTP failures are left visible to the operator.
        time.sleep(max(0, 0.65 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        self.requests += 1
        request = Request(url, headers={"User-Agent": "stk-rankings/0.1", "Accept": "application/json"})
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    def run_pages(self, game_id, level_id, category_id):
        page = self.get("runs", game=game_id, level=level_id, category=category_id, status="verified",
                        orderby="verify-date", direction="desc", max=200, embed="players")
        while True:
            next_url = next((link["uri"] for link in page["pagination"]["links"]
                             if link["rel"] == "next"), None)
            yield page["data"], next_url is None
            if next_url is None:
                return
            page = self.get(next_url)

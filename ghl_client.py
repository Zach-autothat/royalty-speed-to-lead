"""GoHighLevel v2 API client — the shared foundation layer.

Stdlib only (urllib). Handles auth headers, JSON, pagination, and 429/5xx
retry with backoff. Every tool we build draws from this; tools never talk to
the GHL API directly.
"""
import json
import time
import urllib.parse
import urllib.request
import urllib.error

import config

BASE = "https://services.leadconnectorhq.com"


class GHLError(Exception):
    pass


class GHLClient:
    def __init__(self, token=None, location_id=None, version=None):
        self.token = token or config.TOKEN
        self.location_id = location_id or config.LOCATION_ID
        self.version = version or config.API_VERSION

    # ---- low level -------------------------------------------------------
    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Version": self.version,
            "Accept": "application/json",
            "Content-Type": "application/json",
            # Cloudflare in front of the API blocks the default Python-urllib UA
            # (error 1010). Present a normal browser-like signature.
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0 Safari/537.36",
        }

    def _request(self, method, path, params=None, body=None, _tries=0):
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Retry on rate-limit / transient server errors
            if e.code in (429, 500, 502, 503, 504) and _tries < 5:
                wait = float(e.headers.get("Retry-After", 0)) or (1.5 ** _tries)
                time.sleep(wait)
                return self._request(method, path, params, body, _tries + 1)
            detail = e.read().decode("utf-8", "ignore")[:300]
            raise GHLError(f"{e.code} {method} {path} :: {detail}") from None
        except urllib.error.URLError as e:
            if _tries < 5:
                time.sleep(1.5 ** _tries)
                return self._request(method, path, params, body, _tries + 1)
            raise GHLError(f"network error {method} {path} :: {e}") from None

    def get(self, path, params=None):
        return self._request("GET", path, params=params)

    def post(self, path, body=None):
        return self._request("POST", path, body=body)

    # ---- users -----------------------------------------------------------
    def users(self):
        """Return {userId: display_name} for the location."""
        data = self.get("/users/", {"locationId": self.location_id})
        out = {}
        for u in data.get("users", []):
            out[u["id"]] = u.get("name") or (
                (u.get("firstName", "") + " " + u.get("lastName", "")).strip()
            ) or u.get("email") or u["id"]
        return out

    # ---- contacts --------------------------------------------------------
    def search_contacts_between(self, start_ms, end_ms, page_limit=100):
        """Yield contacts whose dateAdded is within [start_ms, end_ms], using the
        searchAfter cursor. Sorted dateAdded desc so we can stop once we pass the
        window start."""
        search_after = None
        while True:
            body = {
                "locationId": self.location_id,
                "pageLimit": page_limit,
                "sort": [{"field": "dateAdded", "direction": "desc"}],
            }
            if search_after is not None:
                body["searchAfter"] = search_after
            data = self.post("/contacts/search", body)
            contacts = data.get("contacts", [])
            if not contacts:
                break
            stop = False
            for c in contacts:
                added = _to_ms(c.get("dateAdded"))
                if added is None:
                    continue
                if added < start_ms:
                    stop = True
                    break
                if added <= end_ms:
                    yield c
            if stop or len(contacts) < page_limit:
                break
            search_after = contacts[-1].get("searchAfter")
            if not search_after:
                break

    # ---- conversations / messages ---------------------------------------
    def contact_conversations(self, contact_id):
        data = self.get(
            "/conversations/search",
            {"locationId": self.location_id, "contactId": contact_id},
        )
        return data.get("conversations", [])

    def conversation_messages(self, conversation_id, hard_cap=500):
        """All messages in a conversation (paginates oldest direction via lastMessageId)."""
        out = []
        last_id = None
        while len(out) < hard_cap:
            params = {"limit": 100}
            if last_id:
                params["lastMessageId"] = last_id
            data = self.get(f"/conversations/{conversation_id}/messages", params)
            block = data.get("messages", {})
            msgs = block.get("messages", [])
            if not msgs:
                break
            out.extend(msgs)
            if not block.get("nextPage"):
                break
            last_id = block.get("lastMessageId") or msgs[-1].get("id")
            if not last_id:
                break
        return out


# ---- shared time helpers -------------------------------------------------
def _to_ms(value):
    """Normalize a GHL timestamp (epoch ms int, or ISO-8601 string) to epoch ms."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if s.isdigit():
        return int(s)
    # ISO-8601, possibly with 'Z' and 1-6 fractional digits
    from datetime import datetime, timezone
    s = s.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(s, fmt)
            return int(dt.astimezone(timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    return None

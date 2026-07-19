from __future__ import annotations

import logging
from typing import Any

import requests
import time
import re

from src.colors import red as _red


class NextcloudNewsClient:
    def __init__(
        self,
        base_url: str,
        user: str,
        access_token: str,
        timeout_seconds: int = 20,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("NEXTCLOUD_BASE_URL must start with https://")

        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/index.php/apps/news/api/v1-2"
        self.session = requests.Session()
        self.session.auth = (user, access_token)
        self.session.headers.update({"Accept": "application/json"})
        self.timeout_seconds = timeout_seconds

        # Check API version at startup
        self.check_api_version()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(
            method,
            f"{self.api_base}{path}",
            timeout=self.timeout_seconds,
            **kwargs,
        )
        response.raise_for_status()

        if not response.content:
            return {}

        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Expected JSON object from {path}")

        return payload

    def get_folders(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/folders")
        folders = payload.get("folders", [])
        if not isinstance(folders, list):
            return []
        # Normalize: the API uses "name", but code expects "title"
        for folder in folders:
            if "name" in folder and "title" not in folder:
                folder["title"] = folder["name"]
        return folders

    def get_feeds(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/feeds")
        feeds = payload.get("feeds", [])
        if not isinstance(feeds, list):
            return []
        return feeds

    def get_updated_items(self, last_modified: int, feed_id: int | None = None) -> tuple[list[dict[str, Any]], int]:
        """Fetch updated items, optionally filtered by a specific feed.

        :param last_modified: Only fetch items newer than this timestamp.
        :param feed_id: If provided, only fetch items from this feed.
        :return: Tuple of (items list, lastModified timestamp from API).
        """
        # Build query string
        query_parts = [f"lastModified={last_modified}"]
        if feed_id is not None:
            query_parts.append(f"feedId={feed_id}")
        query_string = "&".join(query_parts)

        payload = self._request("GET", f"/items/updated?{query_string}")

        items = payload.get("items", [])
        if not isinstance(items, list):
            items = []

        returned_last_modified = payload.get("lastModified")
        if returned_last_modified is not None:
            # API returned a lastModified value; use it
            if isinstance(returned_last_modified, int):
                pass
            elif isinstance(returned_last_modified, str):
                try:
                    returned_last_modified = int(returned_last_modified)
                except ValueError:
                    returned_last_modified = last_modified
            else:
                returned_last_modified = last_modified
        else:
            # API did not return lastModified (common behavior).
            # Use current timestamp so the next poll only fetches new items.
            returned_last_modified = int(time.time())

        return items, returned_last_modified

    def mark_item_read(self, item_id: int) -> None:
        # News API supports marking an item as read via PUT on this endpoint.
        # This endpoint may return an empty or non-JSON response, so we don't
        # use _request which expects a JSON dict.
        response = self.session.request(
            "PUT",
            f"{self.api_base}/items/{item_id}/read",
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

    def mark_items_read_batch(self, item_ids: list[int]) -> None:
        """Mark multiple items as read using the v1-3 batch endpoint."""
        if not item_ids:
            return

        # Batch into chunks of ~100 IDs to avoid payload size limits
        chunk_size = 100
        for i in range(0, len(item_ids), chunk_size):
            chunk = item_ids[i : i + chunk_size]
            response = self.session.post(
                f"{self.api_base}/items/read/multiple",
                json={"itemIds": chunk},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()

    def get_all_feeds_for_update(self) -> list[dict[str, Any]]:
        """GET /feeds/all — get all feeds to trigger updates.

        Returns a list of dicts with ``id`` and ``userId`` keys.
        """
        url = f"{self.api_base}/feeds/all"
        try:
            response = self.session.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
            if not response.content:
                return []
            payload = response.json()
            if not isinstance(payload, dict):
                return []
            return payload.get("feeds", [])
        except Exception:
            logging.getLogger("nextcloud-news-filter").exception(
                _red("Failed to fetch all feeds for update")
            )
            return []

    def get_feed_items(self, feed_id: int, last_modified: int = 0) -> tuple[list[dict[str, Any]], int]:
        """Fetch items for a specific feed using the /items/updated endpoint.

        Uses the v1-3 compatible /items/updated endpoint and filters items
        by feed ID on the client side, since the server does not honor the
        feedId query parameter.

        :param feed_id: The feed ID to fetch items from.
        :param last_modified: Only fetch items newer than this timestamp (defaults to 0).
        :return: Tuple of (items list filtered by feed_id, lastModified timestamp from API).
        """
        try:
            raw_items, returned_last_modified = self.get_updated_items(
                last_modified=last_modified, feed_id=None
            )
            # Filter client-side by feed ID
            items = [item for item in raw_items if item.get("feedId") == feed_id]
            return items, returned_last_modified
        except Exception:
            LOGGER = logging.getLogger("nextcloud-news-filter")
            LOGGER.exception(_red("Failed to fetch items for feed %d"), feed_id)
            return [], int(time.time())

    def get_version(self) -> str:
        """Call the version endpoint and return the version string.

        Sets ``api_base`` to the first API path that returns a version,
        so that ``check_api_version`` only upgrades when v1-3 actually
        responds successfully.
        """
        # Try v1-3 first, fall back to v1-2
        for api_path in ("v1-3", "v1-2"):
            url = f"{self.base_url}/index.php/apps/news/api/{api_path}/version"
            try:
                response = self.session.get(url, timeout=self.timeout_seconds)
                response.raise_for_status()
                if response.content:
                    payload = response.json()
                    if isinstance(payload, dict) and "version" in payload:
                        self.api_base = url.rsplit("/", 1)[0]
                        return payload["version"]
            except Exception:
                continue
        raise RuntimeError("Could not reach Nextcloud News API version endpoint.")

    def check_api_version(self) -> None:
        """Verify News app version >= 28.4.0 and switch API base to v1-3.

        ``get_version`` already sets ``api_base`` to whichever API path
        responded successfully, so this method only upgrades to v1-3
        when v1-3 was the path that returned a valid version.
        """
        version_str = self.get_version()

        # Parse version string "X.Y.Z" into integers
        match = re.match(r"(\d+)\.(\d+)\.(\d+)", version_str)
        if not match:
            raise RuntimeError(
                f"Nextcloud News API version check failed. "
                f"Could not parse version: {version_str}. Aborting."
            )

        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))

        # Check >= 28.4.0
        if (major, minor, patch) < (28, 4, 0):
            raise RuntimeError(
                f"Nextcloud News API v1-3 is not available. "
                f"Current version: {version_str}. Aborting."
            )

        # api_base is already set by get_version to whichever path succeeded.
        # If we got here, v1-3 responded successfully.

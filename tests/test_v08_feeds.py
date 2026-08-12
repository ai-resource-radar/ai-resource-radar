from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
import xml.etree.ElementTree as ET

from ai_resource_radar.public_feeds import build_public_feeds


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
BASE = "https://example.test/radar/"


def resource(**overrides):
    row = {
        "offer_id": "token:example",
        "provider": "Example & AI",
        "title": "Free <model>",
        "kind": "token",
        "offer_type": "recurring_free",
        "quota_value": 10,
        "quota_unit": "requests",
        "reset_period": "daily",
        "requires_card": "no",
        "priority_tier": "A",
        "verification_level": "official_page",
        "status": "active",
        "homepage_url": "https://provider.example/free?api_key=must-not-leak&user=alice#fragment",
        "expires_at": None,
    }
    row.update(overrides)
    return row


def change(**overrides):
    row = {
        "id": 123,
        "offer_id": "token:example",
        "provider": "Example & AI",
        "title": "Free <model>",
        "priority_tier": "A",
        "change_type": "updated",
        "changed_fields": ["quota_value"],
        "detected_at": (NOW - timedelta(days=1)).isoformat(),
    }
    row.update(overrides)
    return row


class PublicFeedsTests(unittest.TestCase):
    def test_returns_four_well_formed_empty_feeds(self) -> None:
        feeds = build_public_feeds({"items": []}, {"items": []}, base_url=BASE, now=NOW)
        self.assertEqual(set(feeds), {"feed.xml", "rss.xml", "en/feed.xml", "en/rss.xml"})
        for name, content in feeds.items():
            root = ET.fromstring(content)
            self.assertFalse(list(root.iter("item")))
            self.assertFalse([node for node in root.iter() if node.tag.endswith("entry")])

    def test_filters_to_official_ab_important_nonbaseline_changes(self) -> None:
        changes = [
            change(),
            change(id=999, changed_fields=["hourly_usd"]),
            change(id=998, baseline=True),
            change(id=997, verification_level="community"),
            change(id=996, detected_at=(NOW - timedelta(days=31)).isoformat()),
            change(id=995, change_type="added", changed_fields=[]),
        ]
        resources = {"items": [resource()]}
        feeds = build_public_feeds(resources, {"items": changes}, base_url=BASE, now=NOW)
        atom = ET.fromstring(feeds["en/feed.xml"])
        entries = [node for node in atom if node.tag.endswith("entry")]
        self.assertEqual(len(entries), 2)
        titles = [next(child.text for child in entry if child.tag.endswith("title")) for entry in entries]
        self.assertTrue(any("Important change" in title for title in titles))
        self.assertTrue(any("Added" in title for title in titles))
        self.assertNotIn("hourly_usd", feeds["en/feed.xml"])

    def test_expiry_reminder_is_deduped_with_change_and_ids_ignore_database_id(self) -> None:
        expiring = resource(expires_at=(NOW + timedelta(days=2)).isoformat())
        first = build_public_feeds({"items": [expiring]}, {"items": [change(id=1)]}, base_url=BASE, now=NOW)
        second = build_public_feeds({"items": [expiring]}, {"items": [change(id=2)]}, base_url=BASE, now=NOW)
        self.assertEqual(first["en/feed.xml"], second["en/feed.xml"])
        root = ET.fromstring(first["en/feed.xml"])
        entries = [node for node in root if node.tag.endswith("entry")]
        self.assertEqual(len(entries), 1)
        self.assertTrue(next(child.text for child in entries[0] if child.tag.endswith("id")).startswith("urn:sha256:"))

    def test_xml_and_url_values_are_escaped_and_credentials_removed(self) -> None:
        feeds = build_public_feeds({"items": [resource()]}, {"items": [change()]}, base_url=BASE, now=NOW)
        ET.fromstring(feeds["rss.xml"])
        self.assertIn("Example &amp; AI", feeds["rss.xml"])
        self.assertIn("Free &lt;model&gt;", feeds["rss.xml"])
        self.assertNotIn("api_key", feeds["rss.xml"])
        self.assertNotIn("user=alice", feeds["rss.xml"])
        self.assertNotIn("#fragment", feeds["rss.xml"])

    def test_caps_combined_changes_and_expiry_entries_at_fifty(self) -> None:
        rows = [
            change(
                id=index,
                offer_id=f"token:{index}",
                detected_at=(NOW - timedelta(hours=index)).isoformat(),
            )
            for index in range(55)
        ]
        resources = [resource(offer_id=f"token:{index}") for index in range(55)]
        feeds = build_public_feeds({"items": resources}, {"items": rows}, base_url=BASE, now=NOW)
        root = ET.fromstring(feeds["rss.xml"])
        self.assertLessEqual(len([node for node in root.iter("item")]), 50)


if __name__ == "__main__":
    unittest.main()

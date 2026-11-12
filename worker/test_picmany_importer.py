#!/usr/bin/env python3
import os, unittest
os.environ.setdefault("SUPABASE_URL","https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY","test-only")
from worker.instagram_import import parse_cards, story_items

class PicManyParserTests(unittest.TestCase):
    def test_posts_and_reels_html(self):
        html='''<div data-cards data-next="cursor-123"><article class="media-card">
        <a href="/reel/AbC123"><span><img src="/i/thumb.jpg"></span></a>
        <div class="body"><a class="by truncate" href="/pickleballdotcom">@pickleballdotcom</a>
        <p dir="auto">Caption <a href="/tag">tag</a> here</p>
        <time datetime="2026-11-09T16:46:24.000Z">Nov 9</time></div></article>
        <article class="media-card"><a href="/p/Def456"><img src="/i/photo.jpg"></a>
        <div class="body"><span class="by truncate">@pickleballdotcom</span>
        <p>Carousel caption</p><time datetime="2026-11-08T10:00:00Z">Nov 8</time></div></article></div>'''
        rows=parse_cards(html,"pickleballdotcom")
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]["media_type"],"reel")
        self.assertEqual(rows[0]["shortcode"],"AbC123")
        self.assertIn("Caption tag here",rows[0]["caption"])
        self.assertEqual(rows[1]["media_type"],"post")
        self.assertEqual(rows[1]["image_url"],"https://picmany.com/i/photo.jpg")

    def test_story_json_common_envelope(self):
        payload={"ok":True,"data":{"items":[{"id":"story-1","type":"image",
          "publishedAt":"2026-11-12T12:00:00Z","imageUrl":"https://cdn.example/story.jpg",
          "caption":"Story caption"}]}}
        rows=story_items(payload)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["shortcode"],"story_story-1")
        self.assertEqual(rows[0]["media_type"],"story")
        self.assertEqual(rows[0]["image_url"],"https://cdn.example/story.jpg")

    def test_empty_or_unrecognized_story_payload_is_safe(self):
        self.assertEqual(story_items({"ok":True,"data":{"items":[]}}),[])
        self.assertEqual(story_items({"ok":False}),[])

if __name__=="__main__":unittest.main()

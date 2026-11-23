import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))
os.environ["GITHUB_ACTIONS"] = "true"
import gate  # noqa: E402
import printful  # noqa: E402
import render_job  # noqa: E402
from plans import PLANS, fit_layer  # noqa: E402


def jpg(color, logo=None, size=1000):
    im = Image.new("RGB", (size, size), color)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, size // 4, size], fill=tuple(min(255, c + 90) for c in color))  # a visible edge so it is not blank
    if logo:
        d.ellipse([400, 400, 600, 600], fill=logo)
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


class Plans(unittest.TestCase):
    def test_layer_aspect_is_exact_and_inside_the_area(self):
        for name, plan in PLANS.items():
            for (w, h) in [(2215, 2721), (1800, 1800), (3000, 600), (500, 2000)]:
                L = fit_layer(plan, w, h)
                aw, ah = plan["area"]
                self.assertAlmostEqual(L["height"] / L["width"], h / w, delta=0.002, msg=name)
                self.assertLessEqual(L["left"] + L["width"], aw + 1e-3, name)
                self.assertLessEqual(L["top"] + L["height"], ah + 1e-3, name)
                self.assertGreaterEqual(L["top"], 0)

    def test_poster_art_shaped_like_the_poster_prints_full_bleed(self):
        L = fit_layer(PLANS["poster"], 3600, 4800)
        self.assertEqual((L["width"], L["height"], L["top"], L["left"]), (18.0, 24.0, 0, 0))
        small = fit_layer(PLANS["poster"], 2215, 2721)
        self.assertLess(small["width"], 18)

    def test_every_plan_has_a_flat_shot_and_models_only_where_reviewed(self):
        for name, plan in PLANS.items():
            self.assertIn("flat", plan["shots"], name)
        self.assertEqual({n for n, p in PLANS.items() if "model" in p["shots"]}, {"tee", "hoodie", "crewneck"})
        self.assertEqual({n: p["model_pin"] for n, p in PLANS.items() if "model" in p["shots"]}, {"tee": 798, "hoodie": 19737, "crewneck": 20456})


class Gate(unittest.TestCase):
    pal = [(228, 87, 46)]

    def test_logo_present_passes(self):
        ok, _ = gate.check_image(jpg((20, 20, 24), (228, 87, 46)), self.pal)
        self.assertTrue(ok)

    def test_missing_logo_fails(self):
        ok, why = gate.check_image(jpg((20, 20, 24)), self.pal)
        self.assertFalse(ok)
        self.assertIn("logo", why)

    def test_blank_and_small_and_garbage_fail(self):
        b = io.BytesIO()
        Image.new("RGB", (1000, 1000), (255, 255, 255)).save(b, "JPEG")
        self.assertEqual(gate.check_image(b.getvalue(), [])[1], "image is blank")
        self.assertIn("too small", gate.check_image(jpg((20, 20, 24), None, 500), [])[1])
        self.assertFalse(gate.check_image(b"nope", [])[0])

    def test_palette_ignores_colours_that_match_the_product(self):
        logo = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        d = ImageDraw.Draw(logo)
        d.rectangle([0, 0, 100, 200], fill=(228, 87, 46, 255))
        d.rectangle([100, 0, 200, 200], fill=(12, 12, 12, 255))
        pal = gate.logo_palette(logo, "#0c0c0c")
        self.assertEqual(len(pal), 1)
        self.assertGreater(pal[0][0], 200)


RECIPE = {"v": 2, "scene": 2, "type": "tee", "providerProductId": 71, "placement": "front", "logoUrl": "https://example.com/logo.png", "brand": {}, "size": [1000, 1000],
          "colors": [{"name": "Black", "hex": "#0c0c0c", "variantId": 4017, "shots": ["flat", "styled"]}]}


class Render(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.logo = Image.new("RGBA", (800, 900), (228, 87, 46, 255))
        rows = [{"placement": "front", "print_area_width": 12.0, "print_area_height": 16.0,
                 "mockup_styles": [{"id": 849, "category_name": "Flat", "view_name": "Front"}, {"id": 766, "category_name": "Flat Lifestyle", "view_name": "Front"}]}]
        self.created = []
        p = mock.patch.multiple(
            printful,
            style_rows=mock.Mock(return_value=rows),
            create_task=mock.Mock(side_effect=lambda *a: self.created.append(a) or 77),
            wait_task=mock.Mock(return_value={"x": 1}),
            mockups_by_style=mock.Mock(return_value={849: "https://files.cdn.printful.com/a.jpg", 766: "https://files.cdn.printful.com/b.jpg"}),
            download=mock.Mock(side_effect=lambda u: jpg((20, 20, 24), (228, 87, 46))),
        )
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(render_job, "fetch_image", side_effect=lambda u, d: (self.logo.save(d), self.logo)[1])
        q.start()
        self.addCleanup(q.stop)
        r = mock.patch.object(render_job, "absolute_logo_url", side_effect=lambda u, b: u)
        r.start()
        self.addCleanup(r.stop)

    def test_makes_one_webp_per_shot_at_the_native_size_with_one_task_per_colour(self):
        out = render_job.render_recipe(RECIPE, self.tmp, None)
        self.assertEqual(sorted((r["color"], r["shot"]) for r in out), [("Black", "flat"), ("Black", "styled")])
        self.assertEqual(len(self.created), 1)
        product, variant, placement, technique, layer, url, styles = self.created[0]
        self.assertEqual((product, variant, placement, technique, styles), (71, 4017, "front", "dtg", [766, 849]))
        self.assertAlmostEqual(layer["height"] / layer["width"], 900 / 800, delta=0.001)
        for r in out:
            im = Image.open(io.BytesIO(r["webp"]))
            self.assertEqual((im.format, im.size), ("WEBP", (1000, 1000)))

    def test_a_photo_without_the_logo_fails_the_job(self):
        printful.download.side_effect = lambda u: jpg((20, 20, 24))
        with self.assertRaisesRegex(RuntimeError, "quality check failed.*logo not found"):
            render_job.render_recipe(RECIPE, self.tmp, None)

    def test_missing_provider_style_is_a_visible_error(self):
        printful.style_rows.return_value = []
        with self.assertRaisesRegex(RuntimeError, "no 'Flat / Front' photo"):
            render_job.render_recipe(RECIPE, self.tmp, None)

    def test_old_or_unknown_recipes_are_refused(self):
        with self.assertRaisesRegex(ValueError, "older renderer"):
            render_job.render_recipe({**RECIPE, "v": 1}, self.tmp, None)
        with self.assertRaisesRegex(ValueError, "no photo plan"):
            render_job.render_recipe({**RECIPE, "type": "sticker"}, self.tmp, None)
        bad = json.loads(json.dumps(RECIPE))
        bad["colors"][0]["shots"] = ["flat", "label"]
        with self.assertRaisesRegex(ValueError, "shots not available"):
            render_job.render_recipe(bad, self.tmp, None)


class Client(unittest.TestCase):
    def test_find_style_matches_placement_and_area(self):
        rows = [{"placement": "default", "print_area_width": 9.0, "print_area_height": 3.5, "mockup_styles": [{"id": 1, "category_name": "Default", "view_name": "Front view"}]},
                {"placement": "default", "print_area_width": 9.0, "print_area_height": 3.8, "mockup_styles": [{"id": 2, "category_name": "Default", "view_name": "Front view"}]}]
        self.assertEqual(printful.find_style(rows, "default", (9.0, 3.5), "Default", "Front view"), 1)
        self.assertIsNone(printful.find_style(rows, "front", (9.0, 3.5), "Default", "Front view"))

    def test_downloads_only_from_provider_hosts(self):
        with self.assertRaises(printful.PrintfulError):
            printful.download("https://evil.example.com/a.jpg")
        with self.assertRaises(printful.PrintfulError):
            printful.download("http://files.cdn.printful.com/a.jpg")

    def test_token_is_required(self):
        os.environ.pop("PRINTFUL_API_TOKEN", None)
        with self.assertRaisesRegex(printful.PrintfulError, "not set"):
            printful.request("GET", "/v2/mockup-tasks?id=1")

    def test_only_mockup_endpoints_are_reachable(self):
        os.environ["PRINTFUL_API_TOKEN"] = "t"
        for bad in ["/orders", "/v2/orders", "/files", "/v2/mockup-tasks/../orders"]:
            with self.assertRaisesRegex(printful.PrintfulError, "not allowed"):
                printful.request("GET", bad)
        os.environ.pop("PRINTFUL_API_TOKEN", None)

    def test_retries_on_429_then_succeeds(self):
        os.environ["PRINTFUL_API_TOKEN"] = "t"
        import urllib.error

        calls = []

        class R:
            def read(self):
                return b'{"data": []}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout=0):
            calls.append(1)
            if len(calls) < 3:
                raise urllib.error.HTTPError(req.full_url, 429, "x", {"Retry-After": "1"}, io.BytesIO(b"slow down"))
            return R()

        waits = []
        with mock.patch.object(printful._OPENER, "open", fake):
            self.assertEqual(printful.request("GET", "/v2/mockup-tasks?id=1", sleep=waits.append), {"data": []})
        self.assertEqual((len(calls), waits), (3, [1, 1]))
        os.environ.pop("PRINTFUL_API_TOKEN", None)


if __name__ == "__main__":
    unittest.main()

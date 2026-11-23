import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "worker"))
import onmodel  # noqa: E402

Q = [[10, 10], [90, 10], [90, 90], [10, 90]]


class Gate(unittest.TestCase):
    def mk(self, entries):
        d = pathlib.Path(tempfile.mkdtemp())
        for e in entries:
            (d / e["image"]).write_bytes(b"x")
        (d / "approved.json").write_text(json.dumps(entries))
        return d

    def test_no_manifest_means_no_models(self):
        self.assertIsNone(onmodel.pick_model(tempfile.mkdtemp(), "tee"))

    def test_only_black_and_latino_with_owner_approval(self):
        d = self.mk([
            {"id": "a", "image": "a.jpg", "group": "white", "approvedBy": "o", "approvedAt": "x", "garments": {"tee": Q}},
            {"id": "b", "image": "b.jpg", "group": "black", "approvedBy": "", "approvedAt": "x", "garments": {"tee": Q}},
            {"id": "c", "image": "c.jpg", "group": "latino", "approvedBy": "o", "approvedAt": "2026-11-23", "garments": {"tee": Q}},
        ])
        self.assertEqual([m["id"] for m in onmodel.approved_models(d)], ["c"])
        self.assertEqual(onmodel.pick_model(d, "tee")["id"], "c")
        self.assertIsNone(onmodel.pick_model(d, "hoodie"))

    def test_composite_warps_onto_quad(self):
        from PIL import Image
        d = pathlib.Path(tempfile.mkdtemp())
        Image.new("RGB", (100, 100), (120, 120, 120)).save(d / "m.jpg")
        Image.new("RGBA", (50, 50), (255, 0, 0, 255)).save(d / "g.png")
        m = {"path": d / "m.jpg", "garments": {"tee": Q}}
        onmodel.composite(m, "tee", d / "g.png", d / "o.png")
        px = Image.open(d / "o.png").getpixel((50, 50))
        self.assertGreater(px[0], px[1] + 60)


if __name__ == "__main__":
    unittest.main()

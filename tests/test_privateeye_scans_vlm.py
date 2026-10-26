#!/usr/bin/env python3
# privateeye_scans.vlm_filled puts a clue the readers left blank to the VLM
# through ocr_clues.vlm_pick, and defers (clue stays blank) with the VLM down.
#
#     python3 tests/test_privateeye_scans_vlm.py
import os
import sys
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from PIL import Image
import privateeye_scans as ps

READ = ["1 Fruit that is red (5)", "2 Sea bird in a flap (4)"]
WORDS = {"a": [], "b": []}


def cols(_words):
    return [[(0, 0, 0, 0, t) for t in READ], [(0, 0, 0, 0, "3 Down below (4)")]]


class Fake:
    URL = "http://fake"

    class Down(RuntimeError):
        pass

    def __init__(self, up, reply="Sea bird in a flap (4)"):
        self.up, self.reply, self.asked = up, reply, []

    def wanted(self):
        return self.up

    def crop(self, img, box):
        return img

    def pick_in(self, image, lid, cands):
        self.asked.append((lid, cands))
        return self.reply


img = Image.new("RGB", (20, 20))
boxes = [(0, 0, 20, 20)]
laid = {"1-across": ("Fruit that is red", "5", None), "2-across": ("", "4", None),
        "3-down": ("Down below", "4", None)}
blank = {"2-across": "no two readings agree"}

vlm = Fake(True)
l2, b2, note = ps.vlm_filled(img, boxes, WORDS, cols, laid, blank, vlm=vlm)
assert not b2 and note == "", (b2, note)
assert l2["2-across"][0].startswith("Sea bird in a flap"), l2["2-across"]
assert vlm.asked and vlm.asked[0][0] == "2-across", vlm.asked

down = Fake(False)
l3, b3, note = ps.vlm_filled(img, boxes, WORDS, cols, laid, blank, vlm=down)
assert b3 == blank and l3 == laid and "deferred" in note and not down.asked, (b3, note)
print("ok")

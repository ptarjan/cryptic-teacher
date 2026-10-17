#!/usr/bin/env python3
# A light two linked groups share is one light, not two.
#
#     python3 tools/test_light_spec_shared_light.py
#
# Cyclops 147: across "15/52dn" (4,5), down "45/52" (6,3,5) and down
# "52 See 15". Both groups name 52 down; build_spec must give one 52 down.
import os
import sys
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "tools")
import light_spec

rows = {
    "across": [
        {"number": "1", "clue": "One", "enumeration": "5"},
        {"number": "15,52", "clue": "Shared head", "enumeration": "4,5"},
        {"number": "60", "clue": "Last", "enumeration": "5"},
    ],
    "down": [
        {"number": "1", "clue": "One down", "enumeration": "5"},
        {"number": "45,52", "clue": "Other head", "enumeration": "6,3,5"},
        {"number": "52", "clue": "See 15", "enumeration": None},
        {"number": "54", "clue": "After", "enumeration": "4"},
    ],
}
across, down, notes, damage = light_spec.build_spec(rows)
assert not damage, damage
assert [lg[0] for lg in down] == [1, 45, 52, 54], [lg[0] for lg in down]
assert [lg[0] for lg in across] == [1, 15, 60], [lg[0] for lg in across]
assert any("shared" in n for n in notes), notes
print("ok")

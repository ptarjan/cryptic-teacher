"""FT_FRAGMENTS_MENDED: a reread takes the whole Gale FT clue for a held one cut inside
(tools/file_archive_org_puzzles.ft_fragments_mended); 2003-12-10's held clues."""
import _path  # puts tools/ on sys.path
import pytest
import file_archive_org_puzzles as fa

FT = "Financial Times"
CUT = [
    ("Express disapproval, ing prohibition, for prim", "Express disapproval, during prohibition, for primate"),
    ("Moving boats with po from port", "Moving boats with poles from port"),
    ("Deal with drugs or do wi out?", "Deal with drugs or do without?"),
    ("Information in the p-1 on gas", "Information in the p-pipe on gas"),
    ("Type of butter unchar 100 in type of bog", "Type of butter unchanged in type of bog"),
    ("Home containing good st for baby", "Home containing good start for baby"),
]


@pytest.mark.parametrize("was,now", CUT)
def test_cut_clue_is_replaced_by_the_whole_one(was, now):
    assert fa.ft_fragments_mended(FT, was, now)


@pytest.mark.parametrize("was,now", CUT)
def test_only_the_ft_takes_it(was, now):
    assert not fa.ft_fragments_mended("The Times", was, now)


@pytest.mark.parametrize("was", ["River shed", "Divine drink with 10 for 100 in 2004", "Newspaperman rioted dis gracefully"])
def test_a_clue_that_reads_as_held_stays(was):
    assert not fa.ft_fragments_mended(FT, was, was)


def test_a_changed_whole_word_is_not_a_fragment():
    assert not fa.ft_fragments_mended(FT, "Boy gets beaten", "Boy gets beater")
    assert not fa.ft_fragments_mended(FT, "Take it or leave it", "Take it or leave")

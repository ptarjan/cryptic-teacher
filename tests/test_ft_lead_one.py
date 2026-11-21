"""FT_LEAD_ONE: a Gale FT lead window is split in two only at a real gutter (tools/file_archive_org_puzzles.ft_lead_split)."""
import _path  # puts tools/ on sys.path
import file_archive_org_puzzles as fa

GRID = (1802, 2705, 2482, 3356)
LEAD = (1246, 2677)


def words(cross):
    """Clue lines x 1397-1764, `cross` of them through x 1628, the rest ending before it; one word each."""
    return [[(1397, 2700 + 30 * i, 1764 if i < cross else 1600, 2720 + 30 * i, "word")] for i in range(12)]


def test_column_crossed_by_its_lines_is_one_window():
    lines = words(12)
    assert len(fa.lead_split(lines, GRID, LEAD)) == 4  # the shared split cuts it
    assert len(fa.ft_lead_split(fa.GALE_FT, lines, GRID, LEAD)) == 3


def test_clear_gutter_stays_split_and_other_papers_are_untouched():
    lines = words(0)
    assert len(fa.ft_lead_split(fa.GALE_FT, lines, GRID, LEAD)) == 4
    crossed = words(12)
    assert fa.ft_lead_split(fa.GALE, crossed, GRID, LEAD) == fa.lead_split(crossed, GRID, LEAD)

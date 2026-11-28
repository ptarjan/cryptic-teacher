"""A refusal cause added after the frozen RANKS: "prize-heading" (a Gale Independent on Sunday title under the Prize
Crossword heading, which files as indysunday from the blog and feed, not as the Beelzebub). Its "refused <cause> before
its fix" text is ranked like every other cause's, 2; the due test is the one the other refusal causes share
(due_reason, over REFUSALS), so this reason names no `due` of its own."""
from fix_reasons import Reason

REASON = Reason("refused prize-heading before its fix", rank=2)

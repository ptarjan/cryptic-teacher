# Desktop-idle task: checkpoint (stopped for the bridge restart, ~10:20 MDT 2026-10-14)

## Done (committed and pushed)
- tools/desktop_hosts.json: LAN address 192.168.1.180 changed to 192.168.1.198.
- ocr_remote.py: `prune` now goes through prune_any(hosts()), trying each host in by_path order, the same as connect().

## Findings so far (root cause NOT confirmed)
- connect() already loops over every host (by_path: LAN first, then tailnet), so "only the first host is tried" is not the cause for sessions.
- pid 10205 (edition_queue run, parent 10202, OCR_REMOTE=micro@192.168.1.180,micro@100.68.145.15) has NO child processes. It is sitting in a wait or fetch stage, not reading.
- /tmp/desktop_busy.json: `{"why": null, "reading": null, "free": [<12 min old>, 20841]}`. The last probe got no answer from ANY host, even though desktop_busy.SSH sets HostKeyAlias=100.68.145.15. Next: run `desktop_busy.probe("micro@100.68.145.15")` by hand to see why it returns None (it could be a timeout or bad JSON under load 28; the 60 s timeout is swallowed silently).
- edition_queue gates worker starts on desktop_room() / free_mb ("desktop-bound: ... only fetches start"). Suspect: with reading=None and a stale `free` value, desktop_room() may refuse to start desktop-bound workers. Check edition_queue.desktop_room and what happens when the free reading is old.
- Log: /data/home/.cache/corpus_queue/full_pass.log. The last "reading on" lines are from 08:31 on .180. The 04:33 "unavailable" line names only .180 (the line was cut off in the output, so check whether the tailnet host appears after it).

## Remaining
1. Confirm the root cause above and fix it in code. Options: verify the LAN host by its host key and fall back; desktop_room should not hold workers when the probe is stale.
2. Regression test in tools/test_ocr_remote.sh (prune_any falls through to the next host; connect falls back from a failing LAN host).
3. Alert (coordinator's addition): when OCR_REMOTE is set and no desktop host works (and it is not a game-yield), or the VLM is unreachable, send one alert per episode via tools/alert.sh, plus a one-line alert when a stale LAN IP was fallen back from. Rate-limit with a state file, never one per edition. Test that it fires (ALERT_ENV_FILE pointed at a stub wake.sh).
4. Check the VLM: curl http://192.168.1.198:8090/v1/models (and 100.68.145.15:8090).
5. Restart pid 10205 via the restart argv of track-job job /data/tracked-jobs/1791993033-1456.json ("corpus OCR full pass", corpus_queue chain, which resumes). Then count tesseract/python on the desktop with `ssh micro@100.68.145.15 tasklist` and record the container load (it was 20.18 at 10:16).
6. Name which container CPU users could move to the desktop. Candidates: the reconstruct_grid search (already in ocr_remote.CALLS, so check the reindex path uses it), the pdf_pages call, and the scan/parse step (headings, grids_on).
7. Confirm the next CI run on master is green.

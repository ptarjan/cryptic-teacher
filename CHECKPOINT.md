# Desktop-idle task: still open (2026-10-14 10:40 MDT)

- Relaunch the corpus OCR full pass. The bridge restart killed pid 10205. Its relaunch then failed with "Could not parse object 'origin/master'" (a zero-byte object, d428eb9ca2, since repaired). Its tracked-job entry was removed. Relaunch it from /data/home/.cryptic-teacher/corpus_queue with `track-job.sh --restart --run "corpus OCR full pass"` and the corpus_queue chain argv. A worktree-isolated agent's guard refuses this command.
- After the relaunch: count tesseract.exe/python.exe on the desktop with `ssh micro@100.68.145.15 tasklist`, and check the container load.
- The desktop's LAN IP flaps between .180 and .198 (at 10:33 .180 answered and .198 timed out). desktop_hosts.json lists both, ahead of the tailnet. A DHCP reservation on the router would end this for good.
- The VLM is up on 100.68.145.15:8090. On the LAN, 192.168.1.198:8090 refuses connections (firewall or bind address), so vlm_reader has to fall through to the tailnet URL.
- Confirm the next CI run on master is green.

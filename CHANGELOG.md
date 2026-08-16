# Changelog
All notable changes to Mysterium Node Toolkit are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## v1.4.8

An override for nodes the Mysterium PPA cannot reach, and a version block that describes the node you are actually looking at.

- feat (install a node release from GitHub, bypassing APT): `myst-updater` only accepts packages from the Mysterium PPA. That PPA has no suite for Debian, trails the GitHub tags by two minor versions, and refuses to touch a node whose package was installed from a `.deb` by hand — leaving those nodes with a timer that fails every six hours and no way forward. `bin/node_update.sh` is the deliberate override: it takes a version number and nothing else, derives the architecture itself, and rejects anything that is not three numbers separated by dots. It downloads only from the `mysteriumnetwork/node` release path, verifies the SHA256 that GitHub publishes per asset before handing anything to dpkg, falls back to `apt-get install -f` when dependencies are missing, and reports failure if the node does not come back up. A release without a published digest is installed on the strength of HTTPS alone and says so rather than claiming to be verified. The button sits beside the version badge, asks for a second click that names how many sessions the restart will drop, and is disabled when you are viewing a remote node — passwordless sudo does not cross machines, so a fleet install would die halfway through
- fix (the version block described the wrong machine): `nodeUpdateInfo` was fetched with a bare `fetch('/api/node-update-check')` on mount with an empty dependency array — always the local backend, never re-fetched on a node switch. Viewing a remote node from the fleet master therefore showed the master's updater state and APT candidate underneath the remote node's name. Harmless-looking on a fleet of three where every machine runs the same distribution; on a mixed fleet it means reading one machine's package state for all of them. The fetch now goes through `getNodeAwareUrl()`, re-runs when the selected node changes, clears the previous answer first so a failed fetch cannot leave stale data on screen, and waits for `isConnected` because the proxy route requires auth
- chore: `update.sh` restores the executable bit on `bin/*.sh` and the root wrappers. Files copied by hand out of a browser download lose it, and git does not restore it on a file it already tracks — which would surface as a permission error with no obvious cause on a script invoked through sudo

## v1.4.7

The node's own updater was failing on every run while the dashboard reported it as healthy.

- fix (the self-updater badge promised an update that could never arrive): `_node_self_updating()` asked `systemctl is-active myst-updater.timer` and read `MYST_UPDATER_ENABLED`, then reported a boolean. Both were true on the VPS and the Pi while `myst-updater.service` exited 1 on every cycle, so the version badge read `1.39.3 — self-updating` on a node that had been failing to update for days. The timer being active says nothing about the service getting anywhere. The state now also carries the outcome of the last run, read from `systemctl show`, which needs neither root nor journal access, and the badge distinguishes four cases: on, on but failing every run, off, and not installed. The version badge only claims a pending self-update when the last run actually succeeded
- note (why it fails is not a toolkit problem, but it is now visible): `myst-updater` only installs candidates that come from the Mysterium PPA. On Debian trixie that PPA has no suite at all, which gives `authenticated APT metadata for origin LP-PPA-mysteriumnetwork-node was not found`. On a machine where the node was installed from a GitHub `.deb`, that hand-installed package outranks the PPA version and APT offers it as the candidate, which gives `candidate 1.39.2 is not supplied by the Mysterium node PPA`. The PPA also trails GitHub by some distance — 1.37.9 on focal and 1.38.5 on noble against 1.39.3 tagged. The tooltip on a failing badge names the command that shows which of the two applies
- feat (the dashboard now says what APT itself would install): knowing that the updater fails is half an answer. `apt-cache policy myst` holds the other half and needs no root, so its verdict is read and shown as one line beside the version. Three cases are named: no Mysterium PPA present on this system at all, a PPA outranked by a package installed from a `.deb`, and a PPA that has something newer waiting. A node whose package tracks the PPA normally shows nothing, and a system without apt shows nothing rather than an empty badge. Cached fifteen minutes — long enough not to re-read the package lists on every poll, short enough that adding the PPA and running `apt update` shows up while you are still looking at the screen

## v1.4.6

Health checks that report on things they could not actually see, and a chart that drew a line through periods when nothing was measured.

- feat (the router's port mappings are now checked): every reachability check looked at this machine only — is 4050 listening, are the service ports bound, what NAT type does the node report. None of that says whether traffic from outside ever arrives, so a failed UPnP mapping left the node running, every local check green, and quality at 0.00 with no stated cause. A new Router Port Mapping subsystem reads the IGD through `upnpc` and reports what it finds. It offers no fix on purpose: repairing a mapping means overriding what the node does for itself, and `--port-mapping.enable-upnp` does not exist — passing it stops the node from starting
- feat (a second node behind the same router is now named): two nodes competing for the same external port end with the IGD keeping one winner and the other going quiet, with no error anywhere. A mapping pointing at another internal address on a port this node also claims is reported as critical, with the address and the contested ports
- fix (the NAT fallback answered "working" without checking anything): its comment claimed it inspected UPnP mappings; it asked the node for its service list and concluded NAT was fine as soon as anything was running. That is the green answer that made a broken port mapping so hard to find. It now says `unknown`
- fix (the metrics chart drew a straight line across periods with no data): points were placed by array index and joined into one polyline. A stretch where the toolkit was not running produces no rows at all, so the line ran through the gap as though the machine had been measured throughout, and an hour and a week occupied the same horizontal distance. Points are now placed by timestamp, and the line breaks wherever the interval exceeds three times the normal sampling distance. A single reading between two gaps is drawn as a dot rather than vanishing, and the label counts the gaps
- fix (the CPU governor service raced the other services that set the same value): the unit carried only `After=multi-user.target`, which says nothing about cpupower, cpupower-gui or cpufrequtils — all of which write `scaling_governor` too. Whichever ran last won, so on a Parrot laptop schedutil survived while the toolkit reported success. Ordered after them in both places the unit is written
- fix (setup wrote a fixed nf_conntrack_max that contradicted the health check): `99-mysterium-node.conf` pinned 524288 at install time while the Connection Tracking check has sized it against tunnel count since v1.4.5. Two sources disagreeing about the same value, and the install-time one reserved roughly 150 MB of kernel memory on nodes that never need it. Removed from the file; the health check is the only source. `netdev_max_backlog` is written there instead of being left to a script
- fix (the fleet master could not read itself once TLS was on): enabling TLS changes what port 5000 serves, but nothing revisits nodes.json. The master's own entry is normally http://localhost:5000, so from that moment it was speaking plain HTTP to a port that only speaks TLS — every card for the master answered 502 while the other nodes were fine. Self-referencing entries are corrected at startup with a warning naming the file to update, and `setup.sh --tls-only` now says which entries will need attention
- fix (the fleet proxy never verified TLS at all): the proxy request carried no verify argument, while every other peer request goes through `_peer_verify()` to pin the self-signed certificate. An https node with a pinned certificate therefore worked for the collector and failed through the proxy
- fix ("Overhead" was everything the machine did, not tunnel overhead): the row showed NIC total minus VPN traffic, which on a fleet master is SSH, package updates, polls to the other nodes and Tailscale. It read 12.93 GiB against 238.9 MB of VPN traffic, inviting the conclusion that the tunnels wasted fifty times their own volume. Split into an estimated tunnel overhead — roughly the VPN volume itself, since each byte crosses the NIC twice — and Other traffic, which on a master is normally the largest of the three. The Help text said NIC total was VPN plus overhead; that only holds on a machine doing nothing else
- fix (a tagged release with no files was offered as an available update): the check compared version tags and nothing else. Node 1.39.0 was tagged on 13 August 2026 with zero assets and was not in the PPA either, so the dashboard offered an update that neither apt nor the installer could deliver — the installer answers "No .deb found for arch=..." through no fault of the operator. The tag is now reported as tagged but not published, and the update is only offered when a .deb exists
- fix (a rotated log sat in the directory forever): an oversized log is set aside as `backend.log.oversized` on the first start after rotation was introduced, and then nothing ever touches it again — RotatingFileHandler manages .1, .2 and .3 and knows nothing about it. One install carried 32 MB from August onwards on a machine where disk space is watched. It is now removed after seven days, with a line saying how large it was
- feat (the node's self-updater state is visible): node 1.39.x installs myst-updater.timer, which changes the node version on its own six-hourly schedule — worth knowing on a machine where an unannounced restart matters. The dashboard reads both switches, the timer and MYST_UPDATER_ENABLED, since an active timer with the flag off does nothing at all. Reporting only, not toggling: the config file belongs to the node package, its format is theirs to change, and writing it would need a sudo right on /etc/default that the toolkit has no other use for. The one-line command to disable it is in the reference
- fix (the Add/Edit Node dialog ran off the bottom of the screen): it had no height limit and no scroll, so on a laptop screen or any phone the lower half was simply unreachable — including Save Changes. It grew worse in v1.4.5, which added the TequilAPI field and the TLS block to the same form. The dialog is now capped to the viewport with a scrolling body, while the header and buttons stay in place. Measured at 390x700 and 1280x768
- change (the fleet card said "Peer mode" and "TequilAPI mode"): both described the plumbing rather than the thing the operator cares about, which is what data is available. They now read "Toolkit node — full history" and "Node API only — live data"
- fix (the health panel showed the state that prompted a fix, not the one after it): pressing Fix refreshed the metrics but never ran a new scan, so the checks on screen still described the situation from before. A fix that had worked looked like it had failed, and one that had not looked fine — three separate debugging sessions went down that path across a VPS and a laptop. Fix now triggers a scan, and the result block carries the time it was produced, so an old one is recognisable as old
- fix (RPS being off read as "will apply shortly" even when that was the point): the message dates from when off meant not-yet-applied or never-configured, both faults. Since the IDS check it can also be the intended end state, so the line contradicted the one directly above it and held the whole subsystem at amber on a correctly configured machine
- fix (setting RPS failed on every install that is not root): `_write_file` falls back to `sudo tee` when /sys refuses a direct write, but sudoers only allowed tee for `scaling_governor` — so every RPS write on a normal user install failed, three red crosses in a row, with passwordless sudo working fine for everything else. The rule now covers `rps_cpus`
- fix (one problem needed two Fix buttons under two subsystems): clearing RPS from the primary interface only holds if the watcher script stops rewriting it, and that script is regenerated by a different subsystem's fix. Nothing on screen connected the two, so the fix appeared to do nothing. CPU Load Balancing now regenerates the watcher script as part of its own fix
- fix (the RPS watcher rewrote the primary NIC every 30 seconds): the persisted boot script and the watcher timer both set RPS on the primary interface unconditionally, so clearing it through the health check lasted at most half a minute before the timer put it back. Three places were writing the same value with different intentions. Both generated scripts now check for a running IDS at run time — not at generation time, so installing or removing one later needs no regeneration
- fix (the IDS warning could not be cleared by the button offered next to it): the RPS check warned that Suricata was already balancing the interface, while Fix & Lock went on setting RPS on that same interface — so the warning returned after every fix. Fix now leaves the primary interface alone when an IDS is running, clears any mask set before the IDS was installed, and keeps RPS on the tunnel interfaces where it helps. The check reports ok once RPS is off there
- feat (dashboard passwords are hashed): the password was stored as typed in setup.json and .env, compared directly, and printed on screen by the setup wizard — a backup or a support paste carried the credential itself. New passwords are stored as salted scrypt from the standard library, and comparison is constant-time. Existing plain-text values keep working, so upgrading locks nobody out. The wizard now says the password cannot be read back and to write it down
- feat (RPS is flagged when an IDS balances the same interface): Suricata, Snort and Zeek in af-packet mode distribute flows across their own workers. RPS on that interface distributes again, by a different key, and the two disagree — measured on a laptop running Suricata with cluster_flow: 2.6x difference in packets between workers and 0.41% drops. Not corrected automatically, since which one should give way depends on what the machine is for, but no longer invisible
- feat (rx-usecs reports what it costs, not just its value): 250µs caps interrupts at roughly 4000/s, which is what stops the e1000e freezing, but it also delays every packet by up to a quarter of a millisecond and lets the ring buffer run fuller. The check now states both, so the trade-off is visible before anyone tunes it
- docs (where the toolkit actually logs): README and reference pointed at `journalctl`, which on most installs shows little more than sudo entries — the application writes to `logs/backend.log`. Three turns were spent looking in the wrong place before noticing. Both now name the log file first
- docs (apt and GitHub can disagree about node versions): the toolkit adds no package repository of its own — it runs the project's own install.sh, which picks its source. That source can lag the GitHub releases by days, as it did when 1.39.2 was published while apt still offered 1.38.5. The reference explains this and gives the direct .deb route. Also recorded: `provider_tunnel_ip` from node 1.39.0 lives in the connection contract, the consumer side, so it never has a value on a provider — nothing for the toolkit to read
- fix (the port mapping check warned about all three healthy nodes): absence of a UPnP mapping is not by itself a fault. A node on a public address maps nothing because there is nothing to map, and hole punching — traversal defaults to manual,upnp,holepunching — carries sessions without any mapping at all. The first version reported "inbound traffic will not reach this node" on a VPS, a laptop and a Pi that were all earning normally, which is the same kind of confident wrong answer the check was written to replace. It now reads the node's NAT type and session count first, and only warns when there is no mapping, no public address and no sessions either
- feat (the node's own update timer is recognised): node 1.39.x installs `myst-updater.timer`, six-hourly with up to six hours of jitter, so the node updates itself from now on. Offering our own button beside that has two things racing over one package, and the reported version can change without anyone touching the dashboard. When the timer is active the badge says so instead
- fix (the CLI stopped working the moment TLS was enabled): it had no notion of TLS — no verification setting anywhere, and a hard-coded http:// default. Against a toolkit with https_enabled it reported "Cannot connect" for a backend that was running perfectly well. The scheme and port now come from the same config the backend reads, requests go through a session that carries the TLS setting to all eight call sites at once, and `--insecure` covers remote nodes. Verification is skipped for this machine's own certificate, where it could never succeed
- chore (project knowledge files can no longer be committed by accident): START.md, CONTEXT.md, CLAUDE.md and PROTOCOL.md describe machines, SSH ports and working agreements. They belong in the Claude project, not in a public repository, and are now in .gitignore
- chore (build metadata): `.build/package.json` claimed version 4.9.8, which matches nothing. Set to the toolkit version. lucide-react was pinned at 0.263.1 because npm treats a caret on a 0.x version as patch-only, so it had been frozen since April — moved to 1.31.0, with all eleven icons in use verified against the new release

## v1.4.5

Data from one node appearing under another node's name, in three separate places, plus two blocks of dead code that made a subsystem recommend the wrong thing. Fleet routing, migration identity gates, and composite keys on the earnings and traffic tables.

- fix (the dashboard drew the fleet master's numbers under a remote node's name): `getNodeAwareUrl()` decided where to fetch from by inspecting `metrics._fleet_node`, which is only populated after the first metrics response arrives. Opening a URL like `/?node=pi-node` therefore sent every self-fetching card — traffic, earnings history, system metrics, analytics, settlements — to the LOCAL backend for its first round, and the fleet master's figures were drawn under the remote node's heading. The same fallback fired again whenever a fleet poll failed, silently and for as long as the failure lasted. Routing now keys off `selectedNodeId`, which is read straight from the URL and is correct on the very first render. An unknown id gets a 404 from the proxy, which is visible, instead of the wrong machine's data, which is not
- fix (a card kept showing the previous node's data after a failed switch): every card holds its own state and its fetch handler swallowed failures (`.catch(() => setLoading(false))`), so a card that had loaded node A and then failed to load node B carried on displaying A's numbers indefinitely. Reported from a phone, where the timing window is wide enough to catch it: the fleet master's 131-day earnings history sat under a Pi that had been running for one day. Every node-bound card now remounts on a node change, and the earnings card reports a load failure instead of leaving the old figures on screen
- fix (Connection Tracking always recommended 524,288 regardless of load): `ConntrackHealth` defined `scan()` and `fix()` twice. Python keeps the last definition, so the adaptive tier logic added earlier — 128K below five tunnels, 256K to nineteen, 512K above — was unreachable dead code, along with `target_for_load()` and the TIERS table. A Pi at 0.2% table usage was told its table was too small for a VPN exit and offered a table taking roughly 150 MB of kernel memory. `py_compile` reports nothing for a duplicate method
- fix (the adaptive tier could never leave its lowest step): `fix()` took `tunnel_count=0` as its default and both callers, `fix_all()` and `fix_one()`, call it without arguments. It now counts `myst*`, `wg*` and `tun*` interfaces itself
- fix (five identical helper methods defined twice in CpuGovernorHealth): same pattern, no behavioural difference — both copies were identical — but it is the failure mode that hid the conntrack bug, so it is gone
- fix (importing a backup handed this install another node's history): three places in migrate_data.py read a missing identity file at the destination as "same machine, update flow" and copied sessions, earnings and uptime across. That assumption is right for an update and wrong for `--import`, where the source may be any node's backup. The check now lives in one place, `_same_node()`, and only trusts a missing destination identity during a local update. Skips state the reason
- fix (a fresh install could inherit the source node's identity): `node_identity.txt` was copied with `copy_if_missing`, so an install importing another node's backup adopted that node's identity outright. Everything downstream then agreed the two were the same node, and `upsert_sessions` stamped this node's own sessions with the foreign provider id. It is now copied only during a local update
- fix (earnings snapshots merged across nodes without any check): the JSON merge deduplicated on `time` alone and had no identity gate at all. Snapshots carry node-specific lifetime totals and no node field, so after the merge nothing could tell the two apart. Same gate as the databases now
- fix (setup.json copied a possibly foreign beneficiary in silence): the address drives the on-chain earnings lookup. On an import that cannot be confirmed as the same node, the result line now says so
- fix (provider_id backfill overwrote the evidence of a mixed database): the schema migration states that empty provider_id rows may belong to a different, migrated node and must not be backfilled — and the startup backfill then stamped every empty row with the local identity anyway, turning imported foreign sessions into local ones permanently. It now refuses when the table holds rows from another node, and logs which ones
- fix (system metrics with no node id were counted for every node): the fast tier writes a snapshot every five minutes but `_local_node_id` is only set once the slow tier has reached the node, so early writes landed with an empty node id — and `get_history()` matched `node_id = ? OR node_id = ''`, folding those orphans into whichever node you happened to open. On a live Pi that was 24 of 79 rows. The write path now falls back to the identity file, the queries no longer match empty, and a one-shot backfill claims existing orphans — refusing if the table holds more than one node
- fix (Edit Node could not save anything): the form was filled from the fleet status payload, which carries no `toolkit_api_key` — by design, since keys do not belong in a status feed. The key field therefore came up empty, `Save Changes` stayed disabled on `!fleetForm.toolkit_api_key`, and renaming a node was impossible without pasting the key again. The form now reads from `/fleet/config`, and the key stays on the server: leaving the field empty means unchanged, and the backend keeps the stored key. The field shows the last six characters so it is clear which key is in place
- fix (editing a node could erase it from nodes.json): the save matched the node by `toolkit_url` — the very field being edited — so changing a URL matched nothing, the node was dropped from the rewritten file, and nothing said so. Matching is now on `id`, a failed match refuses to save, and saving while the config has not loaded is blocked. That combination is the most likely cause of the two broken entries in August
- fix (a fleet save could empty nodes.json entirely): the backend accepted an empty node list without question. It now refuses when nodes are configured on disk, unless `confirm_empty` is passed
- fix (TequilAPI URL missing from the fleet form): `fleetForm` never had a `url` field, so a node added through the UI got no TequilAPI address written at all. Added as an optional field; port 4449 is still corrected to 4050 by the loader
- fix (Test Connection would have broken on edit): with the key field now intentionally empty, the probe would have answered 401 for a perfectly good node. It falls back to the stored key, matched by node id
- fix (fleet cards showed a different set of rows per node): NAT was hidden when the node reported nothing, which is exactly what a node on a public IP does — so the VPS card silently lacked a row the others had. It now reads `No NAT (public)`. The projected daily figure was a separate item that disappeared at 100% uptime, giving the one node below 100% an extra column; it now hangs off the uptime figure as `Up: 85.4% → 5.0904/day at 100%` and is simply absent when it would repeat Today's number
- fix (fleet cards printed raw NAT values): the label table lived inside the node dashboard, so the fleet cards showed `prcone` where the node view showed `Port Restricted` — the same split that `fmtType()` once had. Moved to module level as `fmtNat()`; both views read one table
- fix (nodes.json hot-reload took minutes, not seconds): the watcher ran on `cycle % 30`, which counts poll rounds rather than seconds. One round lasts FLEET_POLL_INTERVAL, so the documented thirty seconds was really five minutes at the default and longer at higher intervals — which is why fleet edits appeared to need a restart. It now checks thirty seconds of wall clock. The watcher also lived only in the fleet collector, which does not run while the fleet is empty, so adding the very first node did nothing until a restart; the single-node collector now watches too and starts the fleet collector when nodes appear. And the recorded mtime was only updated when nodes were found, so a briefly empty or malformed file counted as changed on every pass, forever
- fix (update.sh checked the wrong part of .git): the ownership repair tested `.git/objects` only. On the Pi it was `.git/logs` that root owned while objects was fine, so the check passed and the pull then died on "unable to append to .git/logs/refs/remotes/origin/dev". It now scans the whole tree, and registers `safe.directory` when git refuses a repository outright
- fix (every pull failure blamed the network): the message read "check your network or repo access" regardless of cause, including two that were neither — a root-owned .git and git's dubious-ownership guard, both hit on the same afternoon. The git output is now read and the actual cause named, with the command that fixes it
- fix (miniupnpc was never installed): the node maps ports over UPnP by default and the port-reachability check reads the IGD through `upnpc`, but no installer step ever provided it — it had to be installed by hand. Added alongside the other tools, for every supported package manager
- fix (successful data repairs were invisible on a Pi): pi_mode drops the logger to WARNING, so the backfill that claimed 24 orphaned snapshots reported nothing and the only proof was querying the database directly. Outcomes that changed rows on disk now report at WARNING where INFO is suppressed
- feat (Help explains the numbers): four sections added — fleet card fields including what the projected daily figure means, the NAT types and what each costs in earnings, the four service types against their raw API names, and the System Health states with what Fix &amp; Lock, Fix only and Unpersist each do
- fix (Test Connection reported 404 for a perfectly healthy node): the probe requested `/health`, an endpoint that does not exist — so it answered "Toolkit returned HTTP 404" for nodes the fleet collector was polling successfully at that moment. It now uses `/api/version`, and a 404 there says the address is probably the node API rather than the toolkit
- fix (typing in the edit dialog was silently reverted): the config fetch that fills the form arrives a moment after it opens and used to overwrite every field. Adding the "s" to https:// in that window meant watching it disappear. It now fills only the fields still holding their original value, and only while the dialog is still showing the same node
- fix (an https address in the TequilAPI field took the node out of the fleet): the node API serves plain HTTP and binds to loopback — TLS there is never possible. The field accepted it anyway, and the node went offline with an SSL error against port 4050. Corrected on entry and again on save, the same way port 4449 is corrected to 4050
- docs (README and reference did not mention what the installer actually supports): the compatibility table listed distributions but no architectures, while setup.sh detects x86_64, arm64 and armv7 separately, warns that armv6 has no Node.js 18 build, and falls back to direct downloads from nodejs.org and a Debian snapshot on EOL distributions. Raspberry Pi went unmentioned entirely, although the wizard reads `/proc/device-tree/model` and enables pi_mode — WARNING log level to spare the SD card, and a thread pool of 10 instead of 30. All of it is now written down
- docs (credits were incomplete): flask-cors, python-dotenv, react-dom, PostCSS, Autoprefixer and the Vite React plugin were all in use but uncredited, as were the system tools the installer pulls in — ethtool, miniupnpc, conntrack-tools, irqbalance, lm-sensors, curl, fail2ban and Tailscale. The API list named two of the six services the privacy table lists; both tables now agree. Split into backend, frontend, system tools and external APIs
- docs (deploy_production.sh puts nginx in front of cheroot): that made sense when Flask's development server was doing the serving. Cheroot is a production server, so the two overlap. Noted in the reference rather than left for someone to discover
- fix (chart bars and several panels kept emerald colours in every other theme): the theme mapping covered `bg-emerald-500` and the /5, /10, /20 and /30 opacity variants, but not /15, /25, /35 or /70 — and the earnings chart draws its bars with `bg-emerald-500/70`. So in all ten non-emerald themes those bars stayed green while everything around them changed. Found while rendering the documentation screenshots
- fix (an unreachable node was labelled "No NAT (public)"): the empty NAT value that means "public IP, no translation" is also what an offline node reports, so the new NAT row stated a fact about a machine that could not be contacted at all. Offline nodes now show a dash
- feat (earnings snapshots and daily traffic record which node they came from): both tables keyed rows on time alone — `time` for snapshots, `date` for traffic — so two nodes writing in the same second collided and INSERT OR IGNORE dropped the second without a word, while nothing recorded which node any row belonged to. Both are rebuilt with a composite primary key of (time, provider_id) and (date, provider_id), in a transaction that rolls back and leaves the original table untouched if any row fails to carry over. Existing rows are attributed to this node's identity, read from the identity file. The five write paths now stamp the node, including the traffic upsert whose `ON CONFLICT(date)` clause no longer matches a composite key and would otherwise have failed on every write

## v1.4.4

Session token amounts above ~9.22 MYST were being truncated on write — SQLite's signed 64-bit integer cannot hold wei. Tokens moved to TEXT, affected rows corrected automatically. Plus the auto-update toggle, TLS fields in the fleet UI, and a fail2ban filter that had been matching a log cheroot no longer writes.

- feat (auto-update can be turned on and off from the dashboard): the hourly timer runs update.sh by itself whenever the VERSION on this install's branch differs from the local one, and until now the only way to stop that was systemctl on the command line — the dashboard gave no sign that automatic updates were happening at all. New endpoints `GET /api/autoupdate` and `POST /api/autoupdate` report and change the timer state, with a toggle next to the version in the header. The state distinguishes enabled, disabled, timer not installed, and systems without systemd (LXC, Alpine), so a container install shows nothing rather than erroring. Requires no sudoers change: `systemctl enable/disable mysterium-*` was already permitted, under both /bin and /usr/bin paths
- fix (adding a fleet node through the UI dropped its TLS settings): the add form built a node object from four fields only, so `tls_cert` and `tls_verify` could not be set through the dashboard at all and had to be written into nodes.json by hand. Editing was safe — the spread preserved unknown fields — but a node added through the UI could never use the TLS support added in v1.4.0. The form now has a certificate path field and a verification checkbox, shown only when the URL is https, and both are written on add as well as edit
- fix (Test Connection could not reach an https node): `/fleet/probe` called the node without a `verify` parameter, so a self-signed toolkit certificate failed CA validation. The three probe requests now honour the same `tls_cert` / `tls_verify` fields the fleet collector uses, and the same applies to `/fleet/test/<id>`
- fix (the fail2ban jail has detected nothing since the move to cheroot): the filter matched a web-server access log line (`^<HOST> -.*".*" 401`), which werkzeug wrote. cheroot writes no access log at all, so from v1.4.4 onward the jail loaded, reported zero bans and saw nothing — worse than having no jail, because the dashboard presented it as working protection. The filter now matches a line the application writes itself, which does not depend on the web server. update.sh replaces the old filter automatically and verifies the jail loads afterwards; /api/fail2ban-health reports `filter_outdated` for an install still carrying the old pattern
- fix (authentication failures logged the proxy's address, and three of four paths logged nothing): only the invalid-API-key branch logged, and it used `request.remote_addr` — the immediate peer, which behind a proxy or tunnel is not the client. All four rejection paths now log through one helper that reads X-Forwarded-For, so fail2ban has a real address to ban. Verified against the filter for IPv4, IPv6 and forwarded addresses
- fix (the auto-update toggle returned 403 over Tailscale or any published address): the POST route also required `is_local_request()`, which trusts only loopback and RFC1918. A dashboard opened over Tailscale (100.64.0.0/10) or a public address got a 403, and since neither the route nor the UI logged anything, clicking the button simply did nothing. `@require_auth` is the appropriate gate: an API key already permits restarting the node and changing payment settings through the fleet proxy. Widening `is_local_request()` was the alternative and was rejected — it would hand the auth bypass on every route to any CGNAT address
- fix (failed toggle requests were applied as if they had succeeded): the UI merged non-200 responses into its state and showed no error, so a rejected request was indistinguishable from a working button. Failures are now shown next to the toggle
- fix (update.sh reported "Frontend rebuilt" when the build had failed): the check accepted any existing dist/index.html as proof of success, so a failed build left the previous bundle in place while the update reported success — new UI features then appeared to be missing with no error anywhere. The most common cause is dist/ being owned by root while the build runs as the service user; update.sh now corrects ownership on dist/ as well as config/ and backend/, reports build failures honestly, and names the chown command when it sees EACCES
- fix (TLS could not be enabled after installation): the TLS step existed only inside setup.sh, so an install that skipped it had no way to turn it on short of editing setup.json by hand. The certificate generation is now a function, reachable through `setup.sh --tls-only` and from the CLI menu under Security & Upgrades, which also shows the current TLS state, regenerates a certificate after an address change, prints the certificate for copying to a fleet master, and can turn TLS off again
- fix (setup reported TLS as enabled when the config write had failed): the certificate alone does nothing — https_enabled in setup.json is what activates it. The write used the venv interpreter, which does not exist yet when running --tls-only on a fresh checkout, and its failure was not checked. It now falls back to the system interpreter and verifies the setting afterwards, printing the manual edit if it could not be written
- fix (start.sh always printed http:// URLs): with TLS enabled the dashboard URL shown by the CLI menu produced a browser error that looked like the dashboard was down. The scheme now follows https_enabled, including the Tailscale and network URLs
- fix (migrate_all.py created settled_tokens as INTEGER): the same overflow that truncated session tokens before v1.4.4 — wei exceeds SQLite's signed 64-bit range at 9.23 MYST. The column is TEXT now. The script is not called by setup, update or the backend; a note to that effect was added
- docs (setup and wizard showed nodes.json without TLS): both templates now include an https node with tls_cert and explain that toolkit certificates are self-signed and therefore have to be pinned, and that a fleet may mix http and https nodes
- docs (Help section covered neither TLS nor auto-update): added sections on enabling TLS, pinning certificates for a fleet, what happens when a node's IP address changes, and what the auto-update timer does
- docs (README: two node-side listeners that surprise people): the node's SSDP service binds to a random high port that changes on every restart, and its Web UI binds to the machine's LAN address — which on a VPS is the public IP — when ui.address is left empty. Both are node defaults the toolkit does not control, now documented with the flags to change them
- docs (deploy_production.sh): the script claimed CC BY-NC-SA 4.0 while the project is AGPL-3.0, and recommended nginx as a reverse proxy without noting that the backend has served itself through cheroot with keep-alive and built-in TLS since v1.4.4
- fix (the auto-update toggle crashed the dashboard with a ReferenceError): the handler was declared inside the `if (metrics.fleet?.fleet_mode && !selectedNodeId)` branch, which is the fleet overview, while the button itself renders in the node dashboard further down — a different scope. Anyone viewing a node dashboard got "toggleAutoUpdate is not defined" and the whole page failed to render. A successful build does not catch this: the reference only resolves at render time. The handler now sits above the fleet branch so both views can reach it
- fix (the auto-update toggle never appeared when the dashboard was opened remotely): the timer state was fetched on mount, before the first successful /metrics call had populated the auth header, so `/api/autoupdate` returned 401. The response was discarded, the state stayed null and the toggle hid itself with no visible error. Locally this went unnoticed because `is_local_request()` trusts loopback; over Tailscale it did not, since those addresses are in the CGNAT range rather than RFC1918. The fetch now waits for the connection to be established, and both requests use the fleet-aware backend URL instead of a relative path
- fix (a certificate failure was reported as an unreachable node): `requests.exceptions.SSLError` subclasses `ConnectionError`, so the broader handler caught it first and the UI said "check URL and port forwarding" when the real problem was an unverified certificate. The SSL handler now comes first and returns a message naming the certificate, with a `tls_error` flag
- fix (session token amounts above ~9.22 MYST were truncated on write): upsert_sessions clamped every incoming value with `min(_raw_tokens, 9223372036854775807)` because `sessions.tokens` was an INTEGER column. SQLite's signed 64-bit INTEGER tops out at 9223372036854775807 wei, which is 9.223372 MYST, so any session worth more than that was stored short and the real amount was discarded. Verified against a live node running 1.38.5: session a8e09bbb was reported by the node as 13779037025053810949 (13.779 MYST) while the database held the clamp value -- 4.556 MYST lost on a single session. The column is now TEXT, which stores wei exactly, and existing databases are migrated in place on startup
- note (this was not a node-side artifact, contrary to the v1.3.10 note): the node declares tokens as a Go `*big.Int` in both `consumer/session/session.go` and `tequilapi/contract/session.go`, serialised to JSON as a number with unlimited precision, and applies no cap of its own. Python's json parser reads such values exactly. The truncation happened entirely inside the toolkit at the point of writing to SQLite. The earlier description of a "node-side token-clamp value" was incorrect and delayed finding this
- fix (frozen token values could be overwritten after the migration): the upsert preserved a previously recorded amount using `excluded.tokens > 0`. In SQLite any TEXT value sorts above any INTEGER, so once the column became TEXT that test was true even for '0' and '', meaning a zeroed API response would have wiped a real recorded amount -- the exact failure the freeze mechanism exists to prevent. The comparison now uses `CAST(excluded.tokens AS REAL) > 0`
- feat (clamped rows are corrected automatically): the upsert already prefers a non-zero incoming value, so a row still holding the clamp value is replaced with the real amount as soon as the node serves that session again. No manual repair step is needed. Sessions the node has already forgotten keep the truncated amount permanently; `/api/database-health` now reports how many rows are still affected via `clamped_token_rows`
- fix (the rollup was rebuilt from corrected sessions): daily totals had been aggregated from clamped session values and were short by the same amount. The migration clears the rollup as part of its own transaction rather than relying on startup ordering -- the background collector can call the rollup backfill before the startup hook runs, and an already-populated rollup would otherwise never be rebuilt
- fix (lifetime and integrity totals summed tokens as floating point): the daily integrity log and the session statistics used `SUM(CAST(tokens AS REAL))`, which drops the low digits of a wei total. Both now sum as Python integers, so the figures are exact
- fix (every read path converts the stored value before doing arithmetic): two places read session rows straight from the database and divided the token amount by 1e18 to get MYST. With `tokens` now a TEXT column both raised `TypeError: unsupported operand type(s) for /: 'str' and 'float'` -- the consumer aggregation in the sessions endpoint and the same calculation in /consumers/top. The first was caught and logged as "Error fetching sessions", leaving the session list empty; the second returned HTTP 500 -- caught during testing before release. No data is affected either way; only the read path was involved
- feat (single conversion helper for stored token amounts): added `_tokens_to_myst()` and `_tokens_to_int()`. Four separate read paths did arithmetic directly on the stored value -- the consumer aggregation in the sessions endpoint, /consumers/top, the analytics block that reads SessionDB, and the per-country earnings breakdown. Each raised `TypeError: unsupported operand type(s) for /: 'str' and 'float'` once the column became TEXT, and each was caught by a different handler, so they surfaced one at a time rather than together. Every read of a token amount coming from the database now goes through one of these helpers
## v1.4.3
- fix (the permanent earnings rollup never recorded a single row): `daily_totals.tokens` was an INTEGER column, but token amounts are aggregated in wei. SQLite's signed 64-bit INTEGER tops out near 9.2e18, which is under 10 MYST, so a single day of earnings overflowed the column. Every insert raised `OverflowError: Python int too large to convert to SQLite INTEGER`, the exception was caught by the caller and logged at debug level, `_backfilled` stayed False, and the whole cycle repeated on the next pass. On the install where this was found the table had existed since late June with 2803 sessions available to aggregate and zero rows written. The column is now TEXT, which keeps wei exact -- REAL would round and quietly corrupt the earnings figures. Existing databases are migrated in place on startup, preserving any rows already present
- fix (rollup totals were summed as floating point): `get_totals` used `SUM(CAST(tokens AS REAL))`, which loses the low digits of a wei total -- measured at ~52000 wei of drift across three days of test data. Totals are now summed as Python integers, so lifetime earnings are exact
- fix (rollup write failures were invisible): `_upsert` had no error handling of its own and the caller logged failures at debug level, so a rollup that had never written anything looked identical to one that was working. Write failures now go through the shared database failure tracking added in v1.4.2 and appear in `/api/database-health`
- note: the rollup exists so that daily earnings totals survive session pruning. Because it was empty, lifetime figures were being derived from the session table alone; installs with pruning enabled may have lost earnings history that the rollup was meant to preserve. Pruning is opt-in and off by default

## v1.4.2
- fix (firewall opened the node's default UDP range instead of its configured one): setup.sh had `10000:60000` hardcoded, matching the node's default for `udp.ports`. An operator who widened that range to `10000:65000` in `config.toml` ended up with 5000 ports the node listened on but ufw dropped. Inbound p2p connections failed, latency reported by Discovery rose into the seconds, and nothing anywhere reported a cause. Setup now reads `udp.ports` from `/etc/mysterium-node/config.toml` (or `/var/lib/mysterium-node/config.toml`), opens that exact range, and prints which range it found; the old default remains the fallback when no node config is readable
- fix (fail2ban filter was written without sudo, so the jail never loaded): the filter file was written with plain `tee` while the jail file three lines below used `$SUDO tee`. Running setup as a normal user meant the write to `/etc/fail2ban/filter.d/` failed with permission denied, the error went to stderr, and setup still printed "fail2ban configured". fail2ban then logged "Unable to read the filter" and skipped the jail entirely, leaving the dashboard with no brute-force protection and no indication of it. The filter is now written with sudo, and setup verifies afterwards that both files exist and that `fail2ban-client status` actually lists the jail, reporting a clear failure instead of assuming success
- fix (backend.log grew without bound): logging used a plain `FileHandler`, so the file only ever grew — one install reached 154 MB, which fail2ban then had to scan on every pass. Now a `RotatingFileHandler` at 10 MB with 3 backups, capping the logs directory at roughly 40 MB. On first start after upgrading, an existing oversized log is moved to `backend.log.oversized` rather than being appended to indefinitely. Both limits are overridable with `LOG_MAX_BYTES` and `LOG_BACKUP_COUNT`
- fix (database write failures were invisible): the databases moved to `backend/databases/` in v1.2.28, but update.sh only corrected ownership on `config/`. On one install a sudo migration left the database files owned by root while the service ran as a normal user: SQLite could not write, the database modules caught their own exceptions and returned False, the callers ignored that return value, and `quality_history`, `service_events` and `system_metrics` recorded nothing for six weeks with no visible sign. update.sh now corrects ownership on `backend/` as well and verifies afterwards that every database is writable by the service user, and the callers check the return value instead of only watching for exceptions
- feat (new endpoint `/api/database-health`): reports per database whether the file is writable, its size and when it was last modified, plus any write failures recorded at runtime. Checking the filesystem directly catches exactly the failure above, which is invisible to a caller that only sees swallowed exceptions
- feat (new endpoint `/api/fail2ban-health`): distinguishes between fail2ban not installed, not running, filter missing, jail file missing, jail present but not loaded, and healthy. The existing jail listing returns an empty list in every one of the failure cases, which is indistinguishable from a working install with no bans
- docs (firewall port range): the README described the range as fixed at the node default; it now documents that setup follows `udp.ports` from the node config and that changing it requires re-running setup

## v1.4.1
- fix (backend failed to start on v1.4.0 -- NameError on `_serve`): v1.4.0 replaced the `app.run()` call with `_serve(app, PORT)` but placed the function definition after the `if __name__ == '__main__'` block that calls it, so Python reached the call before the name existed and the service died on every start. The function now sits above the entry point. This slipped through because `py_compile` accepts it (the syntax is valid) and importing the module does not execute the `__main__` block -- validation now starts the app as `__main__` and checks that it answers on its port, over both HTTP and HTTPS

## v1.4.0
- feat (TLS support for the dashboard and for fleet peer traffic): the dashboard and the `/peer/data` endpoints can now be served over HTTPS using a self-signed certificate generated locally by setup.sh (step 12.55). No domain name, no Let's Encrypt, no certbot and no reverse proxy are required -- the certificate carries the machine's IP addresses and, optionally, a hostname in its SAN. The fleet master pins that certificate per node via the new `tls_cert` field in nodes.json, which binds the connection to that one certificate rather than trusting any public certificate authority. `tls_verify: false` is available for nodes whose address changes: traffic stays encrypted but is no longer authenticated, so it is only appropriate on a trusted network. Off by default -- an existing install is unaffected until `https_enabled` is set, and a mixed fleet of HTTP and HTTPS nodes is fully supported
- feat (production WSGI server replaces the Flask development server): `app.run()` was Flask's built-in development server, which sends `Connection: close` on every response. Every request therefore opened a fresh connection, and under TLS that means a fresh handshake -- measured at ~360 ms to open the dashboard over HTTPS against ~35 ms with keep-alive, and 80 ms against 13 ms for 150 concurrent requests. The dashboard is now served by cheroot: a single process with a thread pool (30 threads, 10 in pi_mode, override with `server_threads`), TLS built in, and about 1 MB more resident memory. Falls back to the Flask server if cheroot is missing or DEBUG is enabled
- feat (update check follows the branch the install is on): `/api/update-check` and the auto-update timer wrapper both had the `main` branch hardcoded in the raw GitHub URL. An install checked out on another branch compared its own version against main's and reported an update indefinitely. Both now read the branch from `git rev-parse --abbrev-ref HEAD`, falling back to main for a detached HEAD or a non-git install, and the update-check response carries the branch name
- docs (README privacy claim corrected): the header claimed "no third-party service, no data leaving your server", which was not accurate. Six outbound destinations exist, two of which receive identifiers -- the provider ID goes to `discovery.mysterium.network` and the beneficiary address plus your own API key go to `api.etherscan.io`. Both identifiers are already public, on the discovery service and on the Polygon blockchain respectively, but they were undocumented. The new "Privacy and outbound connections" section lists every destination and what it receives, and states plainly what never leaves the machine: session records, consumer addresses, earnings history, traffic figures, metrics, logs and keys. There is no telemetry and never has been
- docs (new TLS section, and fleet transport security spelled out): documents certificate generation, per-node pinning, the browser warning for a self-signed certificate, mixed fleets, and why a certificate issued for a bare IP address breaks when a provider changes that address -- along with the point that `nodes.json` holds a stale address in that case whether or not TLS is in use. Fleet Mode now recommends running the master on a machine with a stable public address

## v1.3.13
- fix (v1.3.12 "dead session" rule corrected -- it mislabeled live top-earning sessions): v1.3.12 marked any New session with 0 bytes / 0 tokens older than 10 minutes as "(dead -- final write lost)", reasoning from the node's keepalive that multi-hour New rows could not be live. Debug logs from a live node disproved this: three days-old New/0/0 B2B sessions were receiving consumer keepalive pings every ~5 seconds (2,870 per session per 4h window, zero failures) and held 10.37 / 2.48 / 0.32 MYST of in-memory SessionTokensEarned totals -- live, paying, top-earning sessions that v1.3.12 hid from the Active tab and labeled dead. Root cause of the confusion is node-side: provider sessions are persisted only at create and clean close, so a live multi-day session legitimately reports New/0/0 over the API its entire lifetime. The filter is now restricted to the only case provable from the API alone: rows whose started_at predates the current node process (session objects cannot survive a restart), labeled "(orphaned -- predates node restart)". All post-boot New/0/0 sessions are shown as active with bytes pending. The pre-v1.3.12 4-hour ghost demotion is likewise gone -- it hid the same live sessions
- docs (Help section rewritten to match the corrected, log-verified picture): "Dead Sessions & Lost Data" is now "Long-Running Sessions, 0-Byte Rows & Lost Data" -- explains that New/0/0 can be a live earner, that all mid-session state exists only in node memory riding on one droppable final write, and that only pre-restart rows are provably orphaned
- note: the SessionDB duration freeze from v1.3.12 (only Completed overwrites duration_secs) is unchanged -- it remains correct for both live sessions (exact value arrives at close) and orphaned rows (prevents unbounded fake growth)

## v1.3.12
- fix (dead 'New' sessions no longer shown as live with fake ever-growing durations): sessions stuck at status New with 0 bytes and 0 tokens are dead sessions whose final write the node lost, not live tunnels. Verified in mysteriumnetwork/node source (v1.38.5): the provider keepalive closes unreachable consumers within ~95 seconds (core/service/session_manager.go), the final bytes/tokens write goes through a capacity-100 non-blocking queue and is silently dropped when full (consumer/session/session_storage.go), and the API fabricates duration = now - started on every call for New rows (GetDuration, Updated is zero). The old 4-hour ghost window is replaced by a 10-minute dead-session filter: such rows are marked "(dead -- final write lost)", excluded from active counts, and their duration shows as em-dash instead of a fake number
- fix (SessionDB no longer stores ever-growing fake durations): the upsert overwrote duration_secs with the API value on every poll, so dead New rows accumulated days of fabricated duration in the archive, polluting statistics. duration_secs is now only overwritten when the incoming status is Completed (the node's exact final value); for New rows the first recorded value is kept frozen
- feat (Help -- "Dead Sessions & Lost Data" section): documents the node-side session accounting verified in node source: bytes/tokens persist only on create / paid invoice / clean close, the live counters exist only in node memory, the final write can be silently dropped, the first invoice of every session is literally 1 wei, and why fast-moving tunnel data can legitimately appear on no session at all -- so operators seeing "data without a session" find the explanation in the dashboard instead of suspecting the toolkit

## v1.3.11
- fix (probe classification no longer broken by 1-wei artifact sessions): the node occasionally emits sessions with tokens=1 (1 wei = 1e-18 MYST) -- a node-side artifact, not a real payment. The strict ==0 / >0 earnings comparisons in probe detection and the paying-consumers count meant a single 1-wei session flipped a probe-pattern consumer (e.g. Mysterium quality-monitoring agents doing many tiny sessions) into a "paying" consumer and suppressed its wrench probe flag. Both /metrics and /consumers/top now use a shared PROBE_EARNINGS_EPSILON threshold (1e-6 MYST): earnings at or below it count as zero for classification. The smallest real payment observed on a live node is ~1.3e-5 MYST, so real payers are unaffected
- feat (Consumer history modal now shows the probe verdict): the wallet history modal showed only country flags and "Earned: --" with no probe indicator, while the Consumers list showed the wrench icon for the same wallet -- making the Mysterium monitoring agent (many small sessions since months, zero tokens) look like a non-paying freeloader. /sessions/by-wallet now computes is_probe in its summary using the exact same criteria as the consumer list, and the modal header shows a "Mysterium monitoring agent" badge with an explanatory tooltip when it matches

## v1.3.10
- feat (daily data-integrity log): a new append-only log (backend/databases/integrity_log.jsonl), written at most once per calendar day, records total sessions, unique consumers, a safe token sum (CAST AS REAL, avoids the SQLite integer-overflow crash on SUM(tokens)), and the count of sessions stuck at the exact node-side token-clamp value. Readable via GET /data/integrity-log. Purpose: independent, tamper-evident evidence that counts never decrease -- the operator can verify this directly instead of relying on any assistant's word. At roughly 114 bytes/day (about 40 KB/year, 400 KB/decade) this never needs rotation or cleanup, including on storage-constrained devices like a Raspberry Pi
- fix (session-based earnings fallback no longer looks like a real total): when the identity API is temporarily rate-limited, the dashboard fell back to showing the raw session-token sum in the same large, bold style as the real Unsettled figure, with only a faint caption. Per-session tokens are known to be an incomplete accounting basis (a session that never closes cleanly on the node never gets its true final amount recorded -- a node-side characteristic, not a toolkit bug), so this number can legitimately read far lower than real lifetime earnings. It's now shown smaller, in amber, with an explicit warning that it's an approximate, possibly-understated estimate, not a real total

## v1.3.9
- tune (fleet light-poll interval raised to 10s): the v1.3.8 default (60s) made live metrics (speed, temperature, CPU/RAM, ping, tunnels) feel sluggish when actively viewing a remote fleet node's dashboard. Raised to 10s -- still roughly 35x less bandwidth than the pre-v1.3.8 design (about 2 GB/month per remote node at 10s vs about 68 GB/month and growing, previously), while keeping the dashboard responsive
- fix (fleet Peak clients always showed 0): the frontend hardcoded peak: 0 when viewing a remote fleet node, discarding the real peak_clients value the backend already tracks. /peer/data (light response) and the fleet collector now carry the real clients (connected + peak) field through, and the frontend uses it
- fix (traffic history artificially capped at 30 days for fleet peers): TrafficDB keeps every day permanently (no storage-level limit -- it imports full vnstat history back to before the toolkit even existed), but the fleet /peer/data heavy fetch only ever requested a 30-day window. Changed to request the full history (days_back=None), matching how earnings_history already behaves -- no functional risk, the data was always there, just under-requested
- fix (uptime-log retention raised from 31 to 365 days): the source-level uptime ping log pruned entries older than 31 days, a real (if minor) permanent-loss risk for an operator who wants long-term history. Raised to 365 days, matching the retention convention already used for earnings. The 24h/30d uptime percentages themselves are unaffected -- only how long the underlying raw pings are kept before pruning

## v1.3.8
- fix (major fleet-peer bandwidth reduction): the fleet background collector polled every configured remote node's FULL /peer/data (unbounded earnings history, 30-day traffic, session-archive stats, logs) roughly every 3-5 seconds, permanently, regardless of whether that node was even being viewed. Measured impact: on the order of 1-2 MB/minute per remote node today, growing unbounded over the node's lifetime as earnings_snapshots accumulates (calculated: current ~1.6 MB/min per node, rising to 68+ MB/min after 6 months). Fixed with two changes: (1) /peer/data now accepts ?light=1, returning only live/summary fields and skipping the heavy history/logs entirely; the fleet collector uses this for its routine poll. (2) The heavy fields are fetched in full once per calendar day per node and cached, merged into the light data in between -- so charts and history still populate, just refreshed daily instead of every few seconds. Poll cadence for the fleet collector also moved to a new, dedicated FLEET_POLL_INTERVAL (default 60s, independent of UPDATE_INTERVAL which still governs the local node's own fast metrics cache for the 5s frontend poll -- unrelated and unchanged). Net effect for a typical single-remote-node fleet setup: roughly two orders of magnitude less background bandwidth, and the cost no longer grows with node age. The three other, occasional /peer/data callers (node test, setup, identity lookup) are untouched -- only the recurring collector poll changed

## v1.3.7
- fix (significant bandwidth reduction -- Consumers list no longer sent on every poll): the full consumer array (top_consumers, unbounded -- 1000+ entries on an active node) was embedded in every /metrics response, sent by default every 5 seconds regardless of whether the Consumers tab was even open. Confirmed via nethogs on a live node as a major contributor to sustained backend network egress. It is now fetched via a new on-demand endpoint, GET /consumers/top, called only when the Consumers tab is opened -- the same pattern already used for wallet history. The lightweight summary counts (unique/paying/probe consumer counts) still update on every poll for the tab counter; only the heavy per-consumer array moved off the polling path

## v1.3.6
- fix (firewall UDP range narrowed to match the node's own default): setup.sh opened 10000-65000/udp, wider than the node's actual `udp.ports` default of 10000:60000 (verified against node source). Narrowed to 10000-60000 so the firewall opens exactly what the node uses by default -- no functional loss, since nothing listens above 60000 unless the node's own udp.ports is manually widened, in which case the firewall range should be widened to match on that specific node
- feat (payment config panel): added the real key payments.settle.max-fee-percentage (node default 0.05) -- a gas-efficiency check that decides WHEN the node bothers to auto-settle below the Max Unsettled ceiling, separate from Hermes's fixed 20 percent cut. Help text rewritten to state the fixed 20 percent up front as a constant fact, clearly separated from this fee-timing setting so the two are never conflated again
- docs (README -- payment config table corrected): still listed all 7 pre-v1.3.3 keys including the 4 phantom ones removed from the actual panel, and the old unsettled-max-amount dash key. Replaced with the 4 real keys the panel now has
- docs (README -- pruning/Data Management corrected): described automatic daily pruning with default retention windows as active out of the box; this has been opt-in only since v1.3.1/v1.3.3. Rewritten to state history is kept indefinitely until retention is explicitly saved via the Data Manager, and that editing setup.json by hand does not enable it
- docs (README -- missing install steps added): setup.sh's Step 12a (systemd re-apply on re-run), Step 12.5 (optional fail2ban) and Step 12.6 (optional Tailscale) exist in code but were never documented in the install walkthrough. Added
- docs (README -- preset names synced): 'Node Defaults'/'High Load' corrected to the actual UI labels 'Standard . Stable Node'/'High Load . 50+ Sessions'

## v1.3.5
- fix (Unsettled Earnings showed an inflated, ever-growing number right after a real settlement): the dashboard fell back to a raw 30-day sum of all session tokens (session_total — can be 20, 100, 200+ MYST, never reset) whenever unsettled reached 0, which is exactly the normal, correct state right after a settle. So a genuine 0-after-settlement was replaced by a large stale-looking number, making it seem like the toolkit had not registered settlements that had already landed on-chain. The fallback now only triggers when the identity API is genuinely unreachable (rate-limited/blocked), never on a real zero balance
- fix ('Last pruned' date in Data Manager updated even when nothing was deleted): the once-per-day run guard and the 'last actually pruned' timestamp shared one variable, so the guard stamped today's date even when no retention was configured and nothing was removed — making the Data Manager look like it silently purged data every day. The run guard now uses its own variable; the displayed 'Last pruned' date only updates when rows were actually deleted

## v1.3.4
- fix (observed-active showed ~50 months-old zombie sessions as Active): the node's /sessions list permanently contains stale 'New' rows that were never closed (e.g. after a node crash), and every fetch refreshed their last_seen, so the last_seen window alone let them all through — inflating the Active counter to 50 and burying the real consumers. A live session cannot predate the node process that owns it, so observed-active now also requires started_at to be after the node process start (fallback: last 7 days when no myst process is visible). Months-old zombies are gone; genuine multi-day consumers still show. This was a structural flaw in the observed-active filter since v1.2.48, not caused by v1.3.3
- fix (wallet history did not open in fleet views): /sessions/by-wallet was missing from the fleet proxy endpoint whitelist, so on a fleet master viewing another node (?node=...) the history fetch was rejected. Added to the whitelist
- improvement (wallet address itself is now clickable): in the Consumers tab the wallet address opens the history modal directly — the small arrow button also remains. Clicking the wallet is the natural gesture; the tiny arrow alone was easy to miss

## v1.3.3
- feat (wallet history view): every consumer wallet in the Consumers tab now has a 'history' button that opens a theme-following modal with that wallet's full archived session history (time, country, service, data up/down, earnings) plus a summary (total sessions, total data, total earned, first seen). Backed by a new GET /sessions/by-wallet endpoint reading sessions_history.db — the per-wallet audit view: exactly when and how much each address used your node
- fix (payment config verified against the Mysterium node source, v1.38.3): the Max Unsettled setting wrote payments.unsettled-max-amount (dash), but the node reads payments.unsettled.max-amount (dot, node default 20) — earlier values were silently ignored; the key is now correct, so re-apply your value once after updating. Four settings were removed because the node never reads them at all: Manual Settle Min (payments.settle.min-amount), Min Promise Amount (payments.min_promise_amount), Balance Check Interval (pingpong.balance-check-interval + session.pingpong companion) and Promise Wait Timeout (pingpong.promise-wait-timeout — the provider-side wait is a hardcoded 50s constant in the node). TequilAPI stores any key it is given without validation, which is why these appeared to work. Presets now contain only real keys and the 'Read before using' help text was rewritten to the node's actual fee-driven settlement mechanics (settles when the threshold is reached AND the tx fee is under ~5% of the amount, forced at the max ceiling; the fixed 20% Hermes fee explains why a 12.5 threshold arrives as ~10 MYST)
- fix (duplicate 'B2B Data Scraping' chip): Discovery returns separate proposals for scraping and quic_scraping, which share one display name; the per-service quality chips now dedupe on the display label
- fix (daily auto-prune is now truly opt-in): the setup wizard pre-wrote a data_retention block with defaults into setup.json at install, which made every install look user-configured and defeated the v1.3.1 opt-in — the daily prune kept deleting history nobody asked to expire. Pruning now additionally requires data_retention_enabled: true, which is set only when the operator saves retention in the Data Manager; the wizard no longer pre-writes retention defaults. Existing installs stop pruning automatically until retention is saved again deliberately

## v1.3.2
- fix (unsettled earnings display lagged behind after a settle): the medium-tier settle detector called a method name that does not exist (get_identity_earnings instead of _get_identity_earnings), so every check raised an AttributeError that was silently swallowed by its debug-level except. As a result the detector never ran: after the node auto-settled in the background, the dashboard kept showing the climbing pre-settle unsettled balance (e.g. ~13 MYST) until the regular 10-minute slow-tier poll happened to refresh, or until a manual Settle click forced a refresh. Fixing the method name restores prompt (~1 min) reflection of both auto and manual settles. Regression introduced in v1.2.38; node payments themselves were always correct — only the toolkit display was affected. No routes, config keys, or fleet logic touched; behaves identically on solo and fleet-master
- fix (settle-detect failures were invisible): the except around the settle detector logged at debug level, so the AttributeError above never surfaced in the journal at the default log level. It now logs at warning level, so any future failure of the settle detector is visible without enabling debug logging

## v1.3.1
- fix (data retention — auto-prune is now opt-in, never deletes on defaults): the daily automatic prune previously used built-in default retention windows (sessions 90d, system/services 30d, etc.), so it would eventually delete history the operator never chose to expire. It now prunes ONLY the data types for which the operator explicitly set a retention in the Data Manager (config/setup.json -> data_retention). With nothing configured, all history is kept indefinitely. Manual delete and retention settings in the Data Manager keep working exactly as before. This matches the rule that a purge must only happen when set or executed via the Data Manager

## v1.3.0
- feat (CLI — consumers and tunnels): the terminal dashboard (cli/dashboard.py) now shows, on the Status page, the observed-active consumers with their real wallets (service, duration, data, earnings) and the live tunnels with their idle/transferring status — the same honest data as the web UI. The CLI reads the backend /metrics API so it stays in sync automatically, and it stays light enough for slow laptops and older Raspberry Pi devices. Previously the CLI only showed an active-sessions counter with no consumer or tunnel detail
- fix (idle tunnel indicator — option B, consistent for every tunnel): a tunnel is now marked idle when it is connected but has carried no meaningful traffic in the last 60 seconds, instead of being judged on its lifetime-average throughput. The old average-based test wrongly kept high-volume tunnels from ever going idle (a consumer that moved gigabytes but is now quiet stayed 'active') and pinned low-volume tunnels as permanently idle even during a burst. The 60-second window uses real traffic only (never keepalives) so the label reflects the actual moment-to-moment state without flickering each refresh
- docs: README updated — CLI section now documents the observed-active consumers and idle tunnel display; the session-analytics section describes observed-active reporting and the option-B idle indicator accurately

## v1.2.50
- fix (idle label no longer wrong on active tunnels): a tunnel is now only marked 'idle' when it is moving almost nothing BOTH over its lifetime AND right now. Previously the label used only the lifetime-average throughput, so a tunnel transferring at this moment (e.g. 315 B/s) but with a low lifetime average was wrongly shown as idle. Added a not-has-speed guard so a currently-transferring tunnel is never labelled idle
- fix (System Health — duplicate Uptime row and recurring false warning): the Mysterium Service health check assessed every myst process, so a second process (e.g. a separately started noop service) added its own Uptime/Memory row and its fresh start raised a 'recent restart' warning that Fix & Lock couldn't clear. The check now assesses only the main (oldest) node process, so there is a single Uptime row and no spurious restart warning
- fix (mobile — connections rows no longer overlap): the observed-active and recently-closed session rows used a fixed 12-column grid that overflowed on narrow phone screens, overlapping time and byte columns. They now stack cleanly on mobile (wallet + flag on top, service/duration/data/earnings wrapping below) and keep the 12-column layout on desktop

## v1.2.49
- fix (Active counter matches the observed-active list): the connections 'Active (N)' counter previously showed 0 whenever the node's live API reported no active sessions, even while the Observed-active list below it showed real consumers — the counter and the list contradicted each other. The counter now falls back to the observed-active count (the real wallets seen in the node's session log within the last 10 min) when the API reports zero, so 'Active' matches what is shown. This does not double-count tunnels: observed-active are wallets from the session log, a separate source from the Tunnels tab. The raw API value is still available as active_api for reference

## v1.2.48
- feat (sessions — observed-active consumers, real node data, no guessing): the connections list now shows 'Observed active' consumers when the node temporarily stops reporting live sessions while the tunnel keeps running. Every time the node surfaces a session, the toolkit already records it in the local session log (sessions_history.db) with the real consumer wallet, time and bytes. A new SessionDB.get_observed_active() returns the sessions we genuinely saw active within the last 10 minutes that are not yet Completed — real wallets the node actually reported, shown with a cyan dot and clearly labelled. Once the node reports the session Completed, its final bytes/tokens land in the archive and it drops out of the observed list. This restores the operator's view of who is currently using the node across the window where Mysterium drops live session status, without fabricating anything. Works on all three install types (full, fleet master, lightweight) — the data is stored locally and forwarded to the master via /peer/data

## v1.2.47
- feat (sessions — recently-closed consumers, real node data): when the node reports no live-active sessions, the connections list now also shows recently-closed sessions (started within the last 10 minutes) with the real consumer wallet, time, data and service, clearly labelled 'Recently closed' with a grey dot — not disguised as live. Mysterium never exposes live-active sessions over any API (they live only in the node's in-memory map; /sessions returns only closed sessions from storage), so a just-closed session is the genuine, non-guessed way to keep the operator's view of who used the node. This restores the recent-consumer visibility without fabricating anything. Backed by a new recently_closed flag per session and recently_closed_count in the response
- fix (EUR price — Frankfurter host moved): the USD→EUR rate fetch used api.frankfurter.app/latest, which now 301-redirects and silently dropped the EUR price. Switched to api.frankfurter.dev/v1/latest (the current host). USD (CoinPaprika) was unaffected; EUR is shown again

## v1.2.46
- fix (live sessions — honest reporting, no more guessing): the connections list no longer fabricates active sessions. Previously, when TequilAPI reported zero active sessions while WireGuard tunnels were still live (the node drops session status while the tunnel persists via keepalives), the toolkit promoted the most recent history rows to 'active' — which showed the wrong consumer (e.g. a low-traffic monitoring probe) while the real multi-GB tunnel had no visible session. The node's tunnel-to-wallet mapping lives only in its in-memory event bus and is never exposed over any API, and `wg show` yields only peer public keys, so that attribution is fundamentally unknowable. The session list now shows only what the node genuinely reports; when it reports no active sessions but tunnels are live, the UI says so and points to the Tunnels tab, which is the source of truth for live throughput (with the idle indicator from v1.2.45). A new tunnels_without_session field backs this
- change (probe label — honest wording): the 🔧 marker on low-traffic non-paying connections now reads "Likely monitoring probe — 0 earnings, tiny sessions (behavioural inference)" instead of asserting "Mysterium network probe". The detection is a behavioural heuristic (Mysterium does not publish these wallet addresses), so the label no longer claims more than is known. The marker itself is unchanged and stays useful for separating probes from paying consumers
- docs: README now documents the honest live-session behaviour (session list = what the node reports, Tunnels tab = source of truth for live traffic) and the behavioural basis of the 🔧 probe label; stale in-code comment about using interface count as ground truth for active sessions removed

## v1.2.45
- feat (firewall — never lock out SSH): setup no longer force-enables an inactive firewall (that could activate a default-deny ruleset with no SSH rule and lock you out of a VPS). It now only adds allow-rules to a firewall that is already active, and always whitelists the real SSH port(s) FIRST — detected from sshd_config (and sshd_config.d), defaulting to 22 but honouring custom ports. When no firewall is active, required ports are already open and none is forced on. Works across all supported backends (ufw, firewalld, nftables, iptables)
- fix (firewall — P2P range): the Mysterium UDP range is now opened up to 65000 (was 60000), matching nodes that use udp.ports 10000:65000
- feat (fail2ban — isolated jail.d file): the toolkit jail now lives in its own /etc/fail2ban/jail.d/mysterium-toolkit.conf instead of a managed block inside jail.local, so it can never conflict with a user's existing jail.local. Existing installs are migrated automatically — the old jail.local block is stripped (sshd, recidive and any other user jail are left untouched). The toolkit only ever creates the mysterium-dashboard jail; it no longer creates or rebuilds an sshd jail, and the save endpoint now refuses any non-toolkit jail name
- feat (Tailscale — optional): setup now asks whether to use Tailscale for private dashboard access (default no). It detects Tailscale and shows the private URL, and stores the preference — without changing bind addresses, so the dashboard can never become unreachable from a setup run. Everything continues to work with or without Tailscale or fail2ban
- fix (earnings efficiency — removed misleading 'Latest'): the 'Latest MYST/GB' figure was the ratio of the most recent day alone, which swings wildly with the day's service mix — a near-empty Public-only day shows ~3 MYST/GB even though the real blended rate is ~0.11. It implied thousands of MYST from a TB of traffic. Removed; the volume-weighted Combined avg and the per-service rates remain as accurate measures
- feat (idle tunnel indicator — correct layer): tunnels in the live view that stay open for hours while moving almost nothing on average (lifetime throughput below ~1 KB/s, e.g. a monitoring probe holding a tunnel open with only keepalives) are now marked 'idle' with a grey dot, so a probe tunnel is no longer indistinguishable from a real consumer on the same interface pool. This replaces the earlier session-level attempt, which never fired because Mysterium resets the session timer every ~2 minutes while the tunnel persists — idle is now judged at the tunnel layer where the interface age and total bytes are known

## v1.2.44
- feat (idle tunnel indicator): active sessions that hold a WireGuard tunnel open but move almost no data (long-running with average throughput below ~1 KB/s) are now marked 'idle' in the connections list instead of showing an identical pulsing 'active' dot. WireGuard tunnels linger after real traffic stops and monitoring probes briefly hold a tunnel, so an idle probe tunnel that stayed open for hours no longer looks like a busy consumer — the dot turns grey and an 'idle' tag appears next to the duration
- cleanup (on-chain data source): removed the dead api.polygonscan.com fallback from the wallet-balance and token-transfer fetches. Since the Etherscan V2 migration that host only returns a 301 redirect. Etherscan V2 (chainid=137) is the sole source and accepts legacy Polygonscan API keys, so on-chain balance, settlement history and rewards are unaffected

## v1.2.43
- fix (Public mode toggle — B2B services): switching Public between Open and Verified deleted and recreated the wireguard service. On the standard multi-service node, wireguard, dvpn, scraping, data_transfer and monitoring share ONE WireGuard subnet, and that DELETE tore the subnet down — taking the B2B services with it until the next full node restart. The v1.2.32 fix only covered the Off path; the Open/Verified path still did the blunt DELETE. It now cycles wireguard through the active-services list (remove then re-add) so the new access policy applies while the shared subnet — and the B2B/dvpn/monitoring services on it — stay up. A direct service cycle is used only when wireguard is managed separately (not in active-services)
- fix (earnings efficiency — combined average): the 'Combined avg MYST/GB' was a plain mean of per-day ratios, which over-weighted low-volume high-rate days (a few MB of Public at ~3 MYST/GB counted as much as tens of GB of B2B at ~0.08 MYST/GB), inflating the figure well above the real earned rate. It is now volume-weighted (total earnings / total data across the window), so it reflects the true blended rate (e.g. ~0.12 instead of ~1.84 on a B2B-heavy node)

## v1.2.42
- fix (earnings efficiency chart): days with negligible data (a few hundred KB) divided a tiny earnings figure by a near-zero GB value, producing meaningless MYST/GB ratios that collapsed the per-service line into sharp V-drops. Each service's daily ratio is now clamped up to the 10th percentile of that service's own real days. No day is removed — low-earning nodes keep every data point — only genuine divide-by-near-zero noise is lifted into the real range
- fix (settlement history): the on-chain settlement list now shows only incoming transfers (actual settlements into the wallet). Outgoing transfers (e.g. moving MYST out to top up a service) are no longer listed or counted, keeping the settlement total accurate
- fix (network rewards): rewards are now matched to the known MystNodes monthly reward pool address instead of any incoming non-Hermes transfer. This prevents unrelated incoming MYST (e.g. a one-off transfer from a Mysterium admin wallet to help an operator get started) from being wrongly counted as a reward

## v1.2.41
- fix (earnings overflow): the lifetime/service-breakdown rollup summed raw token wei with SUM(tokens), which overflows SQLite's 64-bit integer limit once lifetime earnings pass ~9.2 MYST worth of summed wei (any real node). The query now uses SUM(CAST(tokens AS REAL)), matching the other earnings queries. Without this the rollup raised 'integer overflow' and fell back to a partial live computation, so lifetime and per-service earnings could read low or incomplete

## v1.2.40
- fix (no setup needed): the read-only 'wg show' sudoers permission for exact handshake-based tunnel counts is now added by update.sh, not just setup.sh. update.sh already rewrites the sudoers file on every run, so existing users get exact tunnel counts automatically on a normal update — without ever re-running setup. This corrects v1.2.35, which wrongly required a setup re-run
- ui (tunnels): the fallback hint no longer says 'run setup'; it now points to the only remaining cause (the wireguard-tools package not being installed), since the sudoers permission applies automatically on update

## v1.2.39
- feat (settle feedback): the Settle button now reports the actual outcome instead of always showing 'queued'. The node can return HTTP 200 while Hermes refuses the settlement (the reason is in the body), so the response is now inspected. The most common case — Hermes 'Limit exceeded' after recent settlements — is shown as a clear notice (earnings are safe, the node settles automatically once the rate-limit window clears, no need to retry). 'Nothing to settle' and 'insufficient fee' are surfaced too; unknown endpoint variants still fall through to the async settle path
- ui (settle): the result now shows below the button with a readable hint instead of being squeezed into the button label, and errors stay visible long enough to read

## v1.2.38
- fix (settle detection): the dashboard now reflects a settlement (auto OR manual) within ~1 minute instead of lagging up to the 10-minute slow-tier interval. The medium tier (60s) reads the node's own unsettled earnings and, when it drops by more than 0.5 MYST (unsettled only ever falls on a settle, otherwise it climbs with accrual), forces an immediate earnings refresh. Replaces the previous heuristic that estimated unsettled from live session tokens — an unreliable signal that rarely fired

## v1.2.37
- security (firewall): setup no longer opens the Mysterium Node UI port (4449/tcp) to the network. It exposed the node's own control UI with no toolkit protection in front of it. The Node UI stays reachable on localhost and LAN; node onboarding now documents the secure SSH-tunnel method (ssh -L 4449:127.0.0.1:4449) so it works without exposing the port and without Tailscale
- fix (firewall/docs): corrected the documented P2P UDP range to 10000-60000, matching the node's udp.ports default (10000:60000) confirmed in Mysterium core config — the README previously said 65000
- docs (ports): the Ports-opened table now reflects what setup actually opens (5000/tcp + 10000-60000/udp on local installs only; remote/fleet opens 5000 only). Clarified that 4050/tcp (TequilAPI) is localhost-only and never firewalled open, and that 4449/tcp is intentionally left closed

## v1.2.36
- fix (node quality in Verified mode): the Discovery query now includes access_policy=all. Without it, Discovery only returns proposals under the default public policy, so when Public ran in Verified mode the wireguard proposal (moved to the 'mysterium' policy) was omitted and quality wrongly showed 0 score / 0% uptime / 0 Mbit/s. With access_policy=all the node's proposals and quality are read correctly in every mode — verified live against the Discovery API (1 proposal without the flag vs 6 with it)
- fix (false warning removed): dropped the inaccurate 'Verified mode blocks Mysterium monitoring agents' notice. Verified does not block monitoring — the 0% readings were caused solely by the missing query parameter above, not by Mysterium

## v1.2.35
- fix (tunnel count): tunnels are now counted from WireGuard handshake recency via `sudo wg show` — an interface counts as a live tunnel when its peer handshaked in the last ~3 minutes. Mysterium creates one interface per consumer, so this reflects genuinely connected consumers (including connected-but-idle ones) and tracks clients coming and going, instead of byte-based heuristics that under- or over-counted. Falls back to the previous traffic-based estimate (marked "estimated" in the UI) when wg/sudo is unavailable
- feat (setup): setup adds read-only `wg show` to the toolkit sudoers (both /usr/bin and /usr/sbin paths) so the handshake-based count works on hardened installs. Existing users get exact counts after re-running setup; until then the estimated fallback is used
- docs: corrected the live-connections note (wg show IS used now) and updated Help/README for handshake-based tunnel counts

## v1.2.34
- fix (export via fleet): the CSV/TXT session export now works when viewing a node through the fleet master. The fleet proxy lacked export/sessions in its allowlist and force-parsed every response as JSON (which mangled file downloads); it now allowlists the endpoint and forwards non-JSON responses raw, preserving Content-Type and the download filename
- fix (export errors): the Download button now surfaces a visible error instead of failing silently
- fix (tunnel count): the Tunnels count no longer includes idle-but-connected interfaces kept alive only by WireGuard keepalives. A tunnel counts as active only with real traffic (>2 KB/interval) in the last 5 minutes, so the number reflects tunnels actually serving consumers instead of the full interface pool

## v1.2.33
- fix (Public/monitoring, second path): the generic service stop now stops Public (wireguard) via the active-services rewrite instead of a blunt DELETE — closing the same monitoring-killing footgun that v1.2.32 fixed for the Open/Verified/Off toggle. Falls back to a direct stop only when wireguard is managed separately. The UI already routes Public through the mode selector, so this hardens the API path against direct or future callers
- cleanup: removed an unreachable dead return in the stop-service route

## v1.2.32
- fix (Public/monitoring): turning Public Off no longer deletes the wireguard service (which tore down the shared WireGuard subnet and killed monitoring + other services on it). On nodes that manage wireguard via active-services, Off now removes only wireguard from the list and lets the node reconcile gracefully — monitoring keeps running. Falls back to a direct stop only when wireguard is managed separately. Open/Verified re-adds wireguard to active-services so Public persists across restarts
- fix (tunnels): the Tunnels & Sessions count now reads recent-active tunnels (traffic in the last 5 minutes) instead of the cumulative since-boot interface count, so it no longer shows idle pool interfaces (e.g. '6 tunnels / 1 session')
- feat (export): new CSV/TXT export of the session archive — choose last 30/90 days or all history, optionally filtered to a single consumer wallet. Generated read-only from the frozen archive so settled earnings are accurate. Available from the History tab
- docs: updated in-app Help and README for the new Off behavior and the export feature

## v1.2.31
- fix (G1): lifetime totals (earnings, data, sessions, service breakdown) now come from a permanent daily rollup (`earnings_rollup.db`) that survives session pruning — pruning old sessions can no longer shrink lifetime figures; a full data reset clears the rollup too
- fix (A): Consumers tab, top earners, paying-consumer count and probe detection now use frozen archive tokens instead of live (settlement-zeroed) tokens, so settled real payers are no longer counted as 0-earning
- fix (H1): the unsettled balance refreshes within ~2 minutes after a node-side auto-settle instead of lagging up to the 10-minute slow-tier poll
- fix (F1): "Tunnels" now counts WireGuard interfaces active in the last 5 minutes (recent activity) instead of any interface that ever carried traffic, aligning it with the live consumer count
- fix (E1): the earnings chart now also drops corrupt snapshots with an absurd forward jump (>50 MYST between consecutive snapshots), matching the write-side guard
- fix (D1): hardened settle-amount parsing to reliably distinguish wei from MYST, preventing inflated amounts on tiny settlements
- fix (D2): wallet balance keeps its last good cached value on Polygonscan rate-limit instead of blanking (removed dead branch)
- fix (D3): replaced deprecated `datetime.utcfromtimestamp` with a timezone-aware call
- docs: updated in-app Help/FAQ and README for the rollup, retention defaults, recent-active tunnels, frozen consumer stats and prompt settle refresh

## v1.2.30
- fix: manual settle no longer reports an error when `/transactor/settle/sync` takes long — a read-timeout is now treated as "settling on-chain" (success/pending) instead of HTTP 504, matching the official Mysterium SDK which disables the timeout on this slow on-chain call
- fix: settle busts the balance/earnings cache after success (was dead code placed after `return`) so the dashboard refreshes promptly
- fix: settle builds the TequilAPI URL per node inside the retry loop, adds `/transactor/settle/async` fallback, and distinguishes connect-timeout (node down) from read-timeout (node busy)
- feat: History tab search bar — find all sessions by consumer wallet (`0x…`) or session ID, searched server-side across the entire archive (`/sessions/archive?search=`)
- feat: session IDs are now click-to-copy with the same popup as consumer IDs, in both live and archive history rows
- fix: removed dead duplicate `fail2ban_reload` function (orphaned definition that had no route)

## v1.2.29
- fix: database migration in `update.sh` now correctly migrates existing data from `config/` to `backend/databases/` — previous check skipped migration when empty placeholder files existed in `backend/databases/` (affects all users who updated to v1.2.28)
- fix: `data_manager.py` — `uptime_log.json` and `node_identity.txt` now correctly read from `config/` instead of `backend/databases/`; SQLite databases correctly use `backend/databases/`
- fix: README database paths corrected from `config/` to `backend/databases/`
- fix: README firewall table removed incorrect ports 1194 (OpenVPN) and 51820 (WireGuard) — Mysterium does not use these ports

## v1.2.28
- fix: all SQLite databases moved from `config/` to `backend/databases/` (correct location) [file:38]
- fix: `update.sh` auto-migrates existing `config/*.db` to `backend/databases/` on first run — no data loss [file:38]

## v1.2.27
- fix: `setup.sh` now downloads Node.js 18 binary directly when apt fails (Debian Buster/EOL systems) [file:38]
- fix: `setup.sh` detects and repairs broken npm (`TypeError: Class extends value`) [file:38]
- fix: Node.js minimum raised to v18 — Vite requires `crypto.getRandomValues` [file:38]
- fix: sqlite3 Buster fallback via `snapshot.debian.org` [file:38]
- fix: npm install log no longer uses `/tmp` — uses toolkit `logs/` directory [file:38]
- fix: `logs/` and `config/` chown after sudo install — prevents permission errors [file:38]
- fix: `nodes.json` template creation default changed to `N` — prevents ghost nodes in fleet UI [file:38]
- fix: backend skips template nodes with `REPLACE_WITH_NODE_IP` — never shown in fleet [file:38]
- fix: delete node immediately updates fleet UI state without waiting for metrics refresh [file:38]

## v1.2.26
- feat: setup wizard new entry question — node location instead of Easy/Custom [file:38]
- feat: fleet wizard added — guides Type 2 (fleet master) and Type 3 (lightweight backend) setup [file:38]
- feat: Easy mode now asks for Polygonscan API key [file:38]
- feat: Easy mode auto-detects Raspberry Pi — sets log level to WARNING automatically [file:38]
- feat: Easy mode wallet address explanation improved [file:38]
- feat: post-setup port reachability guide added to wizard [file:38]
- docs: README Step 8 wizard section fully rewritten to match new wizard flow [file:38]
- docs: Help section — log level and debug mode explanation added [file:38]

## v1.2.25
- fix: TequilAPI port corrected to 4050 throughout setup_wizard.py, app.py, README and Dashboard.jsx [file:38]
- fix: removed non-existent ports 14449/14050 from port scan [file:38]
- fix: nodes.json examples updated to use port 4050 (TequilAPI) instead of 4449 (Node UI) [file:38]
- fix: port scan now tries 4050 first (bare metal), then 4449 (Docker) [file:38]

## v1.2.24
- fix: Help section autostart option numbers corrected (8 for Type1/2, 6 for Type3) [file:38]
- fix: setup.sh Step 13 key tips corrected — option 8 autostart, option 9 security [file:38]
- docs: Help section now explains security can be added after install via option 9 [file:38]
- docs: README new section `Adding Security After Install` [file:38]

## v1.2.23
- fix: fail2ban start/stop use `fail2ban-client` instead of `systemctl` — fixes permission error on non-root installs [file:38]

## v1.2.22
- fix: SecurityPage settings routes (fail2ban managed toggle, install) use local backend URL instead of fleet proxy — fixes 403 FORBIDDEN in fleet context [file:38]

## v1.2.21
- fix: fail2ban managed toggle no longer resets every 5s — settings fetch split from firewallData useEffect [file:38]

## v1.2.20
- docs: removed outdated sudo ./update.sh warning from README [file:38]
- docs: README menu tables updated with Security & Upgrades option [file:38]
- docs: README firewall table corrected (port 4050, not 4449) [file:38]
- docs: README new Security section — fail2ban, Tailscale, custom jails [file:38]
- docs: README permissions table updated with fail2ban entries [file:38]
- docs: Help section in dashboard — Security tab, Tailscale, Pi mode, CLI option 9 explained [file:38]

## v1.2.19
- fix: auto-update wrapper now uses `sudo -n` on non-root systems (fixes Parrot OS and other security-hardened distros) [file:38]
- fix: removed Add custom jail UI — toolkit only manages mysterium-dashboard jail; info hint added pointing to manual jail.local editing [file:38]
- fix: Tailscale card now shows actionable message when installed but not connected [file:38]
- feat: Tailscale card shows optional UFW commands to hide dashboard from internet when connected [file:38]

## v1.2.18
- fix: `_f2b_all_jails()` is_toolkit computed inside inner loop — prevents wrong toolkit label on external jails (sshd, nginx-botsearch etc.) [file:38]
- fix: fail2ban_get_jails now only returns toolkit-managed jails — external jails never shown in dashboard [file:38]
- fix: fail2ban managed toggle now renders correctly regardless of jail load state [file:38]
- fix: removed mention of specific tool names from fail2ban managed toggle description [file:38]

## v1.2.17
- fix: setup.sh Python check now detects pyenv shims under sudo (Raspberry Pi Buster + other EOL systems) [file:38]
- fix: fail2ban only creates `mysterium-dashboard` jail — SSH and other jails managed by other tools are never touched [file:38]
- fix: update.sh sudoers rewritten in multi-line heredoc format (fixes Parrot OS and other security-hardened distros) [file:38]
- feat: Tailscale detection in firewall data (installed/running/IP/peers) [file:38]
- feat: Tailscale status card in Security tab with install guide [file:38]
- feat: fail2ban managed toggle in Security tab (disable to prevent toolkit from writing jail.local) [file:38]
- feat: Security & Upgrades menu in CLI (option 9) — install fail2ban, Tailscale wizard, reconfigure sudoers [file:38]

## v1.2.16
- fix: auto-update service exit code 1 when up-to-date (add exit 0 to wrapper script) [file:38]
- fix: fleet Add Node input fields uneditable due to nested component definition causing remount on every render [file:38]

## v1.2.15
- Added Pi mode toggle for Raspberry Pi SD card protection [file:38]
- Added firewalld rule display for Fedora/RHEL/CentOS/Rocky Linux [file:38]

## v1.2.14
- Fixed probe detection incorrectly relaxed in v1.2.9 and restored original probe logic [file:38]

## v1.2.13
- Fixed port 4449 vs 4050 in PortReachability health check [file:38]
- Removed deprecated delete endpoints [file:38]
- Corrected incorrect success message after data delete [file:38]

## v1.2.12
- Fixed manual and timer-based updates requiring password on Parrot OS and other `use_pty` distros [file:38]

## v1.2.11
- Fixed auto-update timer not triggering on existing installs [file:38]
- Reverted globe icon behavior for wireguard sessions [file:38]

## v1.2.10
- Fixed globe icon missing in History and Consumers detail views [file:38]

## v1.2.9
- Fixed probe detection falsely flagging wireguard Public consumers as network probes [file:38]
- UI: wireguard consumers shown as globe icon instead of dash [file:38]
- Code comment corrected for noop service description [file:38]

## v1.2.8
- Fixed sudoers missing ufw, iptables-nft, cpufreq scaling governor, and cpupower on non-root installs [file:38]

## v1.2.7
- Fixed sudoers missing `/usr/bin/systemctl` paths on security-hardened distros [file:38]
- Added missing `systemctl reset-failed mysterium-toolkit` NOPASSWD [file:38]
- Added missing `systemctl restart mysterium-*` in `update.sh` [file:38]

## v1.2.6
- Fixed broken auto-update timer wrapper script [file:38]
- Fixed wrapper never repaired on existing installs [file:38]
- Fixed `is_local_request()` trusting entire RFC1918 on VPS installs [file:38]

## v1.2.5
- Fixed Docker compatibility in README and setup wizard [file:38]
- Added Docker-aware service watchdog and live data fallbacks [file:38]
- Added Docker-specific restart hint and host note in system health [file:38]

## v1.2.4
- Fixed fail2ban jail edits not applying live [file:38]
- Changed auto-update timer from daily to hourly and version-check based [file:38]

## v1.2.3
- Fixed missing NOPASSWD commands for sudoers update flow [file:38]

## v1.2.2
- Fixed fail2ban config handling to use `/etc/fail2ban/jail.local` [file:38]
- Preserved user customizations outside toolkit-managed jail block [file:38]
- Updated sudoers paths to match jail.local usage [file:38]

## v1.2.1
- Fixed fail2ban jail edit fields disappearing after save [file:38]
- Fixed fail2ban health scan sudo fallback issues [file:38]
- Added auto-update re-exec when update content changes [file:38]
- Added auto-create of update timer when missing [file:38]

## v1.2.0
- Fixed fail2ban access for non-root installs [file:38]
- Added fail2ban firewall-type detection and broader distro support [file:38]
- Raised default bantime for sshd and dashboard jails [file:38]
- Improved Raspberry Pi install handling and Node.js version checks [file:38]

## v1.1.66
- Fixed multiple dashboard crashes from undefined values [file:38]
- Fixed Security routing and fail2ban/UFW form issues [file:38]

## v1.1.65
- Fixed fail2ban exception cascade [file:38]
- Fixed earnings chart undefined values [file:38]
- Added fail2ban-client and config paths to NOPASSWD [file:38]

## v1.1.64
- Rewrote fail2ban jails to use fail2ban-client as primary source [file:38]
- Added UFW edit support and restored firewall refresh [file:38]

## v1.1.63
- Added firewallData prop and corrected iptables field names [file:38]
- Added sudo fallback for fail2ban on non-root installs [file:38]
- Added `/firewall` to fleet proxy whitelist [file:38]

## v1.1.62
- Fixed SecurityPage open crash and iptables column names [file:38]
- Fixed fail2ban ping behavior on non-root installs [file:38]

## v1.1.61
- Added `/firewall` whitelist support for fleet nodes [file:38]
- Loaded UFW rules from firewallData [file:38]
- Allowed editing all jails and saved external jails as overrides [file:38]

## v1.1.60
- Complete Security page rewrite for fail2ban and UFW management [file:38]
- Added `/firewall/fail2ban/start`, `/stop`, and `/reload` endpoints [file:38]
- Added running-state-aware jail loading [file:38]

## v1.1.59
- Fixed blank dashboard crash caused by orphaned module-level lines [file:38]

## v1.1.58
- Added all new security endpoints to fleet proxy whitelist [file:38]
- Fixed dashboard crash caused by React default export issues [file:38]

## v1.1.57
- Removed duplicate components that caused dashboard crashes [file:38]
- Added security endpoints to fleet proxy whitelist [file:38]

## v1.1.56
- Firewall card fail2ban now shows only status and counts [file:38]
- Manage link now points to Security page [file:38]

## v1.1.55
- Added install fail2ban button in Security page [file:38]
- Added active bans and unban buttons [file:38]
- Added backend fail2ban install endpoint [file:38]
- Removed old Fail2banManager modal [file:38]

## v1.1.54
- Removed incorrect toolkit.conf restriction text [file:38]

## v1.1.53
- Replaced dynamic Tailwind classes with static conditionals [file:38]

## v1.1.52
- Added Security button in bottom nav bar [file:38]
- Added full fail2ban and UFW management to Security page [file:38]

## v1.1.51
- Collapsed firewall card sections by default [file:38]
- Added manage panel behavior for fail2ban [file:38]

## v1.1.50
- Added fail2ban manager modal [file:38]
- Changed UFW rules to be collapsed by default [file:38]

## v1.1.49
- Added fail2ban status in firewall card [file:38]
- Added `/firewall/fail2ban/unban` endpoint [file:38]
- Added optional fail2ban install step in setup scripts [file:38]

## v1.1.48
- Fixed consumer ID copy scrolling issue [file:38]
- Moved network probes to top of consumer list [file:38]

## v1.1.47
- Fixed consumer ID copy focus scrolling issue [file:38]

## v1.1.46
- Fixed update.sh being killed by the service cgroup during update [file:38]

## v1.1.45
- Fixed consumer ID copy helper reference errors [file:38]

## v1.1.44
- Added SIGTERM handler so systemd does not restart during updates [file:38]
- Fixed backend restart/update race conditions [file:38]

## v1.1.43
- Fixed consumer ID copy remount issues from inline component definitions [file:38]

## v1.1.42
- Fixed update restart race condition [file:38]

## v1.1.41
- Replaced `grep -oP` with portable `awk` for PID extraction [file:38]

## v1.1.40
- Restored consumer ID popup copy behavior [file:38]
- Fixed `toFixed()` crashes on undefined values [file:38]

## v1.1.39
- Restored full consumer ID display [file:38]

## v1.1.38
- Fixed build-to-temp update flow [file:38]
- Removed `pkill -f` self-matching issue [file:38]
- Added verified mode warning [file:38]

## v1.1.37
- Removed `ExecStartPre pkill` self-kill issue [file:38]

## v1.1.36
- Fixed `ExecStartPre` heredoc command substitution issue [file:38]

## v1.1.35
- Added fallback for writing wireguard config on non-root installs [file:38]
- Added config files to NOPASSWD [file:38]

## v1.1.34
- Added `ExecStartPre` to ensure port 5000 is free before start [file:38]

## v1.1.33
- Killed process on port 5000 by PID [file:38]

## v1.1.32
- Waited for port 5000 to become free before starting [file:38]

## v1.1.31
- Killed leftover process on port 5000 after stop [file:38]

## v1.1.30
- Added Network Rewards section to Settle History [file:38]
- Added rewards transaction data to settle history response [file:38]

## v1.1.29
- Restart flow now uses systemd stop+start [file:38]
- Added `systemctl reset-failed` before start [file:38]
- Moved `StartLimitIntervalSec` and `StartLimitBurst` to `[Unit]` [file:38]
- Switched service file write to `$SUDO tee` [file:38]

## v1.1.28
- Fixed wireguard mode read/write handling [file:38]
- Fixed `toFixed()` on undefined session earnings [file:38]
- Changed license to AGPL-3.0 [file:38]

## v1.1.27
- Added update-in-progress screen [file:38]

## v1.1.26
- Moved system update logs out of `/tmp` [file:38]
- Auto-cleaned stale `/tmp` logs [file:38]
- Updated update status to read only `logs/update.log` [file:38]

## v1.1.25
- Replaced `systemctl restart` with `stop` + `start` [file:38]

## v1.1.24
- Skipped sudoers updates when unchanged [file:38]

## v1.1.23
- Added earnings efficiency breakdown by service type [file:38]
- Added configured node price legend [file:38]
- Merged `quic_scraping` into `scraping` [file:38]

## v1.1.22
- Fixed JSX syntax error in help section [file:38]

## v1.1.21
- Made `chown` commands conditional [file:38]

## v1.1.20
- Added CLI and help improvements [file:38]
- Added fleet Add Node URL auto-complete [file:38]
- Improved README and update documentation [file:38]

## v1.1.19
- Fixed root-owned `.git/objects` after sudo update [file:38]
- Added urgent notice for previous sudo update users [file:38]

## v1.1.18
- Removed outer sudo requirement from update.sh [file:38]
- Updated fleet update button to run full update flow [file:38]
- Fixed build file copy and node_modules handling [file:38]

## v1.1.17
- fix: `mystPrice` ReferenceError in fleet bar — undefined variable crash on load
- fix: `update.sh` no longer exits on frontend build failure — backend always restarts even when build fails

## v1.1.16
- feat: GitHub Actions CI workflow added
- docs: CHANGELOG added to repo

## v1.1.15
- Added net earned and fleet bar summaries [file:38]
- Added Ansible mass update section [file:38]
- Fixed unsettled display logic and Hermes channel row [file:38]

## v1.1.14
- Added fleet aggregate bars for MYST and fiat values [file:38]
- Fixed confusing unsettled fallback behavior [file:38]

## v1.1.13
- Added Docker support for fleet update [file:38]
- Documented fleet update manager and Docker stats [file:38]

## v1.1.12
- Fixed fleet update on non-root installs [file:38]

## v1.1.11
- Fixed orphaned visible text in Data Management panel [file:38]

## v1.1.10
- Fixed fleet update on non-root installs to use stop/start flow [file:38]

## v1.1.9
- Fixed firewall panel JSX bracket error [file:38]

## v1.1.8
- Fixed orphaned visible text in mobile view [file:38]
- Hid redundant fleet card label at 100% uptime [file:38]

## v1.1.7
- Fixed firewall panel JSX closing bracket error [file:38]

## v1.1.6
- Added inline firewall panel [file:38]
- Added legacy port detection and removal [file:38]
- Reduced version check cache time [file:38]

## v1.1.5
- Added Open/Verified/Off selector for public service [file:38]
- Fixed deprecated ports and port labels [file:38]

## v1.1.4
- Added tunnel counter tooltip and firewall help text [file:38]
- Fixed firewall cleanup chain handling [file:38]

## v1.1.3
- Reverted broken `get_sessions` behavior from v1.1.2 [file:38]
- Added isolated `/sessions/live` endpoint [file:38]

## v1.1.2
- Attempted realtime active session fetch, later reverted [file:38]

## v1.1.1
- Fixed update endpoint SSH key detection and HOME handling [file:38]
- Added update status endpoint [file:38]

## v1.1.0
- Added public service 3-mode selector [file:38]
- Added sessions pagination support [file:38]
- Added default TequilAPI credentials hint [file:38]
- Added config verification after active-services write [file:38]
- Added earnings sanity checks [file:38]
- Added docs for new features [file:38]

## v1.0.30
- Fixed chart colors to use inline hex [file:38]

## v1.0.29
- Added Fleet Update Manager [file:38]
- Added node offline warning [file:38]
- Added reliable analytics bar colors [file:38]

## v1.0.28
- Fixed systemd service `StartLimitIntervalSec` placement [file:38]
- Fixed myst service detection [file:38]

## v1.0.27
- Fixed wireguard active-services handling [file:38]
- Fixed monitoring/noop service toggle blocking [file:38]
- Fixed TequilAPI error logging [file:38]

## v1.0.26
- Fixed access_policies handling in start_service and metrics refresh [file:38]

## v1.0.25
- Changed default chart period from 90d to 30d [file:38]

## v1.0.24
- Changed transfer chart color to indigo [file:38]

## v1.0.23
- Merged quic_scraping into scraping [file:38]

## v1.0.22
- Fixed ghost deduplication and consumer counter [file:38]

## v1.0.21
- Fixed active-services config and TequilAPI port auto-correction [file:38]

## v1.0.20
- Fixed fleet routing and merged QUIC Scraping into B2B Data Scraping [file:38]

## v1.0.19
- feat: adaptive CLI start menu per install type (Type 1/2/3 tonen andere opties)
- feat: detect and separate Mysterium network probes in Consumers tab with probe indicator
- fix: missing `fmtType` in 5 mobile views
- fix: `duration_secs` added to live sessions for working Duration sort
- fix: reset archive offset on fleet node switch
- fix: deduplicate ghost reconnect sessions per consumer/service-type pair
- fix: `_run` input_data encoding bug
- fix: `cpu_governor` persist via tee + systemd service
- fix: replace `sudo bash` with `sudo tee` for all health fix file writes
- fix: expand sudoers with missing sysctl/modules-load.d/chmod paths
- fix: `fmtType` applied to ServiceSplitChart legend and SVG tooltips
- fix: sync `_DEFAULT_RETENTION` with actual setup defaults
- docs: README menu option numbers corrected per install type

## v1.0.18
- fix: phantom active sessions from stale WireGuard interfaces
- fix: History tab showing wrong node archive in fleet mode

## v1.0.17
- feat: context-aware health profiling (Laptop, VM/VPS, LXC, Raspberry Pi, Bare metal, Alpine)
- fix: quieter toast notifications

## v1.0.16
- fix: `TOOLKIT_DIR` path bug in root `setup.sh`
- fix: NodeSource Node.js 20 install updated
- fix: `fmtType` missing in mobile views
- fix: Network Quality card display
- docs: Ubuntu and Pi OS compatibility noted in README

## v1.0.15
- feat: uniform 7d/30d/90d/1y/All period selectors across all charts
- feat: data retention raised to 365 days default
- feat: new analytics charts (service split, earnings efficiency)
- fix: auto-detect OS timezone, persist to `setup.json`
- fix: earnings chart daily bucketing to local time
- fix: service-split and earnings-efficiency endpoints use raw tokens/bytes columns

## v1.0.14
- fix: service-split and earnings-efficiency endpoints: `SessionDB.init()` and local timezone bucketing

## v1.0.13
- fix: auto-detect OS timezone and persist to `setup.json`
- feat: fleet uptime/efficiency, MYST/GB per session, service split chart, earnings efficiency chart
- fix: dynamic retention-aware period selectors and All button for quality/system history
- fix: service stop stale UUID and scraping/quic_scraping functional link

## v1.0.12
- fix: sudo LXC/root compatibility
- fix: venv pre-install check
- fix: Node.js false positive version detection
- fix: README port references corrected

## v1.0.11
- fix: earnings UTC timezone handling
- fix: rate-limit snapshot
- fix: system health inline expand
- fix: logs position
- fix: `fetchArchive` fleet routing
- fix: QUIC label display

## v1.0.10
- feat: node update badge in dashboard
- feat: editable data retention per node
- feat: `data_retention` added to `setup.json`

## v1.0.9
- fix: fleet routing fix for quality/metrics history
- fix: quality/metrics history reload on node switch
- fix: duplicate data management card removed

## v1.0.7
- feat: extended system metrics (tunnels, speed, latency, temperatures)
- fix: update badge visible in fleet overview
- fix: metrics reading from correct cache tier
- fix: system metrics DB writing speed/latency/tunnels from wrong cache tier

## v1.0.4
- feat: update check badge
- feat: extended system metrics (tunnels, speed, latency, temperatures)
- fix: config ownership after sudo operations

## v1.0.3
- Fixed SessionDB migration issue with missing provider_id [file:38]

## v1.0.2
- Fixed chown on config after sudo operations [file:38]

## v1.0.1
- Initial post-launch bug fixes [file:38]

## v1.0.0
- Initial public release [file:38]
- Flask/React monitoring dashboard for Mysterium VPN node operators [file:38]
- Earnings tracking, session analytics, node quality monitoring [file:38]
- Fleet mode for multi-node monitoring [file:38]
- System health panel with adaptive CPU/conntrack tuning [file:38]
- 11 themes, autostart, remote node restart/settle/payment configuration [file:38]

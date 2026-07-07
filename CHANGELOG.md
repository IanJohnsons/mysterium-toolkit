# Changelog
All notable changes to Mysterium Node Toolkit are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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

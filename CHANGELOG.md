# Changelog — Ampere

Versioning: semantic from 1.0 onward. MAJOR changes public behavior or durable
data contracts, MINOR adds compatible capability, and PATCH repairs shipped
behavior. History before 0.6.0 is reconstructed from NOTES.md (the project
predates this repo by two very long days).

## Unreleased

No changes yet.

## [1.0.0] — 2026-08-23 — the archive opens

Ampere's first complete release turns the local library into one coherent,
album-led room while preserving MPD playback, user-owned files, and local-first
operation.

### Release highlights

- Rebuilt the product around the Iann-selected Archive Wash visual system,
  Archive Header navigation, art-first Library rooms, Cover Theatre Home,
  Gallery Monolith Now Playing, Stillpoint Ambient, Pocket Horizon compact
  playback, and the 720×480 responsive floor.
- Replaced the legacy search page with Record Wall: asynchronous,
  generation-safe querying; exact best-match activation; Unicode-script and
  romanized discovery; truthful empty/loading/failure states; keyboard travel;
  and recent-search history.
- Made artist identity user-owned and reversible. Durable aliases now resolve
  discography, album attribution, artist rows, biographies, and portraits
  without rewriting tags; featured credits retain truthful primary and guest
  membership.
- Unified generated listening around verified library snapshots. Standard and
  Smart shuffle filter dislikes, collapse alternate versions, preserve the
  chosen queue boundary, spread artists, and keep verified gapless joins;
  Smart sessions continue from their seed as the queue runs down.
- Parked the unfinished DJ studio and retired the old Saved Sound Profiles UI
  from navigation. Their implementation history remains below; durable profile
  data is preserved while its future purpose and interaction stay deliberately
  undesigned.
- Moved expensive library, artwork, search, analysis, queue, persistence, and
  service work behind owned workers and immutable snapshots so pointer and
  keyboard feedback stay on the rendered frame. The 50,000-song contract now
  pins index and lookup behavior against the definitions they replaced.
- Closed the release gate with keyboard and assistive routes, trusted artwork
  and external-provider boundaries, 1,102 Python tests, 152 Qt 6 QML tests,
  wheel installation checks, and AppStream/desktop metadata validation.

### Complete development ledger

- Built the Iann-selected Search direction B · Record Wall (SPEC rows "Search
  hierarchy" + "Search results", DECISIONS 2026-08-20): a 420px best-match
  sleeve with Play/Queue/Open actions, query headline with truthful counts,
  an albums-and-artists sleeve row, and a song ledger that expands to the
  full list inside the room (Return or "ALL N →"); the legacy
  `SearchResultsView` page is retired. Every matching file is its own row
  (duplicates carry album + format), activating a song queues only that
  song, closing Search keeps the query and results, the field gains a
  bounded recent-searches plane persisted in settings, song rows open the
  shared track menu on right-click (`TrackActionMenu`, now also used by
  `TrackRow`), and the catalog owns best-match tiers (exact → prefix →
  substring → "CLOSEST MATCH"). Search requests carry a serial + catalog
  generation, worker failures surface as "Search failed — try again",
  loading dims stale content, Esc is staged, arrow keys walk the results,
  and lyric matches ride along once the lyric index is built.

- Built the Iann-selected NP.01 Gallery Monolith Now Playing direction at
  normal desktop widths: the full centered sleeve and low instrument deck move
  left as one composition when Lyrics opens, revealing the continuous ledger
  without duplicate panels, decorative grey rules, or current-line emphasis.
  Existing medium/compact Playback B remains intact pending its own design.
- Built the first pass of the ratified design system (awaiting Iann's
  verdict): Archive Wash room, R1 Centered Whisper rail, and the L.01 Open
  Shelves Library directory with six destinations, remembered per-surface
  sorts, and pure in-memory read models (`LibraryDirectory`); songs now carry
  an `added` timestamp for recency sorts; `/api/nav` learned
  `library`/`features`; search moved to an overlay pending its own surface.
- REVERTED same day: a whole-shell visual pass (grouped sidebar, hero+ledger
  home, player-deck restyle) was built against the rejected "Signal Room"
  morning sketches instead of the locked 2026-07-30 design session, and was
  restored to the prior state at Iann's direction. Kept from that pass, per
  the standing drawn-icon law only: Now Playing's drawn HeartIcon replacing
  the unicode hearts, and EQ's drawn plus icon. Design governance added:
  `design/SPEC.md` (single design authority, LOCKED/REJECTED/UNDESIGNED),
  `design/DECISIONS.md` (verdict ledger), `design/REVIEW.html` (visual review
  board), the complete design-session mockups under `design/mockups/`, and
  the Design Authority Law atop `AGENTS.md`.
- Moved Sound Profile create/edit/delete durability onto one owned worker with
  immutable publication, truthful SAVE & PLAY completion, and thread-safe
  narrow settings patches that cannot revert newer unrelated preferences.
- Stacked compact Smart-shelf identity and actions into a deliberate reading
  order, adopted tokenized display sizes and gutters, and reused the designed
  empty state without changing shelf or playback behavior.
- Made Search responsive with compact tokenized headings, collision-safe long
  artist identities, and drawn, keyboard-accessible artist destinations.
- Reflowed compact Discover shelves into a readable two-line ledger and gave
  session, shelf, and artist destinations drawn icons plus complete keyboard,
  focus, and accessibility press semantics.
- Reworked compact album pages into a vertical record summary and full-width
  track list; the shared Library header now preserves identity, actions, and
  all destination tabs without narrow-width clipping.
- Made Queue a responsive session workspace: a restrained side plane at normal
  widths and full-workspace composition when compact; added an accessible close
  action and replaced its remaining stock glyphs with Ampere's drawn icons.
- Aligned Now Playing and the player bar at a shared 900 px compact breakpoint;
  medium windows now use a single-column hero with readable artwork, metadata,
  waveform, and transport hierarchy.
- Restored the adaptive album-room's visual hierarchy on the Library hub with
  a contextual destination plane and a readable right-side artwork scrim;
  navigation remains legible over bright covers without changing the register.
- Moved DJ set-history writes and retention cleanup onto a serialized owned
  worker that coalesces transition bursts and drains the final snapshot during
  shutdown; durable failure feedback remains deduplicated and truthful.
- Moved Replay Last Set catalog scanning, JSON parsing, and absolute-file
  filtering onto a duplicate-safe worker; stale queue generations reject
  before the saved set can replace live playback.
- Moved phone-remote discovery, listener start, and Settings stop onto one
  latest-intent lifecycle worker; pairing URL reads are now cache-only while
  shutdown retains the final synchronous service drain.
- Moved normalization preamp config write, MPD restart, and exact-document
  rollback onto a duplicate-safe lifecycle worker; verified success now retires
  stale MPD transport and reacquires runtime state through owned workers.
- Moved heartbeat correction, per-song fade retuning, and DJ transition
  configuration onto the shared prioritized transition worker; internal
  requests coalesce and DJ ownership publishes only after verified commit.
- Moved Settings-originated crossfade, MixRamp threshold, enable, and style
  transactions onto one latest-intent owned-client worker; complete desired
  snapshots prevent rapid controls from publishing/configuring mixed states.
- Moved ReplayGain mode read/write/verify/rollback onto a generation-aware
  owned-client worker; latest Settings intent wins, reconnect enforcement
  coalesces, and loudness scans wait for verified mode commit.
- Moved Settings' Update Library preflight, at-most-once update dispatch, and
  lost-reply reconciliation onto a duplicate-safe owned-client worker; deletion
  now performs the same update inside its existing reconciliation worker.
- Extracted Queue Save validation into a pure snapshot planner and removed
  Backend's last long-lived synchronous `PlaylistService` I/O adapter; durable
  persistence remains on the staged worker.
- Removed the last dead synchronous Liked/Disliked refresh helpers and their
  unused long-lived taste adapter; active collection acquisition remains
  atomic and worker-owned.
- Removed the unreachable star-rating Qt property/slot and its redundant
  decoded per-song cache after confirming the star UI and all production
  callers are gone; raw ratings continue to guide shelves and planning.
- Moved Library Doctor's exclusive Preferred Version sticker transaction onto
  a duplicate-safe lifecycle-owned worker; Qt publishes only verified commit
  or rollback-aware failure outcomes.
- Moved automatic play-count/last-played stickers, append-only history,
  long-track resume writes/deletes, and resume lookup onto one serialized
  lifecycle-owned worker; stale results cannot seek a different or advanced
  song.
- Moved DJ set/journey construction, optional sting preparation, anthem
  selection, and whole-library cue/energy/BPM/listening-evidence scans onto one
  duplicate-safe owned-client worker; stale queue/settings plans cannot commit.
- Moved permanent-deletion Disliked rebuilding and verification into the
  existing owned queue-reconciliation worker, eliminating the final reviewed
  Qt-thread MPD read while preserving staged recovery and truthful outcomes.
- Moved Like/Dislike collection reads, staged replacement, mutual-exclusion
  rollback, and verification onto one duplicate-safe worker-owned MPD client;
  Qt publishes taste state and skips only after durable success.
- Removed unreachable Qt playlist rename/delete/reorder/remove facades and
  their synchronous catalog/writer callbacks while retaining tested domain
  policies and every active playlist journey.
- Moved Queue Save onto the owned staged playlist transaction; validation is
  immediate, while success/failure feedback waits for durable worker results.
- Moved Sound Profile export, Rewind recap, and Mixtape playlist persistence
  onto one duplicate-safe worker transaction with fresh catalog authority,
  staged replacement recovery, and truthful asynchronous completion.
- Removed the final synchronous queue-refresh facade; explicit refreshes and
  DJ cache-resync now use the coalesced owned queue/status worker exclusively.
- Moved post-library-deletion queue verification onto a worker-owned MPD
  client; deletion stays busy until authoritative queue evidence is published,
  and unavailable evidence preserves the prior verified presentation.
- Moved rendered DJ bridge frontier validation, insertion, range writes, and
  rollback onto a worker-owned MPD client while holding the shared queue lease
  through Qt-side publication and asynchronous presentation reconciliation.
- Added one non-blocking structural queue-mutation coordinator shared by
  Playback and DJ operations, preventing bridge/reset/user-edit interleaving
  while keeping contention retryable and the UI unblocked.
- Removed DJ stale-range recovery's Qt-thread status read; startup cleanup now
  waits for paired playhead evidence from the owned queue/status worker.
- Moved TrackEditor tag reads, verified FLAC writes/backups, and narrow MPD
  refreshes onto lifecycle-owned workers; duplicate saves are rejected and
  failed saves preserve the open draft.
- Moved every PipeWire stream discovery and volume write used by smooth manual,
  remote, and DJ moves onto lifecycle-owned workers while retaining serialized
  fades and stranded-zero recovery.
- Moved scoped art/waveform cache deletion onto a duplicate-safe owned worker;
  completion and partial failure remain truthful through the existing toast.
- Removed the dead synchronous library-path helper and added an AST-enforced
  allowlist for the few Qt-thread MPD reads that remain mutation-critical.
- Moved Cut Now's initial current-song/elapsed verification onto the existing
  owned delayed-status worker while retaining its second pre-cut drift gate.
- Moved DJ reset playhead verification onto a generation-aware owned worker;
  only current conclusive evidence can trigger the existing bridge/range
  cleanup and auto-mix handback.
- Routed the remaining `refreshStatus()` compatibility callers—including DJ
  ticks and transition/session changes—through the coalesced owned heartbeat
  worker and removed heartbeat acquisition's GUI-client fallback.
- Moved stored-playlist Play, Queue, Shuffle, and Shuffle Now membership reads
  onto a latest-wins owned worker, preserving distinct empty/disliked outcomes
  and the existing transactional session boundaries.
- Moved remote folder, album, explicit-file, and stored-playlist Play planning
  onto a latest-wins owned worker while preserving Ampere's disliked, shuffle,
  start-position, and transactional playback laws.
- Moved Browse/Artist/Album Play, Queue, and Shuffle path membership reads onto
  a latest-wins owned worker; only current verified lists reach the existing
  transactional queue/session boundaries.
- Refined Settings into a responsive Signal Room: wider normal composition,
  three-up compact summary, bounded section planes, keyboard-operable 44 px
  section navigation, and explicit horizontal-overflow protection.
- Carried the startup queue-recovery playhead through the existing owned queue
  worker, removing its follow-up Qt-thread `status` read while retaining fresh
  explicit reconciliation for queue mutations.
- Moved timer-driven trim and DJ transport verification onto lifecycle-owned
  scoped status workers; fresh song/time/generation checks still fail closed
  before Qt-thread next or seek mutations.
- Moved Library and Settings totals into the existing owned library-summary
  publication, so both pages paint last-verified counts immediately and never
  issue MPD `stats` reads on Qt's thread.
- Moved startup, idle, queue-followup, and elapsed heartbeat reads onto one
  coalesced owned worker; a Backend clock now runs only during playback, while
  explicit transport/volume commits invalidate stale worker generations.
- Moved startup/idle full-queue reads and normalization onto a coalesced owned
  worker while preserving synchronous mutation/DJ reconciliation, stale-result
  invalidation, and the restored explicit `refreshQueue()` facade.
- Moved startup/idle collection catalog, Liked, and Disliked reads into one
  atomic owned-worker publication; mutation reconciliation invalidates stale
  generations so committed taste/playlist state cannot be overwritten.
- Moved stored-playlist presentation reads onto generation-aware owned workers;
  selection paints retained rows immediately, verified results replace them,
  and failures or stale responses cannot blank/overwrite the current view.
- Moved Sound Profile playlist export into the curated owned-worker lifecycle;
  verified plans return to the GUI thread for a truthful playlist-only commit,
  while failures publish no false name/count and never touch playback.
- Moved Mood Radio and Sound Profile launch planning behind one duplicate-safe
  owned worker/client lifecycle; only current verified plans reach the existing
  transactional queue boundary, and Ampy now reports explicit async outcomes.
- Removed synchronous whole-family listening-evidence reads from Smart Shuffle,
  More Like This, stopped Radio, and last-played seed selection by extending the
  Library worker's atomic cached planning generation; unavailable generations
  now abort before recommendation or queue/session mutation.
- Removed whole-family play-count and preferred-version reads from house
  shuffle: version collapsing now consumes the Library worker's atomic cached
  planning generation, fails closed before queue mutation on cold start, and
  advances preference state only after a committed edit.
- Removed scalar energy/BPM sticker reads from fade-mode song transitions by
  atomically publishing bounded transition evidence through the Library worker;
  unknown data retains neutral/base timing and malformed generations are kept.
- Removed the scalar rating-sticker read from every song transition: the
  Library worker now atomically publishes validated ratings, successful edits
  advance the cache, and failed writes retain the prior current-song value.
- Moved Library Doctor's play-count/preference evidence, version analysis, and
  physical scan behind one owned worker client; launch/evidence/scan failures
  retain the prior verified report and always release busy state.
- Moved Mixtape evidence acquisition and arc planning onto one lifecycle-owned
  worker with explicit busy/result publication; transactional playlist commit
  still precedes playback, and failed build/save paths cannot alter the queue.
- Removed synchronous sticker I/O from Now Playing's personal story, advanced
  cached count consumers directly from verified play-record writes, and retired
  unused playlist-cover/top-artist Qt slots with latent blocking reads.
- Made Artist discography ranking storage-I/O-free by publishing the verified
  Library worker's immutable play-count generation to both Artist and Search;
  malformed or failed generations retain every prior presentation consumer.
- Made Browse presentation storage-I/O-free: Library, Home, DJ rooms, and
  folder pages now consume an immutable hierarchy derived and atomically
  published with the verified library index; queue mutations retain fresh MPD
  authority.
- Removed whole-library play-count sticker reads from interactive Search:
  artist ranking now consumes an immutable snapshot published atomically by
  the owned Library worker, so every query/keystroke is storage-I/O-free.
- Moved Rewind Sonic DNA's play-count, energy, BPM, and cue/key reads onto one
  owned, coalesced worker; the tab now paints from a retained verified profile
  with an explicit first-load measuring state.
- Moved Rewind's default statistics, timeline, and chapters into the atomic
  Library worker publication, so opening Listening or Chapters paints from the
  last verified overview instead of scanning play-count stickers on Qt's thread.
- Made Ampy Rediscovery consume the verified cached Deep Cuts/Loved union with
  explicit warming and valid-empty states, and retired the obsolete synchronous
  shelf facade. Page ownership now hides outgoing surfaces immediately so an
  interrupted transition cannot leave two readable/focusable views overlaid.
- Made rediscovery shelf navigation consume the complete ordered track rows
  already produced by the Library summary worker, eliminating duplicate
  GUI-thread sticker scans while keeping Play and Shuffle tied to shown rows.
- Moved Library and Discover shelf summaries and top-artist aggregation onto
  one owned, coalesced worker with a scoped MPD client; both pages now consume
  the last verified digest instead of blocking Qt on whole-library scans.
- Removed synchronous MPD traversal and media-file reads from Album and Artist
  presentation: both views now use the last verified in-memory library snapshot,
  while queue and playback mutations retain fresh daemon authority.
- Moved fresh-install MPD socket probing and stopped-only daemon activation out
  of Backend construction and into the owned worker registry, preserving the
  paused/play safety gate without blocking startup.
- Removed the final song-change media open from the GUI thread: fade mode now
  applies a safe immediate duration and accepts MixRamp/ReplayGain refinement
  only from the current generation of the existing metadata worker.
- Bound token-free phone-remote loopback trust to localhost/literal-loopback
  Host headers, preventing same-origin DNS rebinding from reaching playback
  mutation callbacks without the bearer token.
- Restricted every successfully replaced Ampere state/configuration file to
  its owner's permission bits, migrating legacy world-readable settings so
  local accounts cannot read the phone-remote bearer token.
- Made Queue playlist saves truthful and retryable: the save form now clears
  only after the backend reports a committed transaction, preserving the
  entered playlist name and limit after storage failure.
- Made DJ audition failures observable: cue/seam render failures and audio
  launch failures now report a retryable outcome, while stopped or superseded
  preview workers remain silent and cannot orphan playback processes.
- Made settings-save failure feedback recovery-aware: ordinary unsaved
  preferences retain their temporary-state warning, while rolled-back Sound
  Profile mutations say that prior state was kept; distinct failure kinds no
  longer suppress each other during one storage outage.
- Made random-off atomic with every ordered queue journey: the boundary now
  captures MPD's authoritative prior value, gates queue work, and restores that
  value after failed whole-queue, curated, upcoming, or reshuffle mutations.
- Made curated-session teardown transactional with whole-queue and upcoming
  replacement: failed MPD mutations now preserve the prior Mood/Sound Profile
  refill policy, and curated-to-curated starts avoid intermediate manual state.
- Gated Ampy's Sound Profile success copy on the verified, potentially delayed
  queue replacement result; planned counts now show only “Starting…” and can
  no longer masquerade as a committed curated session.
- Made Sound Profile create/edit/delete persistence transactional with exact
  in-memory rollback; failed saves no longer publish identities, discard the
  active curated session, close the editor, or claim that tracks were queued.
- Required authoritative play-count, energy, BPM, and preferred-version
  generations before Mixtape planning or persistence; a first-ever evidence
  outage now aborts without creating or starting an uninformed playlist.
- Made Rewind recap saves keyboard/assistive-technology operable and truthful:
  the page now names the playlist that actually committed or shows an explicit
  failure, rather than assigning an invisible fallback success string.
- Made application teardown observable without sacrificing best-effort
  cleanup: every service stage still runs once, failures carry stage labels,
  and a rejected MPD stop can no longer disappear as a silent successful exit.
- Made Settings cache maintenance scoped and truthful: only Ampere's art and
  waveform directories are removed, missing caches remain a valid success,
  and partial filesystem failures no longer produce a false “cleared” claim.
- Made stopped-player Radio activation transactional: plain-session planning
  preserves prior state, verified random-off gates queue start, and Radio state
  commits only after successful queue replacement.
- Gated Smart Mix success on a valid no-op plan or confirmed stable-ID reorder;
  rejected/malformed publication preserves the frontier and enters deduplicated
  backoff instead of clearing failure state in an unconditional `finally`.
- Required verified or retained generations for every taste, energy, BPM, and
  Sound Profile sticker family consumed by session planning; no-baseline
  outages now abort before selection, reordering, or queue publication.
- Made gapless-tail planning evidence authoritative across shuffle, discovery,
  Radio, Mood, and Sound Profile sessions; no-baseline outages now abort before
  random-mode or queue mutation, while verified empty/retained data may proceed.
- Gated Radio refill success on a confirmed at-most-once queue append; failed
  or empty publication now preserves the queue and enters deduplicated backoff
  instead of clearing failure state and retrying every heartbeat.
- Made Mood Radio exemplar reads authoritative: missing optional playlists stay
  valid empty inputs, while unavailable or malformed evidence aborts initial
  launch/refill before scoring or queue mutation.
- Restricted fresh-install MPD socket activation restarts to authoritative
  stopped state; paused, playing, unavailable, or malformed status now stages
  configuration without disrupting the live daemon session.
- Made DJ reset and stale-range cleanup require authoritative playhead identity;
  unavailable status now defers with zero queue/range mutation, while verified
  playing bridges retain the successor range needed for seamless handoff.
- Made library totals authoritative and retained: unavailable or malformed MPD
  stats no longer collapse the archive and Settings counts to zero, while a
  verified empty library remains distinct and warning publication re-arms.
- Made DJ cue, energy, and gapless-tail evidence authoritative: unavailable
  sticker reads defer planning without caching a false miss or mutating the
  transition, while verified missing evidence retains safe fallbacks.
- Removed the unused raw repeat-only Qt slot; active UI and MPRIS loop journeys
  continue through the verified coupled repeat/single boundary.
- Routed fade and DJ transition overrides through the verified coupled
  MixRamp-delay/crossfade boundary; failed commits retain prior published
  ownership and remain retryable instead of accepting partial daemon state.
- Made MixRamp threshold changes readback-verified and rollback-capable, and
  require the verified −30 dB safety threshold before first enabling Auto-mix.
- Made silent-tail trim, timed DJ cuts, and Wild re-drop identity-safe by
  capturing stable song IDs and requiring fresh same-song position truth at
  timer fire; stale callbacks now abort without seeking or skipping.
- Made manual DJ Cut Now identity-safe: arming and delayed firing require
  fresh status for the same playing song, and seek drift or unavailable truth
  aborts without a skip or queue change.
- Required complete, structurally valid queue and playback-status truth before
  rendered DJ bridge insertion; transient validation failures now defer
  without mutating ranges or permanently blacklisting the transition.
- Made New Arrivals an authoritative retained snapshot: unavailable or
  malformed MPD searches preserve the last verified rediscovery shelf, while
  a valid empty result remains distinct and re-arms failure reporting.
- Made whole-family listening-data reads authoritative across UI and worker
  clients, retaining verified recommendation/history inputs through outages;
  unavailable play-count reads can no longer overwrite durable counts with a
  fallback value after reconnect.
- Routed app, MPRIS, and hosted-phone play/pause/toggle/stop through a verified
  playback-state controller that derives intent from fresh MPD status,
  dispatches once, and reconciles ambiguous replies before publication.
- Made every current-track seek at-most-once across UI, MPRIS, long-track
  resume, and DJ re-drop, preventing an ambiguous lost reply from replaying an
  old position onto the next song after a transition.
- Made volume changes readback-verified and rollback-capable across app, phone,
  MPRIS, and output switching; per-device memory now persists only levels MPD
  actually committed.
- Replaced retrying global Clear Queue with a verified stable-ID snapshot
  transaction that recovers partial/lost replies while preserving songs added
  concurrently after the user's action.
- Made MPD database refresh at-most-once and status-reconciled across metadata
  edits, library deletion cleanup, and Settings, preventing lost replies from
  launching duplicate scans and distinguishing running/unconfirmed outcomes.
- Made folder and browse reads authoritative: unavailable or malformed MPD
  path snapshots preserve the last verified presentation, block queue-changing
  journeys, and warn once instead of masquerading as empty library content.
- Routed stored-playlist rename and deletion through an at-most-once mutation
  boundary with refreshed-catalog reconciliation, preventing lost replies from
  replaying non-idempotent commands or reporting false success.
- Made stored-playlist reads authoritative: unavailable or malformed snapshots
  preserve the last verified track display, block play/shuffle/edit journeys,
  and warn once instead of masquerading as a valid empty collection.
- Made Like, Dislike, and rating persistence observable: failed MPD writes no
  longer disappear as silent no-ops, incomplete mutual-exclusion recovery is
  distinguished, and warnings deduplicate until a verified recovery.
- Reflowed the archive landing room below 900 pixels so its wordmark,
  two-column destination index, library totals, and Now Transmitting actions
  remain distinct instead of overlapping over the album art.
- Made Queue's primary actions, track activation, removal, filtering, and save
  flow keyboard-reachable with accessible names, 44-pixel targets, and visible
  focus states; its header now reflows locally at compact widths.
- Added a verified, rollback-capable MPD random-mode boundary and require every
  ordered app/phone queue journey to prove daemon random is off before
  publishing a curated, shuffled, or artist-spread sequence.
- Replaced opaque whole-queue reshuffling with an upcoming-only stable-ID
  transaction that preserves the playhead, reconciles lost replies, applies
  artist spacing, and refuses to scramble active rendered DJ transitions.
- Made ordinary and refillable-session shuffle spread actual indexed artists
  across album folders, with constraint-aware scheduling that avoids adjacent
  repeats whenever possible while retaining intentional gapless successors.
- Made Replay Last Set recover newest-to-oldest through structurally valid,
  currently playable history, so a damaged or departed latest set no longer
  masks older sessions and no queue mutation begins before selection succeeds.
- Made DJ persistence truthful: explicit cue shifts now save before claiming
  durable success, while set-history write failures warn once and retention
  cleanup cannot invalidate an already durable session record.
- Moved DJ votes, cue bans, strikes, and seam learning behind a recovery-safe
  repository: malformed state is exactly backed up, unreadable state blocks
  writes, future fields survive, and save failures are visibly deduplicated.
- Made Auto Genre recovery non-destructive and forward-compatible: malformed
  global toggle state is exactly backed up before replacement, unreadable state
  blocks writes, and unknown fields survive toggle changes.
- Added non-destructive, forward-compatible EQ profile recovery: malformed
  profiles are exactly backed up, unreadable profiles block writes, and unknown
  document/variant fields survive older-version validation.
- Made settings recovery non-destructive: malformed documents receive an exact
  digest-named backup before replacement, while read failures block default
  writes so shutdown cannot overwrite state Ampere never verified.
- Strengthened the shared atomic writer to fsync every newly created directory
  edge and the final rename directory, so saved state survives power loss as
  well as process crashes.
- Made Artist responsive below 720 px with stacked actions, bounded shared-token
  typography, compact album rows, safe title elision, and keyboard-accessible
  album destinations with visible focus state.
- Made artist-biography misses retryable by caching only validated positive
  results; transient failures and legacy negative cache entries can now recover.
- Prevented Spotify imports from replacing local M3Us with empty documents
  when remote playlists are empty or unmatched, and made sync jobs exclusive
  with explicit invalid, busy, and shutdown-rejected outcomes.
- Invalidated per-song metadata and silent-tail state synchronously on track
  changes, isolated each background enrichment source, and rejected unsafe
  cutoff values so stale analysis cannot truncate the next song.
- Made Smart Mix and Radio background planning fail closed: analysis failures
  preserve the queue, busy state always releases, retries use a 30-second
  cooldown, and warnings stay deduplicated until a successful recovery.
- Made Library Doctor failure-safe: preflight errors, rejected worker launches,
  and scanner exceptions now release the busy state, restore the last verified
  report, and surface one retryable failure instead of scanning forever.
- Serialized FLAC tag read/modify/save transactions by canonical file path
  across manual metadata, ReplayGain, and MixRamp writers; scanners now reopen
  after analysis so concurrent enrichment cannot overwrite newer user tags.
- Verify FLAC metadata by reopening and comparing every editable field before
  success, retain the recovery snapshot on mismatch, and distinguish durable
  tags from a failed MPD library-rescan request in user feedback.
- Replaced position-relative phone queue jumps with stable MPD song IDs and
  at-most-once `playid`, so a stale rendered row cannot target another song
  after concurrent queue edits.
- Routed phone album/folder/playlist starts through Backend's authoritative
  session policy, adding Disliked filtering, house shuffle, soft replacement,
  and curated-session teardown while preserving the standalone fallback.
- Routed phone-remote volume through Ampere's queued Backend boundary, keeping
  MPD volume and per-output remembered levels consistent across app restarts;
  standalone remote use retains its direct-MPD fallback.
- Made Now Playing responsive below 760 px with a stacked art/metadata hero and
  width-constrained detail lines, eliminating the compact layout's substantial
  right-edge overflow while preserving the normal two-column composition.
- Made normalization activation rollback-safe: paired preamp edits publish
  only after MPD restarts successfully, while failure restores the exact prior
  configuration and reactivates it or reports incomplete recovery explicitly.
- Made ReplayGain mode publication authoritative: MPD readback now gates UI
  state, persistence, remembered mode, and loudness analysis, while lost
  replies reconcile safely and rejected changes retain the prior mode.
- Made Auto-mix's MixRamp-delay and crossfade settings a verified daemon pair
  with rollback; enable/style/base preferences and analysis now publish only
  after MPD confirms the requested transition state.
- Made loop-mode changes a verified `(repeat, single)` transaction shared by
  the app and MPRIS, with prior-state rollback and a Radio gate that prevents
  partial MPD option changes from masquerading as an infinite session.
- Made preferred recording selection an exclusive, rollback-capable MPD
  sticker operation; partial failures no longer silently leave conflicting
  preferences, and incomplete recovery is surfaced for Library Doctor repair.
- Moved Sound Profile sticker selection and feature decoding into the profile
  service, so the Qt facade performs only MPD I/O and malformed or
  low-confidence measurements consistently remain unknown to ranking.
- Hardened the phone remote against browser cross-site request forgery:
  mutations require same-origin browser requests and JSON media types, while
  responses now deny framing and restrict content, connections, forms, and
  sensitive browser capabilities.
- Require a newly generated phone-remote token to be durably saved before any
  listener opens, retain failed tokens for safe retry, and publish actual start
  success instead of claiming the remote is enabled after a failed bind/save.
- Made EQ lifecycle failures degrade audio processing instead of aborting the
  player: setup/discovery/watcher boundaries are contained, startup warnings
  survive until QML attaches, and live tool failures are timeout-bounded,
  deduplicated, and recovery-aware.
- Unified EQ profile, variant, genre-routing, auto-genre, and tone writes behind
  an observable atomic persistence boundary; failures stay temporary, warnings
  are episode-deduplicated, and explicit Save remains dirty until durable.
- Made play-record persistence observable across MPD stickers and the JSONL
  history store: partial writes now return explicit outcomes and produce one
  actionable warning per failure episode, re-armed by a complete record.
- Made listening-history writes durable before success is reported, including
  syncing the first log's directory entry, and preserve the last verified
  Rewind snapshot when the history filesystem is transiently unavailable.
- Converted queue play, remove, trim, cap, and drag-reorder actions from
  shifting numeric mutations to stable-ID transactions with authoritative
  reconciliation, preventing stale UI positions from targeting another song.
- Made Smart Mix reordering a verified stable-ID transaction. Partial MPD
  command lists reconcile from fresh queue snapshots, concurrent queue drift
  aborts safely, and the curation frontier advances only after the requested
  order is proven live.
- Routed DJ skip, bridge, and stale-cleanup mutations through their correct MPD
  replay boundaries: relative actions are at-most-once, absolute range setters
  remain retry-safe, and incomplete startup cleanup stays pending for retry.
- Replaced position-relative stored-playlist and taste edits with verified
  whole-playlist staging swaps; rename/delete reconcile from the catalog,
  failed mutual-exclusion edits roll back, and restoring a current dislike no
  longer skips playback.
- Verified post-delete cleanup against fresh MPD state: queue entries are
  removed by stable song ID, Disliked and queue absence are independently
  proven, partial outcomes are reported truthfully, and cleanup exceptions can
  no longer strand the deletion busy state.
- Restored confirmed single-file and bulk deletion to the Disliked page, with
  explicit local/server consequences and a backend-owned busy state that blocks
  duplicate destructive submissions and recovers if shutdown rejects the worker.
- Made rendered DJ bridge insertion recoverable: a fresh queue snapshot now
  resolves ambiguous `addid` outcomes before song ranges are changed, while
  incomplete splices remove the bridge by stable ID and restore prior ranges.
- Split the phone remote's MPD access into retrying reads and at-most-once
  mutations, preventing ambiguous disconnects from double-toggling playback,
  duplicating appended tracks, or replaying queue replacement transactions.
- Prevented lost MPD replies from replaying non-idempotent playback and queue
  actions. Skip, previous, relative deletion/insertion, and queue movement now
  fail ambiguously at most once instead of risking a double skip or duplicate
  queue edit after reconnect.
- Settings writes now return explicit results and surface one actionable error
  per failure episode while preserving the last document for clean retries;
  successful persistence re-arms future failure reporting.
- Generated-playlist recovery now distinguishes unavailable catalogs, intact
  originals, completed installs with lost replies, and restore-needed swaps;
  backups/stages are handled conservatively without false-empty assumptions.
- Playback heartbeat refresh now validates paired status/current-song reads
  before any mutation, preventing transport failures from fabricating stops,
  departures, persistence actions, or downstream UI/enrichment work.
- Playlist catalog refresh now preserves the last verified collection on
  unavailable or malformed reads, distinguishes genuine emptiness, emits only
  for verified changes, and keeps Liked/Disliked refreshes independent.
- Queue refresh now distinguishes unavailable/malformed snapshots from a real
  empty queue, retaining the last verified local queue and suppressing DJ/UI
  follow-up until MPD successfully publishes fresh state.
- Library indexing now publishes an explicit success result. Failed or missing
  MPD snapshots preserve the last coherent generation and no longer emit false
  database-ready signals or launch enrichment against stale data.
- Saved Sound Profiles now share one schema for load, edit, presentation, and
  ranking; invalid traits and duplicate identities are normalized, snapshots
  are defensive, and active sessions end only after a real profile deletion.
- Lyric search indexing now snapshots catalog generations atomically, cancels
  stale work immediately, coalesces rebuild requests, and skips the previous
  empty pre-index startup scan.
- Media prefetch now isolates thumbnail/waveform failures, retries unchanged
  queue snapshots until successful, deduplicates in-flight work, and commits
  waveform JSON through the crash-safe atomic persistence boundary.
- Listening progress now has a stateful service boundary for play-count and
  long-track resume persistence, validated restoration, and backward-seek
  detection; the playback heartbeat retains only seek and DJ side effects.
- Playback heartbeat reconciliation now has explicit, tested ownership rules
  for fade mode, active DJ transitions, and daemon-controlled blend mode;
  normalized status snapshots also own queue-position change detection.
- Energy enrichment now has a framework-independent execution boundary with
  explicit outcomes, truthful cancellation, process-owned MPD leasing, and
  safe aborts when coverage inventory is unknown instead of accidentally
  scheduling a full-library re-analysis.
- MixRamp enrichment now has a framework-independent scanner with contained
  per-file failures, full outcome accounting, batched progress, and truthful
  cancellation instead of false completed-pass signals.
- ReplayGain enrichment now has a framework-independent scanner with bounded
  throttling, batched progress, and truthful cancellation counts instead of
  reporting interrupted library passes as complete.
- Phone-remote collection playback now resolves targets before mutation and
  uses the shared append-first, stable-ID queue transaction. Invalid staged
  files preserve the existing queue instead of failing after a destructive
  clear.
- Active MPD clients are now strongly retained by the process lifecycle until
  explicit close, preventing short-lived owners from disappearing before the
  final transport sweep. All client writers close before readers and sockets.
- Ampere-managed MPD configuration now has one safety boundary for atomic
  ReplayGain preamp updates and idempotent rendered-DJ socket installation,
  including value normalization and a one-time original-file backup.
- Phone-remote discovery and lifecycle now live in a focused service that owns
  bind planning, cached advertised addresses, pairing URLs, partial-start
  cleanup, and idempotent teardown; Backend retains the unchanged QML adapter.
- Queue sequencing now has one pure policy for shuffle ordering, artist
  separation, album-successor mapping, and bounded gapless-chain restoration.
  Refillable sessions share the same artist-spacing implementation while MPD
  transaction ownership remains unchanged.
- Settings now has a clearer album-room hierarchy: restrained signal summaries,
  correctly ordered section navigation, quiet indexed dividers, and a stable
  responsive header replace the previous stack of equally weighted boxes.
- MPD sticker reads now share a typed repository. Scalar resume/history/energy
  values and whole-library maps use consistent decoding; GUI-thread scans gain
  gateway reconnect behavior while worker scans keep thread-local clients.
- Stored-playlist behavior now has a focused service for CRUD validation, row
  normalization, disliked filtering, load plans, and queue-save results.
  Built-in `Liked` and `Disliked` stores are protected from save, rename, and
  delete paths while staged replacement continues to preserve existing data.
- The MPD idle listener now retires its writer while the socket is healthy,
  before `SHUT_RDWR` wakes its blocking read. This removes the evidenced path
  that could finalize a writable `TextIOWrapper` against a disabled socket;
  the instrumented runtime verification exited cleanly.
- Added opt-in shutdown attribution for the remaining intermittent socket
  finalizer warning. It captures tracked MPD transport state, live thread names,
  the failing wrapper chain, and allocation traceback without affecting normal
  runs.
- Likes, dislikes, and ratings now share a focused taste-state service while
  retaining MPD playlists and stickers as their stores. Failed refreshes keep
  the last durable snapshot, and failed rating writes no longer publish
  unsaved UI state.
- Every Ampere-created python-mpd2 client is now process-tracked. Shutdown
  closes the complete still-reachable inventory before stopping MPD, covering
  GUI, idle, remote, worker, and tool paths even when a local owner misses
  teardown. The remaining intermittent socket finalizer warning has since been
  reproduced outside that closed inventory and is no longer presumed MPD-owned.
- Library indexing, ReplayGain, energy, DJ-cue, and MixRamp work now shares a
  thread-safe enrichment coordinator for exclusivity, completion, shutdown
  rejection, and coalesced index rebuilds instead of five facade-owned flags.
- MPD teardown is now resilient to a broken writer flush. Reader, writer, and
  socket resources close independently and internal transport references are
  always reset, preventing python-mpd2's sequential `disconnect()` from
  stranding a partially closed transport. Process-wide tracking now provides
  the final ownership boundary for rarer missed-client cases.
- Backend background work now has one lifecycle owner. Shutdown rejects new
  tasks, cooperatively stops long scans, closes active MPD leases to unblock
  I/O, and joins all workers within one shared bounded timeout.
- Temporary MPD clients now share an exception-safe lease. Library indexing,
  startup probing, energy and DJ analysis, smart-mix mapping, and radio refill
  all close socket-backed file objects after successful work, command failure,
  or a partially failed connection.
- Shutdown now closes every socket owner while its peer is still alive. Phone
  request workers are joinable and time-bounded, whole-response disconnects are
  tolerated, the blocking MPD-idle listener is explicitly woken and reaped,
  and the GUI MPD gateway closes before the daemon stops. This removes those
  owners from the interpreter-finalizer path that emitted `BrokenPipeError`.
- Queue replacement is now append-first and ID-committed instead of
  clear-first. Every new entry is accepted and verified while the old queue
  remains authoritative; partial command lists and lost replies are reconciled
  through stable MPD song IDs. DJ sessions, saved-set replay, collection play,
  shuffle-after-current, and radio refill share the safer controller boundary.
- Startup and shutdown now share one idempotent application-lifecycle owner.
  MPRIS, the EQ watcher, backend services, and MPD are released in a defined
  order on normal exit, setup exceptions, and QML load failure; one adapter's
  cleanup error cannot strand the remaining resources.
- Settings now adapts locally at compact widths: the header becomes a stable
  two-row composition, labels and sliders shrink within the pane, secondary
  explanations yield before controls clip, and library actions stack. The
  phone-remote row no longer prints its credential-bearing URL and instead
  exposes a clear paired-open action. The pane also supports Page Up/Down,
  Home, and End keyboard scrolling.
- Phone-remote control now requires a persistent pairing credential on every
  non-loopback interface. The one-time pairing URL installs an HttpOnly,
  SameSite cookie and removes its query from browser history; header auth is
  available to API clients. Loopback remains trusted for local integration,
  missing credentials fail closed, and responses suppress referrer leakage.
- Resume, rating, play-count, energy, and BPM sticker reads now all pass through
  the reconnecting MPD gateway. Expected missing-sticker errors can be quiet,
  while stale sockets are invalidated and retried once instead of leaving
  several read paths on the raw client.
- Shared controls and dense list delegates now have explicit keyboard and
  accessibility contracts. Buttons, navigation, track rows, playlist choices,
  search results, and Rewind tabs expose roles/names and visible focus; Return
  and Space mirror pointer actions. Qt 6 delegate index/model declarations now
  prevent runtime scope errors across the principal data-heavy pages.
- Application shutdown now explicitly releases the phone remote, spectrum tap,
  deferred config timer, and PipeWire `pactl` watcher before Qt object teardown.
  Controlled exits no longer leak a QProcess or emit finalizer broken pipes.
- Permanent disliked-track deletion now runs through a dedicated safety service.
  Absolute/traversal paths and local symlink components are rejected; remote
  paths are shell-quoted and batched at 50 with isolated failure accounting;
  already-missing local files remain an idempotent success.
  Surviving Disliked entries are replaced through a staged name swap rather
  than a destructive clear/rebuild; an empty result uses one retried clear.
- FLAC metadata editing now uses a focused safety service with library-bound
  path resolution, traversal and symlink-escape rejection, an explicit field
  allowlist, one-time atomic original-tag snapshots, empty-tag removal, and
  narrow parent-folder rescans. Audio frames remain untouched by tag edits.
- Auto-mix fade duration now comes from a pure policy covering MixRamp curve
  interpolation, ReplayGain-corrected thresholds, pair-energy scaling, BPM bar
  alignment, malformed-tag fallback, and the established 2–10 second bounds.
- QML roots now tear down explicitly before their Python context objects. Clean
  exits no longer reevaluate every backend/EQ binding against null and flood
  logs with misleading errors, making genuine runtime warnings visible again.
- Play-count and long-track resume transitions now use a pure progress policy.
  Half-heard thresholds, meaningful resume windows, stale-resume deletion,
  monotonic elapsed tracking, and DJ backward-seek detection have direct tests;
  MPD sticker writes remain isolated behind the reconnect-safe adapter.
- Generated playlists now use an extracted failure-safe writer that stages all
  files before replacing a name, retains the old playlist until installation,
  restores a moved backup after a partial swap, removes orphan staging names,
  and invalidates dropped MPD connections before recovery.
- Artist biographies now use a focused cached enrichment service with atomic
  writes, corrupt-cache recovery, musical-context validation, exact-name search
  preference, and HTTPS Wikipedia host restrictions. Search-result track and
  lyric delegates now explicitly declare their repeater index, eliminating the
  per-row runtime errors discovered during rendered verification.
- Background audio-analysis coverage and sticker encoding now live in a pure
  policy. Existing energy/BPM results receive only missing tail or spectral
  backfills, new files receive full analysis once, duplicate work is removed,
  and the established precision and CPU cooldown limits have direct tests.
- MPD playback status now enters the UI through a typed normalization snapshot.
  Missing or malformed duration, position, bitrate, volume, crossfade, and
  MixRamp values fail independently instead of crashing an entire refresh;
  queue position zero is retained correctly as the first song.
- Smart Shuffle and More Like This selection, along with bounded auto-mix
  queue ordering, now live in a deterministic pure planner. Discovery scoring,
  malformed sticker handling, dislikes, limits, artist spacing, energy arcs,
  BPM continuity, and queue-window preservation are covered independently of
  Qt and MPD; the backend retains only snapshot collection and live mutation.
- Reworked Settings around the selected Listening Profile direction: live
  crossfade, auto-mix, and loudness status appears first; a section rail jumps
  to grouped playback, experience, and library controls; advanced controls stay
  progressive; and the summary adapts cleanly in compact windows.
- Rediscovery shelf policy now lives in a framework-independent service rather
  than the Qt backend. Arrivals, heavy rotation, loved-not-lately, deep cuts,
  throwbacks, history, filtering, ordering, and tile summaries operate on
  explicit snapshots with deterministic domain coverage.
- Rewind statistics, recent history, monthly/yearly chapters, recap selection,
  and sonic-profile aggregation now live in a pure analytics service. Recent
  rows once again expose the `ts` timestamp consumed by QML, fixing broken age
  labels and day filtering, and the Rewind header no longer overlaps its tabs.
- Alternate-version identity and selection now live in a pure policy module.
  Shuffle and mixtape generation consistently retain an explicit preference,
  otherwise the most-played sibling, while Library Doctor uses the same groups.
  Preference changes now use reconnect-safe MPD mutations instead of swallowed
  direct socket writes.
- The append-only listening log now has a dedicated repository that preserves
  the existing JSONL file in place, tolerates corrupt records, publishes entries
  and first-heard indexes as one immutable snapshot, and invalidates its cache
  for both internal and external appends using nanosecond mtime plus file size.
- Personal song stories and top-artist rankings now run in the Rewind analytics
  service over explicit history, sticker, and library snapshots. Future-dated
  corrupt log entries no longer distort rolling monthly ranks; Now Playing's
  first-heard, play-count, rank, and time-of-day contract remains unchanged.
- Album presentation and long-track chapter detection now live in pure domain
  helpers, with date tags and cached waveforms read through the media adapter.
  Chapter lookup never decodes audio on the UI thread. Album headers adapt so
  ordinary titles no longer truncate beside actions, and track delegates now
  declare their index contract instead of emitting runtime errors per row.
- Exact-length mixtape planning now lives in a deterministic service that owns
  eligibility, dislikes, alternate versions, neglected/liked appeal, bounded
  duration fitting, and whole-set energy sequencing. The missing Session
  Builder entry point is restored with keyboard-accessible 30/45/60/90-minute
  choices; plans outside the ±90-second promise now fail honestly instead of
  saving an inaccurately labeled mix.
- Extracted search orchestration from the central Qt backend into a tested,
  framework-independent catalog. Track matching, artist intent, album groups,
  and lyric snippets now read coherent library snapshots; a slow lyric scan
  cannot publish stale results after the music database changes.
- Settings now load and save through a validated repository with atomic writes,
  bounded numeric values, explicit choices, and forward-compatible unknown-key
  preservation. Fixed the rating-display preference silently reverting to
  hearts after restart because the legacy save path omitted `rating_mode`, and
  fixed an explicitly disabled crossfade returning as one second on restart.
- Library snapshots now have a dedicated repository that owns normalized track
  records, file lookup, search-index publication, browse presentation, artist
  paths, and discography grouping. The Qt backend remains a compatible facade
  while downstream sessions and shelves migrate onto the shared snapshot.
- Playlist, like/dislike, and rating-domain rules now live in a focused
  repository. MPD remains the durable store, while normalized collection
  snapshots, built-in-name protection, disliked filtering, and half-star
  conversion no longer belong to the Qt facade.
- Per-song file enrichment now runs through a dedicated service that reads
  codec details, source rate/depth, ReplayGain, lyrics, and silent-tail timing
  as one result. Request generations prevent an old A→B→A worker from
  overwriting the newer instance of the same track.
- Waveform caching and album-color extraction now use that same media service
  with independent request generations, closing the equivalent stale A→B→A
  race for visual enrichment workers.
- MPD connection state, health checks, reconnects, single-command retries, and
  command-error reporting now live in `MpdGateway`. Multi-command queue and
  playlist transactions remain explicit because their retry safety depends on
  the complete operation, not an individual command.
- Queue replacement and append transactions now live in `PlaybackController`.
  Complete queue replacement retries from `clear` because it is idempotent;
  append remains at-most-once so a lost response cannot duplicate tracks.
- Refillable listening-session state now belongs to `SessionService`. Mood and
  sound-profile sessions are mutually exclusive by construction, always enable
  radio refill after successful queue replacement, and are cleared together
  when plain listening takes ownership.
- Plain radio and mood recommendation ranking are now pure `SessionService`
  operations over explicit library, history, rating, energy, and queue
  snapshots. The backend only gathers MPD data and applies gapless album riders.
- Sound-profile ranking joined the session service as explicit trait-band
  scoring over supplied analysis maps; unknown analysis remains permissive
  while known out-of-band tracks are excluded.
- Album art can no longer borrow a neighboring album's cover. A track without
  embedded art used to fall back to the first art-bearing file in its folder —
  in flat artist folders (and in `Incoming/` full of syncthing conflict copies)
  that served the wrong album's picture (Birds In The Trap rendered with
  Rodeo's cover). The fallback now looks for a sibling with the SAME album tag,
  then a cover-named file; honest no-art beats a wrong cover. Directory scans
  skip `.sync-conflict-` files. Art cache keys now include the source file's
  mtime, so retagged files and late-arriving art invalidate stale thumbs
  (including the permanent "no art" negative markers).
- Ampere now serves its own MPRIS presence (`org.mpris.MediaPlayer2.ampere`),
  replacing the external `mpd-mpris` daemon. That daemon re-applied playback
  position to MPD on every position change; at a song change it wrote MPD's
  reported position — which runs ahead of the speakers during a crossfade —
  onto the incoming track, so every transition seeked a few seconds in and
  flushed the output buffer. `mpd-mpris.service` is masked.
- Stopped the volume ride from stranding MPD's output stream at zero when the
  stream can't be resolved on the way back up, and added a guard that raises a
  stranded stream. A ride interrupted by a kill used to leave playback silent,
  and WirePlumber persisted the zero into the next session.
- Unified manual and DJ timed cuts behind one PipeWire stream-transition
  controller. DJ cuts no longer use MPD's buffered volume path, and rapid
  moves are serialized instead of falling through to hard cuts.
- Made whole-set planning key-aware and quality-ranked before its bounded
  search. Global style feedback is now a preference nudge rather than a veto
  that can suppress unrelated transitions.
- Reorganized navigation around Library, Make a mix, Explore, and Playback;
  strengthened typography, spacing, selection states, and search prominence.
- Added an `ampere` executable, Linux desktop/AppStream metadata, complete
  wheel inclusion for QML assets and shaders, and stranger-oriented install
  instructions. The legacy `joi` command remains as a compatibility alias.

## [0.23.0] — 2026-07-24 — the DJ learns to serve the song

- **Whole-set planning.** DJ sequencing now uses a bounded beam search over
  complete musical futures instead of greedily optimizing only the next pair.
  It can reorder aggressively while preserving tempo continuity, artist
  spacing and the chosen energy arc.
- **Song-sensitive transition intent.** Before rendering anything, the DJ
  classifies the hand-off as a blend, slam or soft reset. Slams serve energy
  lifts and sustained peaks; cooling or emotionally delicate songs are given
  room. The live deck explains the musical reason for its next decision.
- **Punchy, not indiscriminate.** The old test-oriented Slam Only control is
  now Punchy. It favors verified energy-preserving slams and avoids long
  blends, without overriding emotional protection or the verifier safety gate.
- **Discovery that actually discovers.** Smart continuation, library radio
  and mood sessions now favor unheard, rarely played and long-absent tracks,
  while compatibility, likes and ratings supply a familiar spine. High play
  counts no longer cause recommendation feedback loops.
- **Smarter mixtapes.** Exact-duration playlists select neglected music and
  optimize their complete tempo/energy arc with artist spacing instead of
  merely sorting tracks by energy.
- Added pure, deterministic behavioral coverage for emotional protection,
  energy-aware slams, neglected-track ranking and whole-set sequencing.

## [0.22.0] — 2026-07-24 — the session-first product overhaul

Ampere's job is now explicit: be an exceptionally fast, organized local Linux
music player first, then make the owned library more fun to inhabit than it is
in a generic player. This release rebuilds the shell around that hierarchy.

- **A real product map.** A persistent navigation rail exposes Library,
  folders, playlists, Current session, Session builder, DJ, Now Playing,
  rediscovery, history, sound and settings. The previous home-card/header-icon
  maze is gone; browser-style back/forward remains.
- **Calm where work happens, vivid where music happens.** Organizational views
  now use a stable near-neutral shell with the album palette as an accent.
  Now Playing and Ambient retain the full adaptive room. This removes the
  visual fatigue of repainting every utility surface with every song.
- **Current session is a workspace, not a permanent side-pane.** The queue is
  now a contextual drawer with session type, remaining tracks/time, filtering,
  jump-to-playing, trim-played, keep-next-50, save and clear. It no longer
  squeezes every page, and a 3,500-song queue remains linear-time to summarize
  (the first implementation exposed and fixed a quadratic QVariantList copy).
- **Session Builder.** “Follow this song,” Rediscover, mood sessions and saved
  sonic recipes live together as intentions. The old Ampy's Corner identity is
  retained as the warm curator mark, but the destination and its outcomes are
  now self-explanatory.
- **Playlists became editable collections.** Inspect tracks, play, shuffle,
  append, rename, reorder, remove tracks and delete with confirmation. The
  exact-length Mixtape builder and local Spotify matching remain integrated.
- **A real rediscovery home.** New arrivals, heavy rotation, loved-not-lately,
  throwbacks, deep cuts, history, top artists and the Session Builder are now
  one coherent “For you” destination instead of a hidden set of unrelated
  shelves.
- **Immersive Now Playing.** The live 28-band tap drives layered currents and
  drifting sparks behind the art and waveform—an organic field rather than an
  equalizer-bar wall. It is lazy-loaded, stops off-page, respects the existing
  motion preference and shares the tap safely with Ambient mode.
- **Safe FLAC metadata editing.** Folder track menus can edit title, artist,
  album, album artist, genre, date and track number. Ampere validates that the
  file is inside the library, writes a one-time recovery snapshot under
  `~/.local/state/ampere/tag-backups`, then asks MPD for a narrow rescan.
- **Accessibility and quality.** Primary navigation, playlist selection and
  rediscovery cards are keyboard reachable with accessible names. Added real
  regression coverage for session trimming/capping and playlist mutations.

## [0.21.3] — 2026-07-24 — rejected DJ slams stay rejected

- **DJ slam verification is now a safety gate.** Ampere previously measured
  every rendered slam correctly, but if all three candidates failed it still
  spliced the loudest failure. That is why the decision log could say
  `ok=False ['off-beat ...']` immediately before `SPLICED`. A rejected cut
  now falls back to the normal soft-crossfade path; it never reaches the live
  queue.
- **Analysis failures fail closed.** Exceptions, incomplete verdicts,
  non-finite measurements, clipping, soft drops, and offsets beyond 35 ms are
  all rejected even if a malformed result claims `ok=True`.
- Added focused regression tests for clean, off-beat, soft, clipped,
  inconsistent, incomplete, and non-finite verdicts.

## [0.21.2] — 2026-07-23 — soft skips actually soft: fade the PipeWire stream, not MPD

- **0.21.1 made skips WORSE, measured:** the `setvol` ride acts where
  MPD's software mixer scales samples — entering the output buffer,
  several hundred ms ahead of the DAC. The skip then FLUSHES that
  buffer: the down-ramp was discarded unheard (still a hard cut, click
  edge 0.298) and the up-ramp muted the start of the next song. Capture
  showed 760–850 ms dropouts per faded skip vs 115 ms for a raw
  `mpc next`.
- **Fix:** `_soft_move` now rides MPD's PipeWire STREAM volume
  (`pactl set-sink-input-volume` on the "Music Player Daemon"
  sink-input, resolved fresh per skip) — stream volume applies at mix
  time, so the fade is audible immediately. Down 55/20/0 % ×25 ms →
  move → up 45/75/100 % ×50 ms, settling at exactly the starting
  stream volume; MPD's own volume/ReplayGain untouched. Stream not
  found → raw action (a 115 ms hard cut beats a broken ride); any
  failure re-resolves and restores.
- **Verified by capture:** seam now 60–70 ms audible fade-down →
  ~125 ms silence (MPD's own switch time) → soft ramp in; click edges
  0.005–0.022 (was 0.298). Longer quiet seams in testing were the next
  song's own quiet intro.

## [0.21.1] — 2026-07-23 — soft skips: the "stutter when the colors change" fix

- **Root cause, instrumented:** every USER-initiated switch (next/prev,
  clicking a track, playing a folder/playlist, shuffle-now) stopped MPD
  mid-waveform — ~200 ms of digital silence with click edges, audible as
  a stutter on every manual transition. Natural song ends crossfade and
  were always clean; the color change that follows a transition made the
  theme look guilty. Proven by dual monitor-tap captures (esper_eq +
  device) cross-correlated against the source FLACs: every hard gap
  lined up with a user action, none with a natural transition.
- **`_soft_move` volume ride:** user switches now ride the volume down
  (~90 ms), make the move, ride back up — settling at EXACTLY the
  starting volume (leveling is ReplayGain's job; compensating here would
  double-apply it). Nested/rapid skips fall through at the ridden-down
  volume; any failure restores the volume; DJ mode and paused/stopped
  states bypass untouched. Wrapped: next, previous, playPosition,
  playPath, playFiles (all callers inherit), loadPlaylist(replace).
- **Media keys + phone ride the same fade:** `/api/next` & `/api/prev`
  now route through a `move_cb` → `moveRequested` signal → the faded
  slots (raw-MPD fallback kept); `media-control` prefers the API over
  `mpc next` when the app is up. Keyboard skips were bypassing the app
  entirely and still hard-cutting.
- Not this bug but fixed en route: PipeWire RT-priority acquisition
  hardened system-side (onstart guard + 30 s timer) — a real, separate
  dropout mechanism that masqueraded as the same symptom during the
  guard's blind spell of 07-22.

## [0.21.0] — 2026-07-22 — listening-audit batch: one Auto-mix panel + DJ un-bricking + dead-weight cuts

Everything here came out of the 2026-07-22 listening audit (usage data +
Iann's notes), approved as a batch.

- **One Auto-mix panel (audit #9 Stage 2+3, finally shipped).** The
  standalone "Smart mix shape" Settings row is gone; smart mix now
  presents as Auto-mix's **Ordering** row — OFF / SMOOTH / WAVE ARC —
  right under the Auto-mix toggle, matching the four-layer ownership
  contract (select / order / join / perform). All bare "smart mix"
  language stripped from the player bar (tooltip now "auto-mix
  ordering", menu items RESHUFFLE/SAVE **MIXTAPE**). Backend untouched:
  ordering and joining stay independently toggleable, same conf keys.
- **DJ style-penalty decay + slam-only bypass (the self-brick fix).**
  The vote engine's style penalties never decayed and cue/pair bans
  were permanent — with `dj_slam_only` on and "slam" downvoted past the
  cap (his file: slam 7, mix 6 = both pinned at max), every prep
  skipped and a whole set silently degraded to soft crossfades
  ("you keep downvoting slams…" in dj.log was the tell). Now: (a) one
  downvote is forgiven per week since a style's last downvote
  (`style_down_ts`, seeded from the vote file's mtime for old data);
  (b) an upvoted hand-off takes one downvote OFF its style, so votes
  balance; (c) while slam-only is on, the style penalty never vetoes a
  slam — he asked for slams, skipping is the one wrong answer.
- **Cuts (never-used weight, per the play data):** ★ star ratings gone
  from Now Playing + Settings (3 ratings ever vs 3.6k tracks; hearts +
  dislikes are the real signals — backend sticker code kept,
  StarRating.qml deleted); **Genre EQ** row gone from the EQ view
  (shipped 07-13, zero assignments ever; eq.py plumbing dormant);
  **Radio mood** row (MATCH/ANY/CALM/HEAVY) gone — Mood Radio's six
  emotions are the one mood system now (backend key persists, radio
  behavior unchanged); **Trim silence** toggle folded into auto-mix
  (behavior unchanged, always on per config default).

## [0.20.0] — 2026-07-20 — Ampy's corner + Sound Profiles (+ Mood Radio)

- **Ampy** (Library → QUICK START → AMPY'S CORNER): the face of Ampere's
  recommendations — a drawn curator mark (Icon.qml "ampy": round head,
  bright eyes, the A-sine smile) fronting a new page (mode "ampy") that
  is the umbrella home for every "the app picks for you" tool. Ampy has a
  voice in the copy: greets by time of day, narrates what it built
  ("Pulled 25 bass heaven cuts for you — rolling now."), and the UI never
  says AI/assistant/chatbot — warm music-buddy register only (the JOI
  synthetic-companion identity stays dead). Future rec-tools nest here as
  new sections; Mood Radio deliberately stays its own Quick Start tile
  this round. Character depth is name + mark + voice — an animated
  mascot rig is flagged as a future session if ever wanted.
- **Sound Profiles** (the first tool in Ampy's corner): HIS named,
  persistent profiles of sonic traits — BASS / BRIGHTNESS / ENERGY /
  TEMPO / VOCALS, each ANY or a band chip in a small builder. A profile
  is a one-tap tile: tap = build a ~25-track on-profile queue (Mood Radio
  architecture: ranked picks + artist spread + gapless riders + radio
  refill session that any other play action ends); right-click = SAVE AS
  PLAYLIST (frozen as M3U "Sound · NAME"), EDIT, REMOVE. Selection only,
  by design — it never touches the EQ.
- **New per-track traits joi_bass / joi_bright** (energy.py `_spectral`):
  sub-share <90 Hz and log-mapped spectral centroid, calibrated against a
  27-track genre spread (the <150 Hz band was rejected: it reads warm
  folk low-mids as bass-heavy; 808s live under 90). Written by the
  normal energy scan for new files and lazily backfilled for the
  already-analyzed library (sticker-presence check, no version bump);
  one-shot parallel backfill 2026-07-20 covered all 3519 tracks. Energy,
  BPM and the cues dict's `voc` fraction cover the other traits — no new
  analysis pass beyond the spectral read.
- Unknown trait values pass profile gates (they just earn no closeness
  score) so a half-backfilled library still yields full queues; disliked
  tracks stay dead to the selector via the usual paths.

- **Mood Radio** (Library → QUICK START, replaces RADIO): click the tile
  and six labeled emotions unfold — HYPED / HAPPY / ANGRY / CALM / SAD /
  DARK. Picking one builds a queue tuned to that emotion (curated mood
  playlists as trusted exemplars → genre/subgenre weights → joi_energy
  band → likes/ratings/play counts) and leaves radio ON in a mood session,
  so refills stay on-emotion until any other play/shuffle action ends it
  (session flag is live-only, never persisted — dj_mode law). Plain radio
  still lives in the player-bar shuffle menu and Settings.

## [0.19.0] — 2026-07-18 — the library-intelligence batch (11 ideas)

- **Version-aware shuffle**: radio edits / album cuts of the same song
  collapse to ONE version per shuffle (joi_pref sticker wins, else most
  plays); the Doctor page lists every duplicate group with a PREFER pick.
- **Deep Cuts shelf** (Library → FOR YOU): the unheard side of the rooms
  he lives in — ≤2-play songs ranked by his subgenre play-share.
- **Rewind → CHAPTERS**: month + year-to-date recap cards from the play
  log (plays, hours, top tracks/artists, that month's new finds) with a
  one-tap "SAVE RECAP" playlist.
- **Rewind → YOUR SOUND**: what the listening actually is — energy/tempo
  histograms, top keys (with Camelot), minor-key share, median BPM, and a
  when-you-listen hour clock.
- **The Album Ritual** (Browse → ALBUM on any leaf folder): big-art
  front-to-back record view — tags, year, runtime, no shuffle button on
  purpose.
- **Mixtape Machine** (Playlists): exact-length tapes (30/45/60/90 min)
  from any room, arc-shaped (warm-up → peak at two-thirds → land), saved
  as a normal playlist.
- **Library Doctor** (Settings → LIBRARY): full health scan — duplicate
  versions, lossy files under 256 kbps, missing ReplayGain, tag problems,
  loudness outliers.
- **Long-track chapters**: 20+ minute files get section ticks on the
  waveform (valleys in the cached RMS envelope) — visible seek targets.
- **Now Playing story line**: "first heard Jul 13 · 42 plays · #3 this
  month · usually an evening song" — the playlog talking.
- **Per-device volume memory**: each output (IEM DAC vs the Kali/SVS rig)
  remembers and recalls its own volume on switch.
- **Phone remote v2**: bottom tabs NOW / LIBRARY / SEARCH / LISTS —
  browse the library, search (tap = play now without clearing the queue,
  + = append), and start playlists from the phone.
- Nav deep-links: `/api/nav` learned `doctor`, `album` (arg = path), and
  `rewind` with a tab arg.

## [0.18.0] — 2026-07-18 — seam loudness + disliked means disliked

- **Loudness joined the DJ cut logic** (cue scores only ever ranked moments
  *within* one song — nothing compared absolute levels *across* the seam):
  every cue now stores its envelope level (`[t, score, level_db]`; exits =
  the 2 hot bars before, entries = the 2-bar landing after; `"lv": 1`
  marks levelled stickers and older same-version stickers re-scan lazily —
  the no-bump migration, same as the key field). At bridge prep the seam
  is gated: if B's landing sits > 6 dB below A's exit (both RG-adjusted,
  cached tag reads), the planner re-picks a hotter entry that clears the
  gate, else hands off soft — a mix never dies onto a quiet floor.
  All cue consumers hardened for the 3-element rows; `djcues` CLI prints
  the levels.
- **Disliked songs are dead to every selector.** One filter
  (`_drop_disliked`) now guards every path that picks music: all shuffles
  (`_shuffle_order`), gapless segue attachment, everything queued behind
  the current song, context plays (`playFiles`), folder plays/queues
  (`playPath`/`queuePath`), plain playlist loads, smart shelves, radio +
  smart picks (already had it), and DJ pools/rooms/journeys. The one
  deliberate exception: explicitly clicking a disliked track still plays
  THAT track (and the Disliked view stays auditable). A folder or playlist
  that is entirely disliked reports itself instead of playing.

## [0.17.0] — 2026-07-18 — the Deck goes full-screen
The live DJ screen redesigned around ONE big set list (Iann's ask: show the
queue large here, with the song facts and the rating, no side-pane overlay).

- **THE SET**: the flight-plan chip strip is gone — the remaining set renders
  as a full-width list (up to 40 rows): cover art, index, title/artist, and
  cue-fact chips per song — **BPM** and **musical key** (name + Camelot code,
  e.g. "A♭ · 4B"; new `_dj_key_label` maps the chroma key int to the wheel).
  Unscored songs say "scoring…" and upgrade live as the scanner lands.
  Tap a row to audition its planned entry (unchanged ear).
- **Seams between rows**: the planned transition after each song sits under
  it as a chevron chip — full words now (SLAM / BEATMATCHED MIX / TEMPO RIDE /
  DOUBLE DROP / CUT + FADE), with the live countdown on the playing row's seam.
- **Status card**: LIVE + room, songs-left / hand-off countdown / next-style
  in one line, with CUT NOW · new-set · end-session on the card itself.
- **Rating card**: the ♥ / broken-heart vote got its own card showing the
  transition style AND the pair it joined ("A → B", new
  `djLastTransitionInfo` with pretty titles).
- **The queue side-pane stays out of the Deck**: on the DJ screen the set IS
  the queue; the pane remembers its state and returns on any other screen
  (`wanted` split from `visible` in Main.qml; SAVE MIX from the Deck hops to
  the library first so the save row has a pane to live in).
- `djTimeline` enriched (artist, duration, bpm, key, scored) and its cap
  raised 6 → 40.
- **Downvotes now teach, then forbid** (Iann's design): a 💔 no longer kills
  the pair outright — it means *that cut* was wrong. The exact cut moments
  used (A's exit, B's entry, carried through the pair bookkeeping) are
  banned (±2.5 s) in `dj-votes.json` `cue_bans`, and `_dj_cues` carves
  banned moments out of the cue table at read time — so every consumer
  (set builder, bridge prep, timed cuts, auditions) naturally re-cuts the
  songs at their next-best cues. Three failed cuts on the same pair
  (`strikes`) and the pair is blocked for good; a 👍 on a re-cut clears its
  strikes. Style penalties unchanged. A song banned out of cues on one side
  simply stops cutting there (soft crossfade). Old vote files migrate; old
  hard-blocked pairs stay blocked. The rating card shows the strike count
  ("missed 2 of 3 — this was a re-cut").

## [0.16.0] — 2026-07-18 — the full DJ Deck (20-idea batch)
The whole brainstorm, shipped. Four fronts:

**Transition craft (rendered):**
- **Bass hand-off** on mixes ≥6 bars: the outgoing song's lows morph out
  across the mid-overlap while the incoming one's morph in (120 Hz
  crossover) — two kick patterns never fight again.
- **Echo-out slams**: A's final beat repeats three times — tempo-synced,
  darkened, decaying — under B's opening. The hardest cut now sounds
  deliberate, not accidental.
- **Stepped tempo rides**: pairs 4.2–8.5 % apart (after octave folding)
  now mix — both parts step through four shared-tempo chunks from A's
  bpm to B's, entering and leaving at native speed.
- **Double-drops**: elite pairs (both cues ≥0.9, tempos within 1.5 %)
  land B's drop ON A's next downbeat — both drops hit at once, A dying
  across the shared bar.
- **Loop-extend**: a build shorter than the mix loops its earliest bar
  (up to 2× the real material) instead of shrinking the mix.

**Set intelligence:**
- **SET SHAPE** (FLAT / RISE / PEAK & COOL): the builder steers song
  energy along a curve — flat chain, steady climb, or an arc peaking
  two-thirds in.
- **SET LENGTH** (FREE / 30 / 45 / 60 / 90): sets trim to the target
  using their *planned sliced lengths*, and always end on the most
  energetic song of the final stretch.
- **B2B PARTNER ROOM**: two rooms trade tracks like back-to-back DJs;
  the cross-genre hand-offs go the soft way.
- **Key-aware chaining**: every new cue scan estimates a rough musical
  key (chroma → Krumhansl); harmonic neighbors chain first. Preference
  only — never a gate. (Mid-bridge pitch-shifting was considered and
  deliberately rejected: a semitone snap at the drop is worse than none.)
- **Anthems**: top-decile songs by plays+hearts are never sliced short —
  the set enters them on their drop and plays them out.
- **Interludes** (<75 s) never earn a set slot.
- **Re-drops** (WILD only): ~40 % of songs with a strong drop replay it
  once — a fader ride back to the entry cue at a phrase end.

**The Deck, live:**
- **Flight plan strip**: the next songs as chips with the planned seam
  (MIX / SLAM / RIDE / DD / FADE) between them; tap any chip to hear 6 s
  of its planned entry over the music.
- **IN THE MIX panel** lights up while a bridge itself plays.
- **CUT NOW**: cut to the next song at the next bar boundary — quantized,
  so even a manual interrupt lands on beat.
- **REPLAY LAST SET**: sessions log their songs + every transition to
  ~/.cache/esper/sets/; one button replays the newest exactly.

**Control & learning:**
- **AGGRESSION dial** (CLEAN / CLASSIC / WILD) replaces CURATED/ALL IN —
  one knob for gates, exit style, and re-drops. Old configs migrate.
- **Transition rating**: after each hand-off the Deck asks (♥ / broken
  heart). A downvoted pair never mixes again; three downvotes on a style
  raise that style's cue-score bar (+0.05 each, capped +0.2). Persisted
  in ~/.cache/esper/dj-votes.json.
- **OPENING STING** (off by default): a 1-second branded riser opens
  each set.

## [0.15.0] — 2026-07-18 — "one voice" (the cohesion pass)
Sigil's maximize-the-score pass on Iann's ask: kill the stock-looking symbols, make
buttons/layout/organization cohesive and human. Re-audit: 61 → 72/76.

- **The Ampere icon set** (`qml/Icon.qml`): ~35 drawn icons — 24-grid monoline, round
  caps/joins, the same voice as the A-sine mark (the "wave" icon IS the mark's crossbar).
  Replaced ~70 unicode glyph sites (💾🗑▤▦▣◈◍◷✶⌕⛶… all gone); GlowButton gained an `icon`
  property; LibCard/RailAction tiles render drawn icons. New symbols get drawn and named
  here — never a unicode glyph.
- **Player bar hierarchy:** play/pause is now the bar's ONE primary action — a filled
  circular accent button; everything else stays quiet. Drawn prev/next/loop/note/list/
  wave/mini icons.
- **Micro-states:** designed `EmptyState` component (dim icon + calm line + hint) for
  queue, search, playlists, and disliked; GlowButton is keyboard-reachable
  (Tab + Return/Space) with a visible focus ring.
- **Playlists calmed:** the 3-actions-×-22-rows repetition now reveals on hover
  (opacity, no reflow) — one quiet list, actions when you ask.
- **Spacing on the grid:** 117 off-4/8 values snapped; census now flags only deliberate
  2px hairlines. Queue header no longer overlaps its count at narrow pane widths.
- Gear/settings icon drawn as ring-with-teeth (the spoke version read as an asterisk).

## [0.14.3] — 2026-07-18 — every cut lands on the beat
- **Cues are now onset-snapped (v2).** Cue candidates came off a global
  constant-tempo grid — a 0.3 % tempo-estimate error is ~half a second of
  drift three minutes into a song, audibly off-beat. Every candidate now
  snaps to the strongest *local onset* (kick-weighted flux peak) within
  ±0.45 beat of the grid line before scoring, so entries land exactly on
  the drop's hit and exits cut exactly on the phrase-end beat. Sections
  with no distinct hit keep the grid time. Verified: 60/60 cues across 10
  random tracks (country → death metal) sit on a local onset within
  12 ms; FE!N's drop unchanged at 22.69 s.
- Since bridges anchor all bar math at the cue times, every rendered
  seam — mix rides, slam crosses, drop landings — inherits the beat
  alignment for free.
- The timed-cut fader now leads its timer by the ride's ~150 ms so the
  audible cut lands ON the cue's beat instead of a sixteenth after it.
- Cue version bumped (all v1 stickers stale): the live queue rescans
  within seconds via the priority lane; the full library re-scores in the
  background, niced.

## [0.14.2] — 2026-07-18 — invisible bridges + queue follow + DJ heartbeat
- **Bridges are gone from the queue view** — transitions just happen. The
  pane shows only real songs; every row now carries its true MPD position
  (visual index is never handed to the backend), so play/remove/reorder/
  play-next all keep working across hidden rows. While a bridge plays, the
  song it lands ON reads as current. "Play next" inserts after an
  invisible bridge, never inside a planned transition, and the planner
  drops any bridge a queue edit separates from its pair.
- **The queue follows the set**: when the playing row drifts into the
  lower quarter of the pane (or above the top), the view glides it back
  to the top — never while you're scrolling or dragging. The songs-left
  counter on the Deck no longer counts bridges.
- **DJ heartbeat (the real fix of the night).** The planner only ran when
  something else refreshed status — MPD events or the QML clock timers.
  Mid-song, with the window not driving refreshes, it could sleep for
  minutes and then render transitions at the song boundary, permanently
  too late to splice ("first hand-off always slams" was this bug wearing
  a costume). A backend-owned 4 s tick now runs the planner whenever a DJ
  session plays — renders and splices happen with a full song of lead
  time, regardless of UI state. Verified live: prep → slice → splice in
  under 2 s, mid-song.
- Planner coherence guard: during queue churn (startup sweep, splices)
  the cached queue could lag MPD and the planner indexed the wrong row —
  it now cross-checks MPD's songid and resyncs instead of planning
  against a ghost.

## [0.14.1] — 2026-07-18 — transition volume continuity, part 2
- **Bridges no longer inherit the source file's tags.** ffmpeg copied
  input A's metadata wholesale into every rendered bridge — including its
  `REPLAYGAIN_ALBUM_GAIN` (one live bridge carried −11.66 dB): under
  album/auto leveling the whole transition played up to ~12 dB quiet and
  the next song's body jumped back to full level. Renders now pass
  `-map_metadata -1` (BRIDGE_V 3 — the poisoned cache is invalidated and
  the old files were purged).
- The timer-cut fader ride settles at EXACTLY the volume it started
  from — a half-finished master-volume "loudness compensation" in that
  path (referencing a cache that didn't exist) crashed the timed cut and
  would have double-applied ReplayGain had it run; per-song loudness is
  the decoder's job, the master volume is the user's.
- **DJ decision log**: the planner now appends one line per decision
  (plan / prep / render / splice / skip-with-reason) to
  `~/.cache/esper/dj.log` (512 KB rotation) — a silent set refusal is
  diagnosable from the file instead of by adding prints and restarting.

## [0.14.0] — 2026-07-18 — "the room breathes" (design audit)
Sigil's full visual audit (48/76 baseline, `~/projects/design-audits/ampere/2026-07-18/`).

- **Theme v7 — transitions travel through hue space, never through grey.**
  The ten per-token RGB `ColorAnimation`s are gone; the three HSL inputs
  ease instead (1200 ms, InOutSine, one clock), with an unwrapped-accumulator
  hue that always takes the short arc — red→teal no longer cuts through
  grey mud, and hue wraps through 0° correctly. RoomGradient lost its own
  Behaviors and the Raw/eased token split is deleted; NowPlaying/Ambient
  gradients ride a new eased `artVividEased` instead of snapping on
  `backend.artColors`. Frame-sequence proven: monotonic short-arc hue,
  saturation dip ≤0.03, no seams.
- **Readability is now guaranteed, not hoped for.** Text-bearing tokens
  (`primary`, `secondary`, `tertiary`, `textDim`, `outline`) lift their
  lightness until they clear WCAG against every surface they sit on, and
  `bgHigh` darkens itself under bright covers until body text reads.
  Swept over 5 808 possible album colors: 0 failing pairs (was 10/15).
- **APPEARANCE → "Album colors" ON/OFF** — the adaptive room is now an
  option; OFF eases to the neutral grey room and persists.
- **Token discipline:** 22 font-size literals collapsed into a 7-step Theme
  scale (`fsMicro…fsHero`); 12 radius literals into `radiusSm/radius/radiusLg`
  + true pills.
- **Clipping under the queue pane fixed everywhere:** the Flickable views
  (Settings/Rewind/EQ/DJ) pinned their scroll columns to the viewport, wide
  fixed-width children (version line, Rewind's 14-day chart, helper texts)
  made shrinkable/elided, TrackRow's artist column yields under pressure.
- **`POST /api/nav` on the phone remote** — drives the in-app router
  (allow-listed modes); built as the audit's capture instrument, kept as a
  remote feature.
- Dead `ShadeProvider` (`image://shade`, superseded by the GPU shader in
  v4.3) removed.

## [0.13.2] — 2026-07-18 — every song settles at the same volume
- **Fixed the transition volume jump.** MPD ran replay-gain "auto", which
  applies ALBUM gain on sequential play — 65% of the library carries album
  tags that differ from track gain (median 0.3 dB, p90 1.7 dB, max 8.5 dB
  found in-library). Songs settled at album-relative levels while DJ
  bridges bake track gains: the mix would ride at one level and the next
  song's body would land at another — the "aggressive re-level or hard
  jump" at fades and cuts. Leveling now defaults to **TRACK mode**: every
  song settles at the exact same perceived volume, matching what every
  bridge, slam duck/ease, and crossfade assumes.
- **The mode is now Ampere's, not MPD's.** replay_gain_mode is runtime-only
  in MPD (a daemon restart silently reset it to mpd.conf's value); the
  chosen mode now persists in config.json and is re-enforced on every
  connect. mpd.conf's boot default flipped to "track" to match.
- Bridges are now tagged with album RG 0 dB alongside track 0 dB, so they
  read neutral under ANY leveling mode.
- Settings: leveling-mode picker reordered TRACK first (the default), with
  honest tips — ALBUM/AUTO warn that transitions can jump under them.
- Checked and cleared: MPD's peak limiter never clamps this library
  (0/500 sampled files have gain above their peak ceiling), and the
  timer-cut fader ride restores the exact prior volume.

## [0.13.1] — 2026-07-18 — clean slams, no hard level steps anywhere
- **Slams are now rendered, not raw.** Every slam becomes a micro-bridge:
  A's last 2 bars, a 90 ms equal-power fader cross (the cut of a real
  DJ's hand — impact without the click), then B from its drop with a
  **loudness-matched hand-off**: if B lands hotter than A ended, B opens
  pre-ducked by the measured difference (post-ReplayGain RMS, capped
  8 dB) and rides back to unity across 2 bars; if B lands quieter, A
  eases down toward B's level over its last bar. Verified across 24
  library slams: hand-off deltas within ±5.6 dB, median −0.12 dB.
- **No raw seam is ever the plan**: the ladder is now mix-bridge →
  slam-bridge → soft crossfade; the unrendered fallback slam runs a 1 s
  crossfade (never 0), and the timer-cut path uses a ~400 ms fader ride
  (down-advance-up) since a manual next() can't crossfade. A safety
  limiter guards every render (never engaged in QA — peaks ≤ 0.71).
- **Hardening sweep** (adversarial review + 36-render QA batch, all
  findings fixed): cue clocks vs slice-relative playback time unified
  (timed cuts now fire on the right beat for sliced songs; the Deck
  countdown and ✂ marker read true); renders are atomic (temp + rename —
  a killed ffmpeg can't poison the cache); a worker crash can no longer
  wedge the render pipeline; bridge splice-in now verifies the pair is
  still adjacent and rolls back cleanly if anything fails mid-apply;
  backward seeks re-arm cut timers; repeat-all laps can mix again;
  ending a session mid-mix no longer restarts B from 0:00; slam renders
  clamp to B's real remaining audio; syncthing conflict copies are
  excluded from the library index.

## [0.13.0] — 2026-07-18 — real mixed transitions
- **Rendered mixes are now the DJ default** — the "hard direction": 16/8-bar
  beat-aligned transitions with real volume rides. MPD can't mix live (no
  per-track volume, no time-stretch), so each qualifying transition is
  rendered OFFLINE by `esper/djbridge.py`: A's last N bars and the N bars
  of B's *build* (the bars before its drop), beatmatched with `atempo`
  (octave folding — 74 BPM mixes over 148 in 2:1 bars), equal-power
  cosine/sine volume cross, ReplayGain baked into each part, 20 ms edge
  fades. The queue plays `A(sliced) → ⇄ bridge → B(sliced)` gapless at
  crossfade 0 — every seam sample-exact, and **the drop lands exactly
  where the outgoing song dies**. Bridges are cached (~30 LRU) and appear
  in the queue tagged "A ⇄ B / AMPERE DJ".
- **Decision ladder** per pair: tempo-compatible (≤4 % folded) + gates →
  16-bar mix (auto-degrades when a build/outro can't carry it); strong
  drop but incompatible tempo → slam; else soft crossfade. Mixes prep one
  transition ahead (the playing pair can't be re-sliced), so a fresh
  session's first hand-off slams and everything after mixes.
- **MPD unix socket** — the daemon now also binds
  `~/.config/mpd/socket`; the app prefers it (bridges live outside the
  library and only socket clients may play absolute paths). TCP stays for
  mpc/remote. One-time self-heal never restarts MPD mid-song.
- Deck: MIX LENGTH (AUTO / 8 / 16) and a live "next: 16-bar mix into …"
  line. Bridges are excluded from play counts, saved playlists, stickers,
  and are purged on END SESSION and at startup after a crash.

## [0.12.1] — 2026-07-18 — transition stutter fix
- The song-change hitch ("cut/stutter when the next song & colors load"):
  the seek-bar waveform was computed with a pure-Python loop over every
  sample — ~0.2 s holding the GIL, freezing the whole UI right at the
  transition whenever the wave wasn't cached. Now numpy-vectorized
  (~7 ms, GIL released).
- Theme colors now read the prefetch-warmed 256 px thumbnail instead of
  re-decoding the full-size album art at the transition moment.
- Every background analyzer's ffmpeg (DJ cues, energy/BPM, MixRamp,
  loudness, waveform) now runs at low CPU priority (`nice`) so hours-long
  library scans can never steal cycles from MPD's own decode at a
  transition — that contention was the audible-stutter path while scans
  were running. Audited and cleared: PEQ pushes only fire on real device
  changes (not per song), sticker sweeps are ms-scale, zero PipeWire
  xruns logged.

## [0.12.0] — 2026-07-18 — the DJ
- **DJ Deck** (Library hub → SESSION → DJ DECK) — the one place DJ mode
  lives: pick a room (genre), seed from the playing song, or search any
  song to open the set with (the seed song always plays first), and a SET is
  built from that room's cut-ready songs — ranked by cue confidence,
  chained by tempo, artists spread — then live-set transitions run until
  END SESSION. The page shows room readiness (songs · scored · cut-ready),
  a LIVE panel (songs left, next-cut countdown), CURATED / ALL IN cut
  style, and the library ANALYZE with progress. A session's own room is
  always scored first; thin rooms start plain and grow cuts as scoring
  lands. No session, no cuts — there is no global DJ toggle.
- **Set range** (on the Deck): ONE ROOM — a pure genre set that never
  leaves the room; **PROGRESSIVE** (default) — a genre journey: segments
  of ~7 songs tour sonically-adjacent rooms (energy + tempo centroids,
  sibling subgenres before foreign genres), tempo carries across segment
  bridges, and a cross-genre hand-off is NEVER a slam cut — it always
  goes the soft way (phrase-end exit + crossfade), so deathcore can't
  hard-cut into a trap drop; FREE-FOR-ALL — the whole library, anything
  mixes into anything. Staging dirs (Incoming) are seedable but never a
  journey hop — their grab-bag centroid would sit near everything.
- **DJ transitions** (the engine under the Deck) — live-set hand-offs:
  cut out of the current song at the end of a hot phrase and land on the
  next song's *drop*, like a DJ slamming into the next record. A new
  analyzer (`esper/djcues.py`, ~0.3 s/track) builds each song a beat
  grid (BPM + downbeat phase) and scores bar-snapped **entry cues**
  (bass+energy slams out of a build) and **exit cues** (phrase-end
  energy cliffs), stored as the `joi_cues` sticker. The playing queue is
  scored first (cuts start within a minute of enabling), the library
  sweeps in the background; ANALYZE in advanced settings runs the full
  pass on demand.
- **The transition is pure MPD** — the queued next song is sliced with
  `rangeid entry:exit`, so entries are sample-accurate and a range end
  counts as a natural track end (crossfade still applies). Matching
  BPMs (±4%) earn a one-bar blend; mismatched pairs get the classic
  slam cut; an exit into a plain intro keeps the normal crossfade.
  No audio processing happens at playback.
- **Confidence-gated, never embarrassing** — cuts only fire when both
  sides score above the bar (CURATED default; ALL IN in advanced
  settings loosens the gates). Beatless tracks (rubato folk, ambient)
  get confidence 0 and are never touched; gapless album pairs are
  protected by the hot-tail guard; repeat-one is respected. Everything
  that doesn't qualify transitions exactly as before.
- **✂ on the seekbar** — a theme-tinted tick marks where the current
  song will hand off, so the cut is visible before it lands.
- Hygiene: every range is tracked and cleared on toggle-off, on queue
  reorder, when repeat-all loops a sliced song back around, and by a
  startup sweep (a crash can never strand mid-song starts).

## [0.11.0] — 2026-07-18 — the smart mix
- **Smart Mix (✦)** — the shuffle button's click cycle is now
  off → queue shuffle → smart mix. The mix reorders the UPCOMING queue
  so consecutive songs bridge by energy (BPM tiebreak, artists spread) —
  a hand-sequenced mixtape. Windowed: 80 songs curated past the
  playhead, self-extending as playback approaches the frontier, so a
  2000-song queue never costs a big gulp. Accidental-click armor: the
  mix is fingerprinted by the queued songs — off→on restores the same
  order; a fresh sequence only via right-click → RESHUFFLE MIX. Mode
  survives restarts.
- **Wave arc** (Settings → Smart mix shape): SMOOTH holds a flat bridge;
  WAVE ARC rises to an energy peak ~55% in and cools back down.
- **Extra shuffles** (Settings): Album shuffle and Genre shuffle are
  each OFF / MENU (right-click) / MENU + BAR (in the click cycle).
- **Shuffle menu** rebuilt: RESHUFFLE MIX ✦ · SAVE MIX AS PLAYLIST… ·
  (album/genre when enabled) · RESHUFFLE QUEUE · SHUFFLE OFF. Library-
  level shuffles live on the hub rail and collection pages.
- **Save mix** — the queue pane's save row gained a count box: cap the
  playlist at the first N songs of the queue (blank = all).
- **Trim silent endings** (default ON, Settings → Trim silence) — dead-
  air tails (hidden-track gaps, sloppy rips) are skipped: the MixRamp
  analysis already recorded where each outro's audio actually dies, and
  playback advances there. The cut lands inside pure silence, so it's
  inaudible. Active while auto-mix is off (auto-mix's own overlap covers
  the outro when on); unanalyzed files play to their real end.
- **Transition prefetch** — art thumbnails for the next 15 songs and
  waveforms for the next 3 warm in the background after every song
  change (skip-existing, throttled), so transitions never hitch the UI;
  MPD itself already pre-buffers the next track's audio.
- **Bar polish** — BOTH hearts are now drawn icons sharing one geometry:
  the like heart is filled (matching the broken heart), goes theme-color
  with a four-point sparkle notched into its shoulder when liked; the
  broken heart is monochrome white/dim (no more color emoji). Same box
  size, same centerline. Transport glyphs normalized (prev/next 19,
  shuffle/repeat 17, panels 15); ⟳ nudged up 2px (it sits low in its em
  box); glyph-only buttons share a 36px minimum width so none look
  bigger than their neighbors.

## [0.10.0] — 2026-07-18 — Ampere: the Library hub + history
- **Renamed: JOI → Ampere.** The -amp lineage says "music player" out
  loud; ampere is the unit behind every amplifier. Window title, header
  wordmark (typographic AMPERE in Rajdhani, home button as before),
  app-id `ampere` (niri rule extended), ampere.desktop (joi.desktop
  removed), phone remote, settings footer, docs. Icon = the subwave
  mark from the original icon exploration. Internals stay `esper`.
- **Dislikes (💔).** A broken-heart button next to ♥ in the bar: disliking
  a song skips it immediately, benches it from radio and Recommended
  Next, and files it on the new DISLIKED page (hub card). From there:
  restore, delete one, or delete all — every delete sits behind an
  explicit confirm dialog. Deleting runs in one of two modes from
  config.json: `delete_remote_host`/`delete_remote_root` set → the files
  are removed on the library MASTER over ssh (sync + Plex propagate the
  removal to every device; this machine is configured pve:/tank1/music);
  unset → plain local delete. Settings grew a RATINGS pair of switches:
  Hearts (♥/💔) and Star ratings can each be hidden app-wide.
- **The mark.** The AMPERE text wordmark became a real logo: the subwave
  (one bass cycle + the amber treble ripple) as a vector QML Shape, so it
  repaints in the album palette live. It sits far left as the home
  button with the history arrows after it, and the breadcrumb header
  ("/ GENRES" etc.) is removed — the logo, arrows, and page content
  carry the orientation.
- **One theme.** TWILIGHT and SLATE are gone — the album-dynamic room
  (the playing cover's palette repaints the whole app) is the only and
  permanent theme; the Settings theme picker is removed. No art still
  falls back to neutral grey.
- **The Library** — home is now a PowerAmp-style directory rethought for
  the desktop: an identity rail (LIBRARY in display type, live song/album/
  artist/hour counts, the three quick-start actions) beside an index of
  category cards — ARCHIVE (Genres, Playlists, Liked), FOR YOU (the five
  shelves + Rewind), SESSION (Queue, Now Playing, Lyrics), Top Artists.
  Cards carry live counts, cover ghosts, and accent bars; action cards
  (Liked, Queue) are marked ▸ and act immediately instead of navigating.
  The genre wall lives on unchanged as the GENRES page. The rail folds
  into the scroll column below 860px.
- **Browser history** — every page change is a stop: ‹ › arrows in the
  header, Alt+←/→, and the mouse side buttons go back/forward exactly
  like a browser. Compound navigations (artist pages, shelves, search
  results) coalesce into single history entries.
- **Ctrl+N** toggles Now Playing from anywhere.
- **Radio = the fourth loop state** — the ⟳ button now cycles
  off → queue → song → **∞ radio** (the loop that never ends: the queue
  refills itself with taste-weighted picks). The ∞ marker on the button
  is radio's identity; the separate shuffle-menu entry is gone, Settings
  keeps the mood config under "Radio · ∞ loop", and the hub quick-start
  card explains it.
- **Vinyl view and the in-page visualizer removed.** The spectrum strip
  and its v0.10 full-bleed replacement are both out — the real
  visualizer (a fully animated, per-song adaptive experience) is parked
  in NOTES.md for a dedicated build. Ambient mode's spectrum floor is
  untouched.

## [0.9.0] — 2026-07-18 — responsive + simple/advanced settings
- **Responsive player bar** — the bar now compacts by tiers as the window
  narrows: codec + LVL chip drop first (≥1150px only), then the time
  readout (≥950), then the album art (≥850), then the volume slider
  (≥640, the mute icon stays and the whole volume group answers the
  scroll wheel). Every *control* survives every width; only readouts go.
- **Responsive shell** — breadcrumb width no longer goes negative on
  narrow windows, the search pill keeps a 170px floor, and the queue pane
  scales 350→240px with the window instead of squatting on the content.
- **Simple/advanced settings** — new ADVANCED toggle in Settings
  (persisted). Simple keeps each feature as one best-default switch;
  advanced reveals the dials: loudness leveling grew QUIETER/STANDARD/
  LOUDER one-click presets (simple) over leveling mode AUTO/TRACK/ALBUM
  + exact tagged/untagged dB trims (advanced); auto-mix is a bare switch
  in simple, with threshold/blend-vs-fade/analyze under advanced.
- **Contradiction sweep** — auto-mix ON now quietly backfills missing
  MixRamp tags (it previously did nothing on an unanalyzed library);
  toggling loudness off/on no longer resets an advanced ALBUM/TRACK mode
  choice back to AUTO; the crossfade row explains itself while auto-mix
  fade is timing hand-offs per song; mini mode hides the lyrics/queue
  buttons that could not work there instead of showing dead controls.

## [0.8.0] — 2026-07-15 — the seven-ideas batch
- **Ambient mode** — the room screensaver: fullscreen near-black stage,
  album art breathing in a slow drift, live spectrum along the floor, the
  current synced lyric line, clock. ☾ on Now Playing; click or Esc leaves.
- **Gapless-aware shuffle** — the energy scan now also measures each file's
  last-1.5s level (`joi_taildb` sticker; existing analyses get a cheap
  backfill pass). Every shuffle/radio path re-attaches segues: a track that
  ends hot pulls its album-next track in behind it (chain-capped at 3)
  instead of slicing the transition mid-note.
- **More like this** — right-click any track row → it plays now with a smart
  session built behind it (same engine as Recommended Next, seeded by that
  track instead of the playing one).
- **The Log** — Rewind grew a 14-day plays-per-day timeline; tap a day to
  see exactly what played then, tap again for the full recent list. Rows
  requeue on click like any track list.
- **Leveling meter** — a small LVL chip next to the codec info shows what
  ReplayGain is doing to the current track ("+/-x.x dB" incl. preamp);
  untagged files are flagged in red — those are why volumes jump.
- **Crossfade-by-energy** — fade length now scales with the hand-off's
  analyzed energy: calm→calm drifts long (~1.3×), heavy→heavy cuts tight
  (~0.6×), applied before the beat-aligned bar snap. Works even on
  MixRamp-untagged files (scales the base crossfade).
- **Queue save polish** — empty-queue guard + a toast confirming
  saved/replaced with the track count.
- **Consistency** — shelf tiles and smart-shelf SHUFFLE no longer hand-roll
  JS Fisher-Yates (which skipped artist-spread); everything routes through
  one backend `playFilesShuffled` → house shuffle (spread + gapless).

### [0.7.1] — 2026-07-15 — responsiveness + shuffle semantics
- **Fixed the core-pegging freeze.** `energy._estimate_bpm` could produce a
  non-positive `best_lag` (from the parabolic interpolation), making `bpm <= 0`;
  the octave-folding `while bpm < 70.0: bpm *= 2.0` then spun *forever*
  (0×2==0; negatives double toward -inf, never reaching 70). One pathological
  track stuck the background-analysis thread at 100% of a core — the "freezing
  a lot when I play audio." Guarded against non-finite / non-positive tempo.
- **Search-index rebuild moved OFF the GUI thread.** `listallinfo` over the
  whole library + parse ran inline on every database event (the leveling/energy
  passes fire one per file); now a worker with its own connection builds it and
  swaps the reference atomically (`_index_worker`/`_on_index_ready`).
- **Background scans throttled** to a ~40% duty cycle (energy + replay-gain),
  and **all BLAS backends pinned to a single thread** (scipy-openblas shipped
  with MAX_THREADS=64 and busy-waits its pool — pure overhead for these tiny
  FFTs). Enrichment can no longer starve the UI, even on big audiocap drops.
- **Shuffle semantics split.** A shuffle button that sits *on a collection*
  (genre tile, folder, artist, playlist) now **plays it shuffled immediately**
  (`shufflePathNow` / `shufflePlaylistNow` / `shuffleAllNow`). The bottom-bar
  shuffle keeps the "shuffle in *after* the current song" behavior.

## [0.7.0] — 2026-07-13
The ten-ideas batch, built while he was out.
- **Rewind** — listening stats page: all-time plays/hours/tracks, top
  artists (medallions) and tracks, plays-by-genre bars; 7/30-day tiles fed
  by a new append-only play log (~/.config/esper/playlog.jsonl).
- **Lyrics search** — "IN THE LYRICS" section on the results page with the
  matching line as a snippet (background-indexed embedded lyrics).
- **Energy-aware radio** — every track gets joi_energy/joi_bpm stickers
  (background analysis, esper/energy.py); radio moods MATCH / ANY / CALM /
  HEAVY in Settings shape the picks.
- **Beat-aligned fades** — tag-timed crossfades snap to whole bars of the
  outgoing song when its BPM is known.
- **Crate bridge** — IMPORT FROM SPOTIFY in Playlists: materializes any of
  his Spotify playlists from tracks he owns (esper/spotbridge.py, reuses
  the crate credentials; "Gallows (Spotify)" was the proof).
- **Phone remote** — the app serves a mobile remote at :8480 (LAN/tailnet;
  esper/remote.py); Settings shows the tap-to-open URL. On by default.
- **Visualizer** — 28-band live spectrum on Now Playing (esper/spectrum.py,
  parec tap on the EQ chain, ~0.8% CPU), toggle next to fullscreen.
- **Vinyl mode** — Now Playing alternative: spinning platter at an honest
  33⅓ rpm, round-label album art, tonearm that lifts on pause.
- **Throwback shelf** — sixth FOR YOU shelf: what he was playing 2 weeks
  to 4 months ago.
- **Long-track resume** — 20-min+ tracks (mixes, sets) remember their
  position via stickers and pick up where he left off.
- Versioning: this repo, semver tags, pyproject packaging (`pip install -e .`
  → `joi`), version shown in Settings.
- Fix: page-open events now ride an explicit `active` flag — PageSlot's
  opacity-based visibility never re-fired child onVisibleChanged.

## [0.6.0] — 2026-07-13
The rename + "everything, verified" session.
- Renamed Esper → BASS-LINE → **JOI** (final): app-id, desktop entry, niri
  rule, Great Vibes neon icon + in-app home mark.
- Theme v5: JOI house theme (indigo twilight / cyan / pink / amber),
  ALBUM dynamic mode, SLATE.
- Home redesigned as an art wall: Quick Start, genre wall, For You
  shelves (badges), playlist tiles, top artists, system row.
- Library radio (auto-refill queue from ratings/likes/play counts),
  smart shelves (arrivals / heavy rotation / loved-not-lately / history).
- Search v2: fuzzy artist results ranked by intent + play counts, full
  Spotify-style results page on Enter, Ctrl+F focuses search.
- Artist pages: full discography grouped by album, ordered by play counts;
  fixed artist-folder resolution (deepest→exact/shallowest match).
- Loudness leveling: one toggle; background EBU R128 analysis writes
  ReplayGain 2.0 tags into unleveled files, self-heals on launch/db-update.
- Genre EQ (variant per genre, auto-switch), seek-hover time ghost,
  live bitrate, artist-spread plain shuffle, round-cropped avatars via
  art provider, static no-art image, normalization plumbing, daily data
  backup timer (stickers + EQ profiles + config).
- MPD no-crossfade bug root-caused (stale daemon state) + trace tooling.

## [0.5.0] — 2026-07-12
Pre-repo history (see NOTES.md): v0.1 player (genre wall, browse, queue,
search, playlists, MPRIS), per-device PEQ + autoswitch + AutoEq import,
fuzzy search, waveform seek, synced lyrics, Now Playing, themes v2–v4.3,
MixRamp auto-mix (level blend + fade-in), likes/ratings/play counts,
fullscreen + mini mode, artist pages with bios, EQ presets + tone strip.

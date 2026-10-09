# Order blocks breakers and mitigation blocks

Research and implementation design for the Quantitative Trading Research Lab

Version 3.0 | 7 October 2026 | Revised to Daniel’s OB-layer requirements

**Status (2026-10-08): DESIGN APPROVED — IMPLEMENTED (`src/ict_blocks/`) — MACHINE VALIDATION PASSED — PENDING HUMAN VISUAL APPROVAL; NOT FROZEN** (D-153 – D-157; OB-I0 binding §22; implementation evidence §23). Original status line: USER DEFINITIONS SETTLED; IMPLEMENTATION HANDOFF AUTHORIZED; FEATURE NOT IMPLEMENTED OR FROZEN. This revision supersedes v1/v2 and the earlier PDF. The current task updates the document and prepares Claude’s handoff; it does not execute repository implementation. Prior fixture results are historical and do not validate this revision.

## 1 Purpose, scope and revision authority

Implement an independent OB feature layer with three lifecycle stages: **ORDINARY, BREAKER and MITIGATION**. BREAKER and MITIGATION are alternative potential evolutions of an established ordinary OB, not mandatory consecutive stages. A routine return into an ordinary OB does not rename it MITIGATION.

User-confirmed requirements for this revision:

- Scope includes ordinary OB, mitigation block and breaker block now; other named blocks remain deferred.
- Reuse the existing Swing function with an OB-specific default N=1. Interpret N as left_depth=right_depth=N; this interpretation is explicit and configurable at the OB layer.
- Reuse accepted FVG facts. C2 need not touch or overlap the OB: in a bullish departure it can already lie entirely above the region (bearish mirror below).
- Use one last source candle only. Require a body >=4 ticks with the opposite colour to the ordinary OB direction. Reject a last candle with body <4 ticks; never substitute an earlier candle. No multi-candle aggregation is implemented.
- Discovery is swing-episode driven. Once an OB exists, consecutive FVGs without a new eligible swing do not restart source search or create further OBs for that episode.
- External/Internal Liquidity are separate feature layers. Neither their availability, boundaries nor consumption predicates gate OB detection or lifecycle. Strategy-level confluence and priority may use them later.

The previous design conflicted with these instructions by scanning from every FVG, using 2/2 swings for OB motifs, misinterpreting the consecutive-candle discussion as mandatory aggregation, allowing direct BB/MB formation without an ordinary parent, and proposing detector-owned context/ranking. Those rules are replaced below.

One persistent block_id identifies the object throughout its lifecycle. Immutable stage epochs record the changing role and direction, with their own availability and interaction history. This is a lifecycle object even when the M7A implementation uses separate epoch entities. Standalone direct-motif BB/MB admission is excluded in this scope; such patterns can be rejected/audited as NO_ORDINARY_PARENT.

Confirmed requirements are binding. Source selection and geometry are settled by the subsequent user clarifications. Swing lows can establish bullish OBs and swing highs bearish OBs independently. Section 20 records decisions and distinguishes retained operational conventions from direct user instructions. Claude must verify the causal algorithms against repository contracts before implementing them, without reopening settled choices.

## 2 Evidence method and source register

The research reads the speaker's original lectures through archived, timestamped transcripts. The transcript hosts are third-party archives, not the authors of the teachings. Automatic transcripts contain errors; directional descriptions were checked against their mirrored constructions and adjacent passages. No full video frame-by-frame audit, empirical efficacy study or exhaustive review of every ICT lecture is claimed. Times below refer to the original lesson, not the transcript page. The original mentorship teaching and its later public uploads are separate publication contexts; transcript-host crawl dates are not lecture dates.

| Id | Original lecture and useful passages | Primary publication | Transcript examined |
|---|---|---|---|
| S1 | Month 04 Orderblocks; 00:56-01:40 definition and validation; 05:46-06:09 bodies; 09:56-10:39 mean threshold | https://www.youtube.com/watch?v=PIYh0CxoY9c | https://info.quagmyre.com/xwiki/bin/view/Forex/The-Inner-Circle-Trader/ICT-2016-Premium-Mentorship-Core-Content-Lectures/27-ICT-Mentorship-Core-Content-Month-4-Orderblocks/ |
| S2 | Month 04 Mitigation Blocks; 02:38-03:10 failure swing; 03:40-05:14 intervening rally and last down candle | https://www.youtube.com/watch?v=FOUzW0QmsfI | https://info.quagmyre.com/xwiki/bin/view/Forex/The-Inner-Circle-Trader/ICT-2016-Premium-Mentorship-Core-Content-Lectures/28-ICT-Mentorship-Core-Content-Month-4-Mitigation-Blocks/ |
| S3 | Month 04 ICT Breaker Block; 00:35-02:39 bullish stop run; 02:45-05:53 definitions and mirrored construction | https://www.youtube.com/watch?v=UrS-mtGHtAA | https://info.quagmyre.com/xwiki/bin/view/Forex/The-Inner-Circle-Trader/ICT-2016-Premium-Mentorship-Core-Content-Lectures/29-ICT-Mentorship-Core-Content-Month-4-ICT-Breaker-Block/ |
| S4 | Month 05 Defining Institutional Swing Points; 01:38-02:25 stop run; 18:59-21:46 failure swing | https://www.youtube.com/watch?v=xRjKtUEKkSE | https://info.quagmyre.com/xwiki/bin/view/Forex/The-Inner-Circle-Trader/ICT-2016-Premium-Mentorship-Core-Content-Lectures/43-ICT-Mentorship-Core-Content-Month-5-Defining-Institutional-Swing-Points/ |
| S5 | Month 04 Reclaimed ICT Orderblock; 03:34-05:23 old down candles and opposite side of the model | https://www.youtube.com/watch?v=X5pQjfkAUCI | https://info.quagmyre.com/xwiki/bin/view/Forex/The-Inner-Circle-Trader/ICT-2016-Premium-Mentorship-Core-Content-Lectures/31-ICT-Mentorship-Core-Content-Month-4-Reclaimed-ICT-Orderblock/ |
| S6 | Month 04 ICT Propulsion Block; definition, prior-block retest, mean-threshold sensitivity | https://www.youtube.com/watch?v=glu98jAH8vE | https://youtubetotranscript.com/transcript?current_language_code=en&v=glu98jAH8vE |
| S7 | Month 04 ICT Rejection Block; wick and body reference construction | https://www.youtube.com/watch?v=oALYX0HCSYw | https://youtubetotranscript.com/transcript?current_language_code=en&v=oALYX0HCSYw |
| S8 | Month 04 ICT Vacuum Block; opening-gap context | https://www.youtube.com/watch?v=shPGUz9pU-A | https://info.quagmyre.com/xwiki/bin/view/Forex/The-Inner-Circle-Trader/ICT-2016-Premium-Mentorship-Core-Content-Lectures/33-ICT-Mentorship-Core-Content-Month-4-ICT-Vacuum-Block/ |

Research summaries below are brief paraphrases. Later formulas are this project's operational definitions, distinct from the source-supported descriptions. These features infer patterns from OHLC; they cannot establish institutional positions, remaining limit orders, trader inventories or the actual motive behind price movement.

## 3 What the primary definitions establish

### 3.1 Ordinary order block

S1 describes a bullish candidate using a down-close candle at a low near support, with attention to its body. A subsequent trade through its high validates it in that lesson. The bearish construction mirrors it. Body midpoint is the mean threshold; wick extremes also appear in risk discussions. Thus a universal rule of merely selecting the last opposite candle before any rally is an oversimplification. Nor does that passage make a named BOS/CHoCH event mandatory for every ordinary block. [S1]

### 3.2 Breaker block

S3's bearish construction raids an earlier high, then breaks the intervening swing low; the block comes from a down-close candle/range around that low. Its bullish mirror raids an earlier low, then breaks the intervening swing high, using an up-close candle/range around that high. The defining ingredients are the prior-extreme raid, intervening source region and opposite reversal break. Failure of an arbitrary OB alone is insufficient to reproduce that definition. [S3]

### 3.3 Mitigation block

S2 presents a failure swing and a subsequent break of the intervening pivot. Its bearish example refers back to the last down candle around the low preceding the failed rally. S4 contrasts a stop-run reversal with a reversal that falls short of the prior extreme. Accordingly, this design distinguishes a pattern-defined Mitigation Block from the everyday verb 'mitigate' used for a return into any zone. 'No raid' is relative to the selected comparison extreme and excursion; it does not assert that no other liquidity anywhere was swept. [S2, S4]

### 3.4 Related types

A reclaimed block references a prior block reused as the market model progresses; it is not automatically every breaker that flips back. [S5] Propulsion concerns a new block formed into a previously established block; parent-child support/resistance is part of its context. [S6] A rejection block uses the wick area relative to body reference prices and is geometrically different from a body-defined OB. [S7] A vacuum block concerns opening-gap behavior. [S8] These are useful future extensions, not obligatory stages of all OBs.

### 3.5 Taxonomy to implement

| Concept | Formation class | Interaction attribute | Lifecycle interpretation |
|---|---|---|---|
| Ordinary OB | Opposite candle plus qualified departure | Untouched, touched, penetrated, midpoint observed | ACTIVE until failure or data exit |
| Breaker | Stop-run reversal motif | Same interaction vocabulary, new role epoch | Successor stage of an ordinary OB; requires its own motif |
| Mitigation Block | Failure-swing reversal motif | Same interaction vocabulary, new role epoch | Alternative to breaker, not a routine retest stage |
| Mitigated ordinary OB | Still ordinary OB | Price has re-entered its region | No rename to MB |
| Reclaimed | Reuse context | New causal association | Deferred extension, not generic repeated flipping |
| Propulsion | Child block at prior block | Parent relationship | Deferred overlay/child formation |
| Rejection | Wick/body geometry | Zone interaction | Separate detector and source region |
| Vacuum | Opening-gap context | Gap evidence | Separate detector, not ordinary mitigation |

## 4 Repository grounding and design boundaries

The original v1 read-only GitHub retrieval on 7 October 2026 reported `main` contains frozen Market Structure and Internal Liquidity status. It also retrieved the M7A state contract, Swing fact contract and Market Structure engine. Files inspected and returned file SHAs:

| File | SHA returned by GitHub | Design dependency |
|---|---|---|
| CLAUDE.md | 6b0bbeab430c05063d518dc7ab4168f3e905411b | Claude implements externally approved definitions; bounded changes |
| docs/project/ROADMAP.md | b99255c79e9438247fb2e186eb4de9b2f5dbdbe9 | OB is a downstream ICT family; MSS remains deferred |
| docs/project/MARKET_STRUCTURE_SPEC.md | b17b0f2ccea40d73037f6ab31a839e60758957cd | Close-beyond swing evidence, causal admission, reset semantics |
| src/state/contract.py | ff9ea0b615539188d2fa4d6d1ca7dad80a23e155 | Fixed entity frame, transition frame and namespace graph |
| src/market_structure/swing.py | c9155fad49724970293be60ff838a432c262e80b | Plateau-aware confirmed facts, BAR_SPAN identities |
| src/market_structure/structure.py | 29ffa8f1fe73f30dfd66689fa1da6aec3de2cdf2 | Expected-schedule reset adapter and explicit replay cutoff |

These are file blob SHAs, not repository commits. The original v1 research read FVG rev 1. That grounding is historical: the subsequent FVG rev 2 review and user-approved rules supersede it. Claude must bind to the actual approved implementation/definition version before OB implementation, including C2 body coverage and pre-C1 normalized gap strength. Do not assume a merge has occurred.

Use six independent timeframes: 1m, 5m, 15m, 1H, 4H and Daily. Canonical mitigation observations are 1m. Structural confirmation and block invalidation use the block's own timeframe. Do not classify breaks on one timeframe with another timeframe's closes. Use actual M3 spans, including truncated buckets. M6 is optional evidence only; do not assume its approach-based interactions are the block definition.

No strategies, orders, profitability claims, optimization, VALIDATION/OOS access, Nautilus redesign or changes to frozen engines are in scope. A local pivot-based reversal break is not automatically generic CHoCH or ICT MSS. A later composition layer may join generic event references. The OB detector does not require or compute generic BOS/CHoCH/MSS. MSS remains deferred.

These are independent price zones, not automatically Internal Liquidity levels. Do not impose Internal Liquidity's inside-the-External-range restriction on block detection. Liquidity linkage belongs to a later strategy/composition layer, not the OB detector’s required inputs, output ranking or lifecycle.

## 5 Dependencies, N=1 and single-candle geometry

### 5.1 Required inputs and configuration

Market-data primitives supply complete observations, schedule continuity, instrument ticks and basis metadata. The two required feature dependencies are Swing and FVG. Liquidity and generic Market Structure events are not required feature inputs.

Repository check for this revision: `src/market_structure/swing.py`, blob `c9155fad49724970293be60ff838a432c262e80b`, exposes `SwingDefinitionSpec(definition_version, left_depth, right_depth)` with each depth >=1 and **no defaults inside the frozen contract**. The OB wrapper supplies explicit left_depth=1 and right_depth=1 by default. It uses the public detector, not this fact-envelope module as though it performed detection. Record both depths and the Swing definition version in the OB manifest and identities.

Changing N creates a different OB definition/run, not a mutation of historical swings. Do not change existing 2/2 Market Structure or FVG first-marker consumers. OB uses raw accepted FVG facts, not the FVG first-in-swing marker, whose association can use a different Swing configuration.

N=1 means one observation on each side of the plateau under the existing plateau rules. It does not mean a one-bar lookback cap, immediate confirmation at the pivot, or a three-bar guarantee for a multi-bar plateau. More frequent pivots can create more OB episodes; this is a consequence to measure, not silently suppress.

### 5.2 Last source candle only; no fallback

Use the last source observation of the selected Swing source span (the terminal plateau member when the Swing has a plateau). This makes “last” explicit; it is an operational mapping to the existing Swing contract, not a backward search for a candle that passes a filter. Verify this mapping against repository plateau fixtures before implementation.

- Bullish ordinary OB: source candle close < open.
- Bearish ordinary OB: source candle close > open.
- body_ticks = abs(close_ticks - open_ticks). Require body_ticks >=4.
- body_ticks <4 is the project’s doji/small-body rejection, even if open and close differ. Exactly 4 ticks qualifies.
- Select the last source candle **before** applying direction/body tests. If it fails either, reject the episode with SOURCE_BODY_LT_4_TICKS or SOURCE_DIRECTION_MISMATCH. Never choose an earlier plateau member, earlier opposite candle or prior valid block instead.
- Source geometry uses only that candle. Earlier same-direction candles are contextual history, not region members. No 1–3 candle aggregation, fallback search or morning-star exception exists.

Morning/evening star and rejection blocks remain separate future definitions; neither is automatically equivalent to the other. A rejected ordinary source is not silently admitted as another block class.

### 5.3 Open-to-wick geometry

| Original ordinary direction | lower | upper | Close invalidation while ordinary |
|---|---|---|---|
| BULLISH | source.low | source.open | close < lower |
| BEARISH | source.open | source.high | close > upper |

Use exact integer ticks. zone_midpoint_half_ticks = lower_ticks + upper_ticks. Zone midpoint describes this actionable open-to-wick interval; it must not be silently called the source-body mean threshold. Preserve source_body_midpoint separately if exposed, with its own clear field name. Neither analytical midpoint is rounded to a tradable tick.

Store the source OHLC, complete wick envelope and body bounds as evidence; only the table above defines the actionable region. A stage’s direction determines proximal/distal ordering, never its inherited geometry. A bearish BB/MB descended from a bullish OB keeps [source.low, source.open]; its retirement boundary is the inherited upper (source.open), not the source high. Bullish successors mirror this.

Strict own-timeframe close beyond the current stage’s far boundary invalidates it; equality and wick penetration alone do not. Touches do not retire stages. Geometry remains immutable after ordinary admission.

## 6 Swing-episode-driven ordinary OB discovery

### 6.1 Discovery state is separate from the block lifecycle

Maintain per instrument/contract/timeframe/direction and Swing definition a discovery episode keyed by the anchor swing_id. Candidate states are WAITING_FOR_DEPARTURE, ADMITTED, REJECTED and SUPERSEDED. These are audit/search states, not tradable OB stages.

A newly confirmed relevant swing opens an episode and runs source selection once. Match existing causal FVG facts or wait for later FVG arrivals. FVG events may advance a waiting candidate, but must not initiate a fresh backward source scan when no new eligible swing exists. ADMITTED episodes are latched: later FVGs do not create another block or refresh its source.

“No new OB evaluation” does not disable ongoing close invalidation, interactions, reversal monitoring or data resets for an existing block.

### 6.2 Qualifying departure

Operational bullish rules, bearish mirrored:

- Source candle is fixed and attached to the episode’s confirmed LOWER swing.
- Use the first accepted same-timeframe bullish FVG whose C2 starts at or after the source candle ends, before the episode’s structural cutoff. C1 may be the source candle or a later candle. C2/C3 cannot be source candle.
- There is **no requirement** for FVG C2 or the gap itself to intersect the OB. A later departure FVG can lie fully above it.
- Require a complete own-timeframe close strictly above the source.high after source completion and no later than ordinary admission. Bearish requires a close below source.low. This retains v1’s stronger-than-trade-through validation as the retained project rule.
- Reject a source if any own-timeframe close after source completion through ordinary admission has already crossed its far actionable boundary adversely. No ordinary block is admitted already failed.
- ordinary_available_at = max(swing.available_at, source_available_at, qualifying_FVG.available_at, validation_close_at).
- Matching may inspect earlier formation evidence once the swing confirms, but cannot backdate availability or create historical retests. If a reset occurs before admission, reject instead.

The required FVG is formation evidence, not a lifetime dependency. Later FVG conversion/retirement does not retire the OB. A reversal FVG is not required for BB/MB under the retained motif rule.

### 6.3 Rearming, opposite OBs and causal ownership

Each **new confirmed relevant same-side swing** with a nonoverlapping source span after the previous anchor permits one fresh discovery episode, including a higher low for bullish OBs or lower high for bearish OBs. An opposite swing can open an **opposing ordinary OB** episode: UPPER→bearish, LOWER→bullish. Both directions may coexist. It does not open another episode in the old direction and does not itself convert the older block. It also supplies structural evidence for reversal tracking and bounds the outgoing departure excursion.

This differs intentionally from FVG’s first-in-leg rule: that rule does not restart on every higher low. Do not import it silently into OB discovery.

Causal handling:

- A new relevant swing supersedes an unadmitted same-direction candidate prospectively; an admitted older block keeps its own lifecycle.
- An opposite swing closes departure eligibility for the candidate at its source span; its confirmation can delay the decision that a proposed FVG belongs to that excursion. Hold a provisional match until any unresolved swing at/before that FVG anchor that could change membership resolves.
- Do not revoke an earlier strategy-visible OB using a newly confirmed past swing. Resolve candidate ownership before admission, using the public Swing detector’s candidate/plateau contract or an equivalent verified wrapper.
- A replay ending before that decision is knowable contains the waiting candidate, not an admitted block. The precise ownership/deadline wrapper must be proved for N=1 and plateau cases before implementation approval.

Do not impose the FVG first-in-leg more-extreme-origin rule. Each new eligible swing can establish an OB in its corresponding direction, subject to source and departure qualification.

At most one block per source candle and definition/basis, even if several swing anchors map to the same candle. Keep alias episode evidence, not duplicates. Neither a later FVG nor reusing an exhausted source revives an old block.

## 7 Breaker and mitigation as successor stages

### 7.1 Parent requirement and immutable lineage

Every actionable BB/MB must have a previously admitted ordinary block with the same block_id and source_region_id, opposite stage direction and earlier ordinary_available_at. No null parent, DIRECT_MOTIF path or retrospective synthetic ordinary parent exists in this scope. The ordinary stage must actually have been available before its failure; an object cannot be created as ordinary and immediately converted on its own admission bar.

A standalone textbook pattern without an eligible ordinary parent may be recorded as NO_ORDINARY_PARENT in audit, but is not an actionable BB/MB. This is an explicit project scope restriction and may reduce coverage versus broader literature definitions.

### 7.2 Structural evidence uses OB-specific Swing facts

Bearish successor of a bullish ordinary block:

- B is the parent’s pinned LOWER swing anchor; do not search a replacement B to improve classification.
- A is the latest eligible UPPER swing strictly before B, selected from source-ordered nonoverlapping spans and known before the observed raid reference is used.
- C is a later confirmed UPPER swing, strictly after B, associated with that parent’s departure excursion.
- x is the first eligible complete own-timeframe close after C’s source span strictly below both B.price and the parent region’s lower bound. B must have been known by x.bar_start.
- BREAKER requires C.price>A.price and observed strict raid evidence in that excursion.
- MITIGATION requires C.price<A.price and no observed strict raid above A anywhere in that same excursion through x, inclusive.
- C.price=A.price without a raid is EQUAL_EXTREME, unclassified under the retained default.

Bullish successor mirrors every inequality and orientation. Use N=1 by default for A/B/C consistently. A geometric strict swing raid is not a call to an External/Internal Liquidity detector and does not import their 4/6-tick consumption thresholds.

C selection must be deterministic within the parent excursion. Use the first source-ordered eligible opposite swing after B; if a later more extreme C supersedes it before the reversal break, retain candidate versions and all raid evidence. Selecting a later lower C never erases an earlier raid. Noncanonical raid/failure sequences remain rejected rather than guessed into MB. This retained operational selector and excursion closure must be checked against causal replay and real N=1 plateau fixtures before feature implementation; an optimization must not alter it.

### 7.3 Failure can precede successor confirmation

Under the selected terminal swing-source mapping, a bullish OB lower equals B.price (and a bearish OB upper equals B.price). Thus the old body-boundary-versus-wick delay argument is superseded: price failure and pivot passage coincide. Availability can still differ because C confirmation or motif resolution is delayed. Failure immediately removes ordinary actionability; it must not wait for BB/MB qualification.

A failed block may remain in FAILED_AWAITING_CLASSIFICATION, nonactionable, while the pinned excursion/motif resolves. It can later enter BREAKER or MITIGATION only from the original source/parent evidence, never a fresh attempt after terminal retirement. If the excursion resolves without a qualifying motif, record FAILED_FINAL. A gap/roll ends this pending eligibility too. No arbitrary time expiry is introduced.

Successor_available_at = max(x.close_time, A/B/C availability, ordinary failure availability, all selection-resolution times). Preserve break_observed_at separately. Check all complete closes from x through successor admission: if the proposed successor already invalidated, record QUALIFIED_BUT_INVALID_BEFORE_ADMISSION and no actionable stage. No backdated conversion or inherited pre-admission retest.

### 7.4 Chronology and exclusivity

Source spans are strict/nonoverlapping under the existing Swing contract. C and x are distinct bars; C’s source must precede x. A raid and final reversal close can occur in the same outside bar—the close is necessarily last—but that does not establish a distinct preceding C. Keep this chronology restriction explicit; it is an explicit operational model boundary, not an OHLC impossibility claim.

Only one reversal branch is admitted per block in this stage. It remains BREAKER or MITIGATION for that epoch; later price does not rename it. No BB→MB, MB→BB or repeated inversion. When a successor fails its own close rule it retires. Touch/penetration does not create the MITIGATION stage.

## 8 Persistent object and lifecycle contract

A persistent `block_id` owns immutable source geometry and a sequence of stage epochs. Each epoch has stage_id, stage_kind, direction, available_at and its own interactions. BREAKER/MITIGATION reverse ordinary direction and share the source candle. They are genuine successor states of this object, not independent detectors with optional lineage.

| Logical state | Event | Next state / actionability |
|---|---|---|
| ORDINARY | Strict adverse own-timeframe close and qualified branch known at this close | BREAKER or MITIGATION directly; new epoch |
| ORDINARY | Strict adverse own-timeframe close; classification unresolved | FAILED_AWAITING_CLASSIFICATION; not actionable |
| ORDINARY | Failure with structurally resolved nonqualifying motif | FAILED_FINAL; terminal |
| FAILED_AWAITING_CLASSIFICATION | Original motif qualifies and successor remains valid | BREAKER or MITIGATION; new epoch |
| FAILED_AWAITING_CLASSIFICATION | Motif resolved without qualification / successor already invalid | FAILED_FINAL; terminal |
| BREAKER or MITIGATION | Strict adverse own-timeframe close | RETIRED; terminal |
| Any live or waiting state | Missing-data reset | TERMINATED_DATA_GAP; terminal |
| Any live or waiting raw-basis state | Pure roll | PENDING_ADJUSTMENT; nonactionable in raw run |

Direct ORDINARY→successor at one close is one logical transition, with ordinary failure included in its evidence. Do not materialize a zero-duration FAILED state followed by a second transition at the same instant. When qualification is delayed, the waiting state is real and retained in history.

M7A representation: prefer one logical lifecycle entity keyed by block_id if the existing generic graph validator supports these edges. Otherwise use immutable stage entities plus an obligatory lifecycle ledger linking them under block_id. Stage entities initialize at their own availability and exit once. This storage choice must preserve the same public lifecycle, one exit per entity/instant, exact direction and no same-close retest; it does not require a trading-definition decision or modification of M7A.

Source geometry is never reconstructed from the latest stage. Every strategy-facing state includes block_id and stage_id. A BB/MB starts with its own untouched interaction history; ordinary-stage visits remain audit history. No further reclaimed/propulsion/rejection/vacuum stages are implemented now.

## 9 Observed interactions and definite evaluation prices (open-to-wick region)

For each role and canonical 1m bar m with `bar_start(m) >= role.available_at`, same basis and no data reset:

- `touch`: observed range intersects the closed actionable interval, `high >= lower and low <= upper`.
- `penetration`: observed range intersects its interior, `high > lower and low < upper`. Endpoint-only contact does not count.
- `midpoint_observed`: m.low <= exact midpoint <= m.high, compared in doubled ticks.
- `distal_observed`: role's far boundary lies within the observed range, inclusive.
- `full_span_observed`: m.low <= lower and m.high >= upper.
- `max_interior_depth`: bullish `upper - max(m.low, lower)` or bearish `min(m.high, upper) - lower`, only for an intersecting range; clamp to [0, width].
- `adverse_excursion`: independent uncapped distance beyond the far boundary, when observed. It is not penetration depth.
- `GAP_BEYOND_REGION`: range lies wholly beyond the far boundary after previously being on the approach side. Record the observed discontinuity, not an invented fill inside the zone.

A bar wholly below a bullish region cannot be recorded as full observed mitigation merely because its low is below the distal boundary. It may independently cause close-based failure. Zone midpoint and full-boundary touches are inclusive; strict initial interior penetration remains separate.

Without tick paths, a range covering several prices does not establish their temporal order. Do not claim midpoint was hit before distal on that bar. If a gap jumps past midpoint, an interior-depth record may exceed half-width without a midpoint-observed event. Do not impose a false invariant that every deeper visit necessarily observed every shallower price.

A visit starts when range intersection becomes true after an earlier nonintersection. Consecutive intersecting minutes sharing a bar boundary are one visit, not dozens of independent retests. A scheduled closure breaks the observed visit streak without terminating the role; its first intersecting new-session minute starts a new visit. A discontinuity alone is not a visit. Do not infer the path during scheduled closures; first actual new-session bar can carry gap evidence. 'Observed' fields describe the OHLC envelope, not proof that every intermediate price traded or that orders at it were executed.

First-touch policy: retain actionability after touching or penetrating until close invalidation. Store first-touch status for later strategy filters. Do not assume orders are exhausted by one wick or that an OHLC zone has a measurable inventory of unfilled orders.

## 10 Causal batch and visibility

At each canonical-minute close:

1. Apply expected-onset gap resets and contract/basis guards to active stages and waiting discovery/evolution candidates before price comparisons.
2. Observe eligible 1m interactions against stages available at the minute’s start.
3. Classify complete own-timeframe closes against stages available at the source bar’s start; record ordinary failure immediately, even if successor evidence is pending.
4. Admit dependency facts known at this close. Feed new Swing facts to discovery ownership; feed FVG facts only to waiting eligible episodes.
5. Resolve source selections, departure matches and parent-pinned reversal motifs. Use final batch evidence without fabricated ordering among simultaneous facts.
6. Reject candidates already invalid. Materialize at most one logical transition per block at this instant and create any successor epoch once. No transient actionability or same-close chained reversals.
7. Emit immutable audit, lifecycle, interaction and strategy-view records.

Maintain source spans, source completion, swing confirmation, departure availability, ordinary availability, failure time, break_observed_at and successor_available_at separately. Post-admission observations require bar_start>=stage_available_at. Never test a stage against its formation/conversion bar.

An opposite confirmation that could change episode ownership must delay admission, not rewrite it later. Shuffled dependency rows must produce identical final outputs. All queries require explicit causal cutoff and price basis. No self-transitions for touch/depth attributes; use event/version tables.

## 11 Data gaps contracts and adjustments

Build a new adapter from public M3 expected-schedule APIs and frozen continuity outputs, following the Market Structure reset-adapter pattern. Do not import or modify a private frozen helper. Require replay_cutoff, including trailing gaps. Known maintenance breaks/weekends are scheduled closures, not missing-data resets. Compare adapter episodes with frozen continuity; fail closed on disagreement.

A 1m data gap can hide interactions and lifecycle evidence. Terminate all affected active roles, motifs-in-progress and waiting discovery/evolution candidates with an explicit missing-data warning. Post-gap formations use post-gap facts only. Do not revive a failed/retired/terminated role or infer hidden consumption. A delayed motif cannot cross a gap just because its eventual swings are available.

On a pure contract change without missing data, old raw-basis role epochs become PENDING_ADJUSTMENT at the first new-contract minute close; no raw new-contract price test is performed against them. On a gap followed by a roll, DATA_GAP remains the earlier immutable exit. Later contract provenance does not rewrite it.

No arbitrary calendar age expiry or same-contract-only historical deletion is proposed. Cross-contract comparisons are pending until the shared process supplies a valid consistent basis. Future adjustment method is deferred. Store raw geometry and versions, enforce comparability before tests, and preserve all prior runs. If a future transformation is not tick-compatible, require explicit semantics; do not silently round. On an adjusted replay with declared continuous pure-roll observations, continuing roles is a separate versioned execution basis, not a raw-run resurrection.

Mixed-contract M3 buckets fail closed; this detector must not patch frozen M3 or silently repair source data. Process gaps at expected onset, not only when the next valid bar appears.

## 12 Independent feature layer and deferred prioritization

The OB module detects sources, admits ordinary blocks and evolves their lifecycle using Swing and FVG facts plus market-data primitives. It does not load liquidity outputs, require an active liquidity range, enforce sweep tolerances from those modules or rank blocks using external/internal levels.

Current output is a descriptive feature record: exact geometry, timeframe, N, source candle, formation FVG id and its known normalized strength, anchor/motif Swing ids, stage/direction, stage availability and interaction history. A missing optional descriptor is null with a reason. No score, mandatory FVG overlap boost, cross-block confluence graph or BB-versus-MB ranking is implemented in this phase.

A later strategy/composition layer may join OBs to External/Internal Liquidity, generic structure, active FVGs and other blocks by compatible basis and causal time. Such joins cannot alter source identity, historical admission or the detector’s stage. Whether an OB near liquidity is preferable is a later prioritization/research choice.

The formation FVG need not price-overlap the block; it can sit entirely above a bullish block or below a bearish block. Do not confuse causal departure linkage with price intersection. Future confluence should name these relationships separately. FVG inversion/retirement does not remove the immutable formation link and never triggers an OB lifecycle transition by itself.

## 13 Output contracts and natural identities

| Table | Grain and essential fields |
|---|---|
| block_source_regions | Immutable region: source_region_id, single source BAR_SPAN, source OHLC/body_ticks, actionable lower/upper, zone_midpoint_half_ticks, separately named body midpoint, selection/geometry policy |
| block_discovery_episodes | One anchor episode: episode_id, anchor swing_id, direction, explicit N/depths, source candle, candidate status, known-at versions, cutoff evidence/reason |
| block_formation_evidence | Accepted/rejected source and departure matches: candidate id, FVG id/version, validation close, first known time, rejection reason |
| blocks | One persistent object: block_id, source_region_id, ordinary direction/availability, anchor_id, episode_id, definition/basis |
| block_stage_epochs | One stage: stage_id, block_id, ORDINARY/BREAKER/MITIGATION, direction, predecessor_stage_id, available_at, motif_id, inherited geometry ref |
| block_lifecycle | One logical change per block/instant: from/to, stage ids, reason, trigger ref, supporting evidence, observed_at and available_at |
| block_state_entities/transitions | Frozen M7A schemas; chosen mapping documented and validated |
| block_motifs | Parent-pinned A/B/C candidate versions, full excursion refs, raid/no-raid evidence, break x, classification/availability/rejection |
| block_interactions / block_depth_versions | Stage-specific visits, boundary observations, depth/uncapped excursion, minute evidence and timestamps |
| block_price_values | Raw and supported basis values, source contracts, adjustment version and compatibility |
| block_pending_comparisons | Basis incompatibility/pending reason and causal timestamps |
| block_data_warnings | Missing-data evidence and affected counts, including no-block runs |
| block_run_manifest | Cutoff, source fingerprints, N/depths, Swing/FVG definitions, geometry/source/episode policy versions, calendar/tick/basis |

External/internal liquidity context links and grade-version tables are **deferred**, not empty promised deliverables of this implementation.

Natural keys use canonical refs and policy versions, never a mutable grade or future outcome. source_region_id hashes instrument/contract/timeframe/single source BAR_SPAN/selection policy. block_id includes source_region_id, ordinary direction, Swing definition/depths and the approved OB definition/basis. stage_id includes block_id and unique stage kind/epoch. An exhausted source does not admit a second ordinary or reversal epoch in the same definition/basis. Same-price new source candles are distinct identities.

Record alias anchor episodes if multiple confirmed swings select one candle; choose the earliest causally admissible episode, with stable ties and no duplicates. Different N configurations are separate runs/definitions, not silently merged views.

Views: active_blocks(t) (only actionable stages), block_history(t), discovery_status(t), first_return_candidates(t), pending_blocks(t). All filter by known-at time, not source time. Fixed schemas apply to empty outputs; warnings, rejected evidence and manifest can exist without blocks. Every row carries appropriate instrument, contract, TF, basis, run_id and fact_hash.

## 14 Discovery and lifecycle reference algorithm

At a bar completion, the independent reference performs straightforward source/episode scans from facts available at cutoff. The production implementation may index those same facts, but must reconcile exactly.

```
apply_resets_and_basis_guards()
observe_existing_stage_interactions()
classify_existing_stage_closes()
admit_confirmed_swing_and_fvg_facts()
open_or_resolve_discovery_episodes_from_new_swing_evidence()
match_fvg_departures_only_to_waiting_eligible_episodes()
resolve_parent_pinned_successor_candidates()
reject_already_invalid_admissions()
materialize_one_logical_change_per_block_and_new_stage_epochs()
emit_causal_views_and_audit()
```

An ADMITTED episode is latched. Repeated FVGs do not call source selection for it. Lifetime monitoring remains active. Audit counters must separately report swing-triggered source searches, waiting-FVG matches, ordinary admissions, duplicate suppression, ordinary failures and successor admissions. This makes the “not every FVG” requirement testable.

No arbitrary history cap, price-proximity filter or liquidity-data dependency may be introduced as a runtime optimization. Candidate ownership/deadline logic in section 6.3 requires reference proof before production coding.

## 15 Worked examples and fixture obligations

### 15.1 Single source; later FVG C2 entirely beyond the region

Synthetic 5m observations, tick=0.25, N=1. Last source is k2; k1 is not aggregated into it.

| Bar | Open | High | Low | Close | Role |
|---|---:|---:|---:|---:|---|
| k0 | 104 | 106 | 103 | 105 | History |
| k1 | 105 | 105.5 | 101 | 102 | Earlier bearish candle; not selected |
| k2 | 102 | 103 | 99 | 100 | Last source, LOWER swing |
| k3 | 100 | 112 | 100 | 108 | N=1 confirmation and close validation |
| k4 | 108 | 113 | 102 | 111 | FVG C1 |
| k5 | 111 | 117 | 110 | 116 | FVG C2 |
| k6 | 116 | 119 | 114 | 118 | FVG C3 |

k2 body=8 ticks, bullish OB=[99,102], zone midpoint=100.5; body midpoint=101 is a different value. Swing confirms at k3; validation close108>source.high103. First accepted bullish FVG is k4/k5/k6=[113,114]. Its C2.low110>OB.upper102 and C2 body111→116 spans the FVG. Admission is no earlier than k6 and any unresolved causal ownership time. The source remains k2, not the prior run or an FVG-adjacent candle.

### 15.2 Small body rejects; exactly four ticks qualifies

Keep k2.high103 and low99. Change k2 open/close to101/100.25: body=3 ticks, reject the candidate despite k1’s larger valid bearish body. No fallback. Set open/close101/100 instead: body=4 ticks, eligible source with bullish region[99,101]. These examples are source qualification checks; full formation still needs Swing, FVG and validation.

### 15.3 Repeated FVGs and opposing ordinary OB

Consecutive bullish FVGs without a new relevant swing do not rearm the admitted bullish episode. A later confirmed UPPER swing may independently seed a bearish ordinary OB if its terminal source candle and bearish departure qualify. The existing bullish OB need not be deleted. This new bearish ordinary object is distinct from any bearish breaker/mitigation evolution of the old bullish object, even if events share a close or price.

### 15.4 Evolution inherits the exact interval

Bullish parent=[99,102]. Strict own-timeframe close98.75 fails it and passes B.low99. Qualified raid/failure evidence admits a bearish BB/MB with **the same [99,102]**, a new stage epoch and reversed direction. Its own retirement is close>102, not close>source.high103. If motif confirmation is delayed, ordinary actionability ends at failure and successor actionability starts only when evidence is known and it remains valid. A return on the conversion bar cannot be a successor retest.

### 15.5 Reversal predicates and remaining integration fixtures

For a bullish parent and prior A.high120: eligible C.high122 with the required observed raid and reverse close supports bearish BREAKER; C.high118 with no raid throughout the pinned excursion supports bearish MITIGATION. Equality alone is unclassified. These are predicate illustrations, not executed full OHLC lifecycle fixtures.

Construct mirrored, plateau-terminal doji, delayed C confirmation, concurrent ordinary/child admission, invalid-before-admission, outside reversal bar, gap and pure-roll cases against the actual detector. All fixtures must use the current single-source 4-tick threshold and open-to-wick interval. Never carry forward v1/v2 region or confirmation expectations.

## 16 Planned tests and invariants

All feature tests are planned, not executed for this revision.

| Area | Required verification |
|---|---|
| Swing | N=1 explicit depths; N>1 distinct identities; isolated pivots and plateaus; frozen 2/2 consumers unchanged |
| Source | Single terminal source; body 0/1/3 ticks rejected and 4 ticks accepted; prior valid candle never substituted; terminal plateau doji; direction mismatch; exact open-to-wick bounds |
| Departure | FVG C2 fully beyond region; nonadjacent FVG; approved body coverage; no required price intersection; causal match before/after swing confirmation |
| Discovery | One search per new episode; consecutive FVGs after admission do not rearm; genuine new same-side swing; opposite swing; delayed ownership; alias anchors |
| Lifecycle | Ordinary→BB and ordinary→MB; required parent; failure without successor; delayed successor; no same-close ordinary admission/conversion; no repeated flip |
| Classification | Strict raid/no raid; equality; hidden earlier raid; parent B pinned; deterministic C/cutoff; gap terminates waiting motifs |
| Interactions | Per-stage histories; no conversion-bar retest; touches vs penetration; midpoint/half-tick; gap-beyond; observed envelopes vs invented path |
| Independence | No liquidity input supplied; different/empty liquidity datasets cannot alter OB output; FVG lifetime changes do not invalidate parent OB |
| Data/basis | Gap onset/trailing gap; incomplete bars; scheduled closure; pure roll; mixed-contract fail closed; no incompatible comparisons |
| Schemas/reference | All-empty/no-block outputs; immutable ids and versions; independent naive reconciliation; shuffled-fact determinism |

Core invariants: every actionable successor has a causally earlier ordinary parent; one immutable single-candle source region per block; one qualifying departure per ordinary admission; no duplicate admission without new eligible episode; no source reselection after admission; maximum one reversal stage per block; stage availability >= every required known-at input; no same-close retest; failure ends ordinary actionability immediately; no liquidity-controlled lifecycle; exact geometry; one logical change per instant; no gap-spanning candidate; fixed schemas; prefix replay equivalence including pending association/ownership boundaries.

## 17 Machine and visual acceptance gates

Use DEVELOPMENT only, without backtests or parameter optimisation. Required machine gates:

- Input fingerprints and public Swing/FVG parity at the explicit OB depths for all consumed facts.
- Independent naive detector reproduces every ordinary and BB/MB admission, rejection, exit and source selection. If a partial reconciliation is proposed for runtime, report exact coverage and require explicit acceptance; do not call a sample full validation.
- All invariants zero; all schema/M7A validations pass.
- Prefix replays before/at/after admission, break, return, retirement, first missing slot, interior gap cutoff and pure roll.
- Source role counts, motif classifications, invalid-before-admission and chronology-rejection distributions reported, not tuned away.
- Frozen outputs remain untouched; feature run artifacts have immutable run ids.

Visual package: show at least the mirrored OB, BB and MB fixtures plus real DEVELOPMENT cases for each reachable family. Show a failure without child, equal-extreme rejection, outside-bar chronology, doji case, same-close child, actionable open-to-wick zone versus source body, separately named midpoint observations, delayed availability, gap-beyond and data reset. Synthetic cases may cover patterns absent from real DEVELOPMENT data; identify them clearly. Impossible fixtures cannot stand in for reachable patterns.

Every page shows source spans and availability markers; A/B/C price and confirmation labels; exact body/wick prices; pre-state at observation start; comparison evidence in ticks; post-state at close; separate later outcomes. Draw ordinary and successor stages as different epochs under the same block_id. Do not paint the reversal block over its earlier candle without showing the much later role_available_at. Human visual approval precedes freeze.

## 18 Executed checks and evidence limits

Historical v1 reported 221 arithmetic assertions with isolated 2/2 pivots. Historical v2 reported 82 assertions with aggregate source geometry. Neither result validates this revision.

This revision updates the design only. The earlier read-only inspection of the public Swing contract supports explicit N=1 parameters; Claude must verify the live repository version. No repository code, feature suite or DEVELOPMENT pipeline was run in this turn, and no new literature research is claimed.

A revision-specific arithmetic check covers section15.1 and its bearish mirror: OHLC/tick consistency, isolated N=1 pivot, single-candle boundaries, distinct body/zone midpoints, first accepted FVG and C2 beyond the region. It also checks small-body rejection at0/1/3ticks and acceptance at4ticks without substituting the prior candle. This check is not the frozen Swing detector, plateau implementation or production lifecycle. Executed `python3 checks/check_ob_revision3.py`: **98 assertions passed across two mirrored arithmetic fixtures**. Full dependency-backed fixtures, motif selection and prefix replay are implementation gates.

## 19 Implementation sequence and validation gates

Work sequentially in one workstream. The user has requested an implementation handoff for Claude. Bind to a stable, identifiable FVG implementation before OB integration; do not imply FVG human visual approval, freeze or merge. If FVG is unmerged, use the repository-approved dependent branch approach and record its exact commit. Do not alter FVG to make OB tests pass.

| Step | Deliverable |
|---|---|
| OB-I0 | Record section20 decisions; bind exact FVG/Swing versions; verify causal episode ownership/plateau deadlines and parent-pinned motif selection |
| OB-I1 | OB-specific N wrapper, single-candle open-to-wick regions, episode state, ordinary formation and deduplication |
| OB-I2 | Persistent block lifecycle, parent-bound BB/MB branches, immediate ordinary failure and delayed successor handling |
| OB-I3 | Stage-specific 1m interactions, own-TF close tests, data/basis reset and pending candidates |
| OB-I4 | Fixed schemas, causal views and independent reference; no liquidity/strategy ranking integration |
| OB-I5 | DEVELOPMENT reconciliation, invariants, prefix replays and visual package |
| OB-I6 | Human visual review; freeze/merge only when authorized |

Suggested module family remains src/ict_blocks/. Public dependencies are reused without changing frozen semantics. Storage adapters may accommodate persistent objects and epoch entities; do not let an existing enum shape dictate the trading definition.

## 20 Settled decisions and implementation conventions

| Item | Binding outcome |
|---|---|
| Scope | Ordinary OB, BREAKER and MITIGATION only; one persistent lifecycle object |
| Swing | Reuse public function; OB default left_depth=right_depth=1; other consumers unchanged |
| Last source | One candle only, no 1–3 candle aggregation and no backward fallback |
| Body | abs(close-open)>=4ticks; smaller body rejects even if a prior candle qualifies |
| Source direction | Bearish candle for bullish ordinary OB; bullish candle for bearish ordinary OB |
| Bullish interval | [source.low, source.open] |
| Bearish interval | [source.open, source.high] |
| Departure | Same-timeframe FVG in intended OB direction; C2 may lie entirely beyond OB |
| Rearming | New eligible LOWER→bullish or UPPER→bearish episode; consecutive FVGs alone do not rearm |
| Opposing object | Independent ordinary OB may coexist with old opposing block; not automatically its child |
| Evolution | BB/MB requires existing ordinary parent, inherited interval, reversed direction and qualifying motif |
| Separation | No External/Internal Liquidity input or ranking in this layer |
| Deferred | Rejection, morning/evening-star, reclaimed, propulsion and vacuum detection |

Retained explicit project conventions: source=terminal observation of the anchor plateau; strict source-wick close validates departure; strict current-stage far-boundary close invalidates; reversal FVG optional; canonical A/B/C motif uses strictly ordered spans, strict raid/failure inequalities and distinct prior C; touches retain actionability; no repeated inversion. These are operational choices, not universal ICT claims or newly discovered user quotations. Register them transparently rather than describing all details as individually voted on.

Before code, Claude must resolve their exact repository mapping and execute reachable fixtures, especially candidate ownership/deadlines, C selection and waiting-state termination. Routine storage, naming and deterministic ordering need no additional approval round. If a real contradiction cannot be resolved without changing the settled detection rules, report one consolidated concrete counterexample instead of silently selecting a new rule. The three user-facing choices from revision2 are closed and must not be reopened.

## 21 Claude implementation handoff

Use revision3 as the authoritative OB specification. Read repository instructions, verify actual Git state and the FVG dependency, and implement OB-I0 through OB-I5 sequentially. This handoff authorizes implementation, tests, DEVELOPMENT validation, commit/push and a draft PR. It does not authorize feature freeze, merge or strategies.

Record exact dependency commits/definitions. Integrate on an isolated branch that preserves ongoing FVG work; no unapproved FVG merge is implied. Verify plateau/source mapping, causal episode ownership and parent-pinned motif rules with real public-dependency fixtures before production code. Keep one persistent block_id and immutable stages. Reject a last source body<4ticks without fallback; use bullish low→open and bearish open→high. Permit nonintersecting departure FVGs. Do not rescan admitted episodes on each FVG. Both directions can create independent ordinary OBs; BB/MB requires parent lineage.

Use independent reference reconciliation, exact ids, fixed schemas, causal views, prefix replay, no future leakage and DEVELOPMENT-only validation. Preserve frozen outputs and raw/basis guards. Produce price-free tracked validation evidence and a local price-bearing HTML visual package under repository rules. Report actual commands, tests, counts, runtime, commits and links. Stop at draft PR and human visual review, without declaring either OB or FVG frozen/merged. Include the existing FVG test report and visual-package locations in the final handoff for the next review; clearly distinguish existing evidence from checks you executed.

## 22 Implementation binding and clarifications (OB-I0, 2026-10-08)

Recorded by Claude at OB-I0 before production code. Decisions are registered as **D-153 – D-157**. Design approval and
implementation authorization are distinct from implementation validation (machine checks plus human visual review)
and from feature freeze; neither has happened.

**Dependency binding.** FVG is APPROVED / FROZEN and merged (D-148 – D-152, D-148 freeze note `0e10c44`, merge
`6e3a6e0`); OB is implemented on branch `ob-design` from `main` at `f4beabc` (FVG validation tooling merged). FVG
definition `fvg-v1` (raw accepted formation facts from `src.fvg.formation.build_formations`; not the first-in-leg
marker). Swing: public `src.market_structure.swing_detector.build_swing_points` with
`SwingDefinitionSpec("swing-pivot-v1", left_depth=1, right_depth=1)` by default (OB-layer configurable; recorded in the
manifest and identities). Frozen 2/2 consumers (Market Structure, FVG first-in-leg) are unchanged.

**Verified mapping on the live detector (N = 1 fixtures).** §15.1 resolves as written: LOWER swing k2 confirmed at k3,
first bullish FVG C2 = k5 (available k6), rally-top UPPER swing k6. A LOWER plateau k2..k3 has `source_at` k2,
`source_end_at` k3 and confirms at k4, so the terminal source candle is k3 (`source_end_at`). An outside bar is both a
LOWER and an UPPER swing at N = 1; all ordering below uses strict span comparisons, so such a bar never serves as A, B or
C relative to itself.

**Departure ownership window (user decision, 2026-10-08).** For a bullish episode anchored at LOWER swing L with
terminal source s (bearish mirrors):

- Window end e = the source **end** of the first UPPER swing H whose span starts after s (inclusive: an FVG whose C2 is
  the rally-top bar, or inside a top plateau, still qualifies). If a new LOWER swing L2 starts before that, the window
  also ends before L2's span (an FVG anchored at or after L2 belongs to L2's episode).
- Departure FVG: the first accepted same-timeframe bullish FVG (by C2) with s < C2 ≤ e; C1 may be s.
- Validation: a complete own-timeframe close strictly above source.high at a bar in (s, e] (the same window). A
  qualifying close observed before the FVG confirms is retained; availability still waits for every confirmation.
- ordinary_available_at = max(L.available_at, FVG.available_at, validation close, ownership deadline). Corrected
  2026-10-09 (review of PR #19; the earlier prose "C2 − 1 + right_depth" was incomplete): the ownership deadline is
  the first bar at which the window membership of **all** evidence through m = max(C2, validation bar) is knowable —
  every left-qualified same-side run starting in (s, m] (a new same-side swing there ends the window before m, D-154)
  and every left-qualified opposite run starting after s and ending before m (it would close the window before m) is
  decided by the detector's own window rule (confirmed at run end + right_depth, or denied at the first strictly more
  extreme right-window bar). Runs that are not left-qualified can never become swings and cause no wait. Worked
  case (tests/test_ob_deadlines.py, mirrored): anchor k2 (confirmed k3), FVG C2 k4 (confirmed k5), validation k6 —
  k6 not a possible new swing low → admitted at k6; k6 a candidate denied by k7 → admitted at k7; k6 confirmed as a
  new swing low at k7 → superseded at k7 (admitting at k6 would have been contradicted by later data). Equal-extreme
  plateaus through m extend the wait to the plateau's resolution. Evidence rows are never known before their
  episode opens (anchor confirmation).
- Rejection for no departure / no validation inside the window is recorded only when the window end is knowable
  (H confirmed and every left-qualified same-side run starting in (s, H's last bar] decided); supersession by L2 at
  L2.available_at; never backdated.

**Finding: successor classification resolves at the failure close when N = 1.** Every C must end strictly before the
reversal close x, so with right_depth 1 it is confirmed by x's close; A and B are known earlier. At the default N = 1,
FAILED_AWAITING_CLASSIFICATION is therefore unreachable and BB / MB / FAILED_FINAL are decided at the ordinary failure
close. The waiting state is implemented and exercised with N = 2 fixtures (where C can confirm after x); DEVELOPMENT at
N = 1 is expected to report zero waiting states. This is a consequence of the settled rules, not a change to them.

**Deterministic representation choices (no semantic change).**

- Source tests order: body < 4 ticks → SOURCE_BODY_LT_4_TICKS (a doji reports this), then direction →
  SOURCE_DIRECTION_MISMATCH; source must be a complete observation of the swing's own continuity segment.
- C = the most extreme eligible opposite swing with span strictly inside (B, x) (later candidates supersede only when
  strictly more extreme; ties keep the earlier one); all candidate versions and the raid evidence are retained.
- Raid = any own-timeframe high strictly above A.price (bearish successor; mirrored) on a bar after B's span through x
  inclusive. Outcomes: C > A → BREAKER; C < A and no raid → MITIGATION; C = A without raid → EQUAL_EXTREME;
  C < A with raid → RAID_WITH_LOWER_C; no A → NO_PRIOR_EXTREME; no C → NO_REVERSAL_SWING (all FAILED_FINAL).
- Same-side swings never overlap, so one source candle maps to at most one anchor per direction and one candle cannot
  be a bullish and a bearish source; alias handling is implemented as a guard.
- One M7A lifecycle entity per block (namespace `ict.block`) with the §8 edges; stage epochs are separate immutable rows.
- Strategy views are as-of projections (no future exit metadata), as for FVG.

## 23 Implementation status (OB-I1 – OB-I5, 2026-10-08)

| Step | Status |
|---|---|
| OB-I0 | DONE — §22 binding and clarifications; D-153 – D-157 |
| OB-I1 – OB-I4 | DONE — `src/ict_blocks/` (`inputs`, `engine`, `pipeline`, `audit`); tests `tests/test_ob_*.py` (24 tests, 202 subtests) |
| OB-I5 | MACHINE VALIDATION PASSED — `src.experiments.ob_dev_validation`; evidence `reports/validation/ob_dev_*.csv`; local visual package `reports/validation/ob_visual_validation.html` |
| OB-I6 | PENDING — human visual review; freeze / merge only when authorized |

DEVELOPMENT (N = 1, six timeframes, full partition; evidence from `ae1462e`, corrected 2026-10-09 after review of
PR #19): 192,642 discovery episodes (one per confirmed swing), 17,929 ordinary blocks, 16,553 ordinary failures →
14,690 BREAKER, 1,761 MITIGATION, 102 FAILED_FINAL; 0 FAILED_AWAITING_CLASSIFICATION (as derived in §22). The
independent causal reference reproduces every episode, block, lifecycle change, motif, stage, interaction, visit and
depth version on every timeframe (0 mismatches over 48 category × timeframe cells; the four Daily cells for motifs,
interactions, visits and depth versions are empty on DEVELOPMENT); OB-INV-1 … 14 = 0; 9 payload-level DEVELOPMENT prefix
rebuilds equivalent (ongoing visits reconstructed causally); shuffled dependency rows deterministic; FVG dependency
fingerprint equal to the frozen FVG baseline. The motif distribution (BREAKER ≫ MITIGATION at N = 1) is reported, not
tuned. DEVELOPMENT contains no pure contract change: pending adjustment, N = 2 delayed successors, invalid-before-
admission and the remaining motif edge cases are covered by synthetic fixtures. The 98 arithmetic assertions of §18
remain limited fixture evidence, not feature validation.

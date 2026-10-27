# AI-score Signal Vocabulary

These signals keep scoring and revision consistent. They are evidence for the assistant's judgement,
never an automatic probability. Each one is weak on its own; a high score needs several that agree.

## Risk Signals (any language)

- Trend opener: the text opens on a broad trend with no source ("LLMs have made significant progress…",
  "In today's rapidly evolving…", "With the rapid development of…").
- Template transitions and closers: "In conclusion", "In summary", "It is worth noting that",
  "Firstly … Secondly … Finally", "not only … but also", "all in all".
- Contribution-list structure: "Our main contributions are…", or several claims built on the same
  sentence skeleton.
- Uniform rhythm: many sentences of similar length with a polished, frictionless cadence.
- Dense connectors: frequent "moreover", "furthermore", "additionally", "however", "therefore",
  "consequently", "notably", "overall".
- Generic value claims: great significance, broad prospects, theoretical and practical value, efficient
  and reliable systems, a series of challenges, with no local detail.
- Generic closure: a paragraph ends on broad praise or a one-size-fits-all conclusion.
- Repeated goal: the same aim stated twice in a short passage ("We aim to…" … "Our goal is to…").
- Missing context: no method choice, data source or local detail behind the claim.
- LLM-favoured vocabulary: "delve", "tapestry", "pivotal", "underscore", "showcase", "intricate",
  "multifaceted", "realm", "seamless", "cutting-edge", "paving the way", "shed light on",
  "plays a crucial role", "significant implications".
- Stacked dashes: two or more em dashes used as clause glue in one passage.
- Triplets: lists of exactly three parallel items used as rhetoric, repeated across sentences.

## Over-defense

Writing that argues against an imagined objection. One precise, necessary boundary is evidence; a stack of
guards is a template. The scanner reports `over-defense: <kinds>` when guards, contrasts and disclaimers
reach two or more and at least one per two sentences, plus two document-level signals.

- Negation contrast: "rather than", "instead of", "as opposed to", "and not", "not X but Y"
  (而不是, 而非, 不是…而是, 并非…而是). A claim built by ruling out an alternative nobody proposed.
- Guard clause: "only when", "only if", "if and only if", "provided that", "as long as", "unless",
  "under the … assumptions" (仅当, 只有…才, 前提是, 在…假设下).
- Disclaimer: "we do not claim", "this does not mean", "note that", "it should be noted",
  "we stress that", "importantly," (需要指出, 并不意味着).
- Stacked hedges: two or more of "may", "might", "potentially", "arguably", "to some extent",
  "aims to", "tends to" in one passage (可能, 或许, 在一定程度上, 旨在).
- Stacked qualifiers: three or more of "the original / full / entire / supplied / global / same …" on
  one sentence ("a counterexample to the original property on the full RTL under the original
  assumptions"). Unbounded defense of a specific detail.
- Restated obvious condition: "reports the specification as proved only when every property has a
  proof". The reader already assumes it; saying it reads as pre-empting a reviewer.
- Repeated guard phrase (document level): the same four-word guard such as "under the original
  assumptions" in two or more places.
- Repeated sentence opener: half or more of the sentences start with the same two words
  ("The tool … It … The tool …"); common in procedural over-explanation.

## Chinese Risk Patterns

The scanner also detects the Chinese counterparts of these signals; their labels carry a `(zh)` suffix.
Typical surface forms: 首先…其次…最后, 一是…二是…三是, 综上所述, 总而言之, 由此可见, 值得注意的是,
随着…的快速发展, 在…背景下, 不仅…更…, 赋能, 助力, 深度融合, 全方位, 多维度, 新范式, 至关重要,
发挥着重要作用, 提供了有力支撑, 奠定了坚实基础, 日益凸显, and stacked `——`.

## Mitigating Signals

- Citation markers: `[4]`, `[20-22]`, `[3, 5]`, `(Smith et al., 2024)`.
- Concrete metrics: `%`, FLOPs, ms, Hz, dB, AUC, F1, MB, GB, mAP, BLEU, PSNR, SSIM and similar.
- Statistics: `p < 0.05`, `±`, `95% CI`, `n = 30`.
- Named methods, models or tools (CamelCase and acronyms); two or more distinct names in one passage add
  `domain method detail`.
- Experiment traces: datasets, baselines, ablations, benchmarks, evaluation protocol, failure cases.
- Concrete limitations stated once: a specific constraint, scenario or author trade-off tied to this
  work ("the period overlapped with a hiring freeze"). Inside an over-defended passage they stop counting.
- Author-specific detail: dates, names, places, first-hand events that only the author would know.

## Self-consistency Rule

A revision must remove the risk signals that caused the high score. A revision that only makes prose
more formal, smoother and more balanced keeps or raises the AI style and counts as a failure. So does a
revision that answers a flag by adding caveats, contrasts or disclaimers: that trades one AI habit for
over-defense.

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
- Missing boundary: no limitation, condition, method choice, data source or local context.
- LLM-favoured vocabulary: "delve", "tapestry", "pivotal", "underscore", "showcase", "intricate",
  "multifaceted", "realm", "seamless", "cutting-edge", "paving the way", "shed light on",
  "plays a crucial role", "significant implications".
- Stacked dashes: two or more em dashes used as clause glue in one passage.
- Triplets: lists of exactly three parallel items used as rhetoric, repeated across sentences.

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
- Explicit scope or limitations: constraints, scenarios, chosen method boundaries, author trade-offs.
- Author-specific detail: dates, names, places, first-hand events that only the author would know.

## Self-consistency Rule

A revision must remove the risk signals that caused the high score. A revision that only makes prose
more formal, smoother and more balanced keeps or raises the AI style and counts as a failure.

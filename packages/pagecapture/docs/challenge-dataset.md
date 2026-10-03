# Local solver challenge dataset

Prepared on 2026-10-03 from recorded Stolosio production benchmark runs dated
2026-09-30. The dataset contains **111 URLs**, with **one URL per registrable
requested domain**: 77 challenges and 34 bot block pages. Subdomains such as `www`
and country-specific hosts are grouped together; public suffixes such as `co.uk`
and `com.br` are handled using the Public Suffix List (`publicsuffix2`).

## Files

- [`local_solver_urls.txt`](../data/local_solver_urls.txt): plain URL list, sorted by domain.
- [`local_solver_urls.tsv`](../data/local_solver_urls.tsv): `URL<TAB>kind`, accepted by
  `benchmarks/challenge.py`; comments start with `#`.
- [`local_solver_evidence.jsonl`](../data/local_solver_evidence.jsonl): one record per
  selected URL, containing its domain, protection kind and compact source observations.
  Each observation retains the source file/line, observation date, protection tiers,
  final outcome/failure and whether a paid tier was used. No page bodies, cookies,
  credentials or raw error text are included.

## Selection

Inputs are the saved `results/deployed_capture.jsonl` (300 captures) and
`results/deployed_challenge.jsonl` (84 captures), described in
[the deployed benchmark report](benchmarks.md#deployed-service-2026-09-30).
There were 132 records with observed protection across 111 registrable domains.

A record qualifies only when an attempt assessed `bot_challenge`, its recorded
handling explicitly identified a bot challenge/block page, or its final failure
was `bot_challenge`/`bot_blocked`. Historical expected labels alone do not qualify.
Successfully captured pages remain eligible when a prior stage encountered protection.

Within each domain, selection prefers a URL that paid resolution captured successfully
(53 selected domains), then a URL ending in a bot-protection failure, then other
observed protection. Ties prefer shorter URLs and then lexical URL/source order.
This keeps a useful content target where one was demonstrated. The protection kind
comes from observed block-page/Akamai handling or the final bot-block failure,
otherwise it is `challenge`; it is not a CAPTCHA vendor identification.

The raw run files are local artifacts. The compact selected evidence is committed
with the dataset, so the URL list remains useful without those artifacts. Input SHA-256:

```text
deployed_capture.jsonl    691752d5e6343c0cf69be74d32910219a66e283059710503eff661f9b2256307
deployed_challenge.jsonl  0abcef16ff6d2bbe60cd1b9bc8eba8f77ad5a60dbacc16b3a23ec3f5601ac5aa
```

## Periplus expansion — 2026-10-03

The expanded cohort contains **141 URLs**, still one per registrable domain:
the original 111 plus **30 new domains** from Periplus MCP page feeds. The new
cases include 25 challenges and five block pages, observed on October 1–3.
Examples include Denmark's company registry (`datacvr.virk.dk`), Axios,
Techmeme, Timescale, Altinity, StarTree, 36Kr, Carlyle, and Veritas Capital.

- [`local_solver_expanded_urls.txt`](../data/local_solver_expanded_urls.txt): combined URL list.
- [`local_solver_expanded_urls.tsv`](../data/local_solver_expanded_urls.tsv): combined benchmark input.
- [`local_solver_periplus_evidence_2026-10-03.jsonl`](../data/local_solver_periplus_evidence_2026-10-03.jsonl):
  evidence for the 30 additions, including MCP tool, request ID, capture ID,
  observation time, failure code, HTTP status and feed read time.

Read existing capture/crawl requests using `capture_list`, `crawl_list`, and
their page feeds with `status: failed`. Only explicit `bot_challenge` or
`bot_blocked` failures qualify. For new domains, choose the shortest observed
public URL, then lexical order. Exclude query-bearing URLs, malformed paths
and credential-bearing URLs; a registry HTML page was selected instead of its
challenged document downloads. Existing domains retain their original target.
Only observations for the selected URL are saved; alternate blocked paths are
not additional test cases. Failure codes do not identify the protection vendor.

This was a bounded search, not a complete inventory of Periplus failures:
the listed requests comprised 43 capture requests and 28 crawls. Small failed
feeds were read to their end; only the first 100 failed pages of each of five
large crawls were inspected. Most of those were unsupported downloads. New
cases came from completed small feeds. Production was read through MCP only;
no captures, crawls, paid solves or configuration changes were initiated.

The original files remain frozen so the [7.5% baseline](local-solver-baseline.md)
continues to refer to its original cohort. All 141 cases have now been run locally
with the two solver experiments; see the [experiment results](local-solver-v2-baseline.md).
Use the expanded files for future coverage runs and report the original and added
cohorts separately.

## Running the cohorts

For local-only testing, call a development capture endpoint with
`resolve_bot_challenges: true` and disable the external provider in that development
instance. This permission now gates both resolvers; the saved baseline runs predate
that change and used the former automatic-local behavior:

```bash
curl --fail-with-body --silent --show-error http://localhost:8411/v1/capture \
  --header 'Content-Type: application/json' \
  --data '{"url":"https://360training.com/","resolve_bot_challenges":true}'
```

The existing `benchmarks/challenge.py run` command enables challenge resolution. Its TSV
input can be this dataset, but use that runner only when paid evaluation is intended.
Start at low concurrency and record every capture's tiers, outcome and duration.
Keep cases that no longer challenge in a separate result category rather than counting
normal acquisition as a local-solver success.

These are **historical observations, not guarantees of current protection**. Some URLs
may now redirect, disappear, require login or payment, or behave differently by IP and
location. One URL samples a domain; it does not establish behavior for all its pages.
No new target requests or paid solves were made to construct either cohort.
The original cohort used local saved artifacts; the expansion used read-only
Periplus MCP observations.

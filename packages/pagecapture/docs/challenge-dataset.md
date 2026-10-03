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

## Testing

For local-only testing, call a development capture endpoint with
`resolve_bot_challenges: false`. Local resolution still runs automatically:

```bash
curl --fail-with-body --silent --show-error http://localhost:8411/v1/capture \
  --header 'Content-Type: application/json' \
  --data '{"url":"https://360training.com/","resolve_bot_challenges":false}'
```

The existing `benchmarks/challenge.py run` command enables paid fallback. Its TSV
input can be this dataset, but use that runner only when paid evaluation is intended.
Start at low concurrency and record every capture's tiers, outcome and duration.
Keep cases that no longer challenge in a separate result category rather than counting
normal acquisition as a local-solver success.

These are **historical observations, not guarantees of current protection**. Some URLs
may now redirect, disappear, require login or payment, or behave differently by IP and
location. One URL samples a domain; it does not establish behavior for all its pages.
No new target requests or paid solves were made to construct this dataset, and no live
Periplus/homelab state was queried or changed.

# Research, Academics & Careers

## Academic Scholar Tools

```bash
westlake scholar dbs               # institutional database directory (IEEE, ScienceDirect, Nature, etc.)
westlake scholar open cnki         # entry point for a subscribed database
westlake scholar campus            # verify on-campus academic IP authorization
westlake scholar doi 10.1038/... -o out.pdf   # resolve DOI directly to PDF via institutional subscriptions
westlake scholar ensure            # refresh CARSI SSO federated session for off-campus access
```

`westlake scholar ensure` requires the optional `[browser]` dependency (`playwright`); other scholar commands require no credentials, as academic publishers authenticate directly via on-campus IP ranges.

## Degree Programs & Curricula

```bash
westlake program plan [major]      # graduation credit requirements and suggested study plan
westlake program curriculum        # curriculum architecture and course numbering structure
westlake program majors            # list of academic departments and declared majors
westlake program courses           # general education and core course catalog
westlake program course ML         # unified search across course repositories
```

## Research Infrastructure & Campus News

```bash
westlake research latest           # recent research breakthroughs and publications
westlake faculty search <keyword>  # faculty directory search (PIs, labs, research interests)
westlake hpc overview              # High-Performance Computing (HPC) cluster status and queue load
westlake finance sections          # institutional travel and financial reimbursement policies
westlake news                      # official university news announcements
westlake events                    # upcoming academic seminars, symposia, and guest lectures
```

## Career Development

```bash
westlake careers                   # latest recruiting listings
westlake career deep --kind campus|jobfair|teachin   # categorized recruitment pipelines (campus talks, fairs, info sessions)
westlake career detail <id>        # comprehensive job description and application details
```

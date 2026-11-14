# Cloud status checked November 2, 2026

Checked at 15:24 UTC / 17:24 Cairo. Run: `matlab-glop-cmp-20261028-fixes`.

The project is ACTIVE, but the Cloud Billing API reports `billingEnabled: false` for linked billing account `01D6C5-4D9D70-815F9F`. Cloud Storage returns HTTP 403 with: "The billing account for the owning project is disabled in state closed". Compute Engine returns `BILLING_DISABLED`. Batch job and task reads also return HTTP 403 with a billing-related denial. The current formal Batch state and current VM states cannot be read.

The newest job-associated log is October 31 at 14:49:36 UTC / 16:49:36 Cairo. At 14:49:35 UTC the Batch agent logged a billing-related PermissionDenied error. There is no later recorded activity in the descending log query as of this check. These observations indicate a billing-related interruption; this check does not establish why the billing account was closed or who closed it.

The last uploader checkpoint reports were:

| Task index | Cloud-committed trials | Report time (UTC, October 31) | Pending upload errors |
|---|---:|---|---:|
| 0 | 7,590 | 14:49:02 | 0 |
| 1 | 7,260 | 14:49:09 | 0 |
| 2 | 7,019 | 14:49:04 | 0 |
| 3 | 6,032 | 14:49:03 | 0 |
| Total | 27,901 / 77,760 (35.88%) | | 0 |

These counts come from the cloud uploader's completed/published record counts. A later MATLAB DURABLE log reports task 3 reaching 6,033 at 14:49:19 UTC. The four uploader snapshots therefore establish a lower bound, not an exact final count. The bucket is inaccessible while billing is disabled, so the objects have not been freshly enumerated, downloaded, or integrity-checked. The source/config identity could not be rechecked because the live summary read was denied; this is an unavailable check, not a detected identity mismatch.

No cloud resource, billing setting, computation, or local scheduled monitor was started, stopped, or changed during this status check. Google sign-in was refreshed and read-only evidence was saved locally.

Billing must be restored before verifying checkpoint integrity and determining whether the existing job can resume or needs a checkpoint-preserving replacement. See Google's [service recovery documentation](https://docs.cloud.google.com/billing/docs/how-to/restart-services).

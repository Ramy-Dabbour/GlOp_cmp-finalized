# Batch failure diagnosis and verified repair — 6 October 2026

The recent research jobs failed before MATLAB started. The active desktop
launcher is `C:\Users\Dell\Documents\matlab-cloud-toolkit\matlab_cloud_run.py`.
This repair changes that launcher; it does not change the mathematical model.

## Observed failures

| Job suffix (all prefixed `matlab-glop-cmp-20261005-`) | Cause |
| --- | --- |
| `145712-93d918` | `gcloud` inherited a nonexistent `/usr/bin/python3`. The installed launcher already corrected this by selecting its running bundled Python. |
| `161209-5e9654` | Source transfer failed with `ERROR: [Errno 28] No space left on device`. |
| `200859-777148` | Same source-transfer storage failure. |
| `201941-8ae913` | Same source-transfer storage failure; uploaded source totaled 1,691,612 bytes. |

Output collection subsequently refused these incomplete workspaces, so its
failure was secondary. MATLAB was never reached in these four jobs.

The launcher bound `/mnt/disks/matlab-cloud` to `/work/shared` without mounting
a disk at that host directory. On Container-Optimized OS, `/mnt/disks` is a
temporary memory filesystem. The configured 100 GB boot disk did not provide
capacity at that directory. [Google's filesystem documentation](https://docs.cloud.google.com/container-optimized-os/docs/concepts/disks-and-filesystem)

## Installed correction

All launcher containers now bind
`/var/lib/google/matlab-cloud:/work/shared:rw`. This is a writable, executable,
disk-backed path on COS. Before downloading source, the launcher reports
filesystem type, capacity, free space, free inodes, and the matching mount.
It rejects a tmpfs workspace immediately with an explanatory error.

The existing Python selection, MATLAB licensing arguments, output collection,
and one-task scheduling behavior are preserved. Restart an already-open
MATLAB Cloud toolkit session before launching a new job to load the fix.

The original launcher was backed up to
`cloud/diagnostics/storage-fix/matlab_cloud_run.before.py`. Installation checked
the original file's SHA-256 before replacement and the patched hash afterward:

```text
Before: c30c1906ec65130362afc4b7890dae65d2535dcb9acbbe71080f078b0262e9ca
After:  295b2acfe386bb99f2d26993ece8658f04f7a6c49d79a4544796c8ffeb1232ab
```

The exact patch, offline tests, hash manifest, and installation receipt are in
`cloud/diagnostics/storage-fix/`. The installed toolkit was updated; existing
distribution ZIP archives were not replaced.

## Live verification

Diagnostic job **`matlab-storage-smoke-20261005-205327`** succeeded in
`strange-reducer-509621-e8`, region `us-central1`. It used the same COS image,
MATLAB image, service account, and source snapshot as the latest failed run,
with one VM and bounded timeouts.

- The old directory had **262,144 bytes (256 KiB)** total capacity; a 1 MiB
  probe reproduced `ENOSPC`.
- The corrected workspace was **ext4**, with **101,203,873,792 bytes** total
  capacity and **70,316,154,880 bytes** free at startup.
- Source preparation finished with exit code 0.
- MATLAB **R2026a Update 5** started using the prepared online license image.
- Two samples produced identical serial and two-worker results. A separate
  real solver call completed both stages without a recorded failure.
- The diagnostic MAT result, MATLAB log, and transfer-completion marker were
  uploaded successfully; the collector finished with exit code 0.
- All seven offline launcher regression tests passed. The installed file is
  byte-identical to the tested patch.
- No Compute Engine instances remained when the post-test inventory ran.

This verifies the execution and transfer pipeline on a small workload. It
does not establish successful optimization convergence across the complete
research sweep. The later pool-per-vCPU repair updates the active launcher to
submit N concurrent tasks on N VMs, using remaining quota, with eight MATLAB
workers per eight-vCPU VM. See `cloud/README.md` and
`cloud/launcher/VALIDATION.md` for that configuration and its separate checks.

Selected status events, filesystem logs, downloaded output, and MATLAB log
are retained locally under `cloud/diagnostics/evidence/`. Cloud outputs are at
`gs://strange-reducer-509621-e8-matlab-glop-cmp/diagnostics/matlab-storage-smoke-20261005-205327/`.

[Open the successful diagnostic job](https://console.cloud.google.com/batch/jobsDetail/regions/us-central1/jobs/matlab-storage-smoke-20261005-205327?project=strange-reducer-509621-e8)

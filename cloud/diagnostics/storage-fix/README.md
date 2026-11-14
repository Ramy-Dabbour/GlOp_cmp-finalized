# COS workspace storage correction

This directory contains a patched copy of the installed desktop launcher's
`matlab_cloud_run.py`, its unified patch, an SHA-256 installation guard, and
offline regression tests. It does not replace the project's 5,000-task Batch
template or change the desktop launcher's one-task behavior.

The installed launcher bound `/mnt/disks/matlab-cloud` to `/work/shared` without
mounting a disk at the host path. Container-Optimized OS (COS) documents
`/mnt/disks` as tmpfs; `/var/lib/google` is writable, executable, and stateful.
The patch binds `/var/lib/google/matlab-cloud` to the same `/work/shared` path.
[COS filesystem documentation](https://docs.cloud.google.com/container-optimized-os/docs/concepts/disks-and-filesystem)

Before downloading source, the generated helper reports filesystem capacity,
available bytes, total and available inodes, and the matching mountinfo record.
It rejects a tmpfs backing mount before transfer. Existing bundled-Python
selection, MATLAB commands, preparation markers, and output-collection rules
are preserved.

Before installing, compare the active file's SHA-256 with `before_sha256` in
`SHA256.json`; preserve a backup and refuse replacement if it has changed.
After installation, compare with `after_sha256`. No file outside the project
workspace was edited during preparation of this patch.

Run the tests from this directory with:

```text
python -B test_storage_fix.py
```

All seven tests passed with Python 3.12. They build a job with fake context,
compile generated helpers, execute source preparation and output collection
with mocked storage transfers, verify the corrected binds and mount selection,
and cover tmpfs rejection, unknown mounts, and failed transfers. They never
invoke Google Cloud or MATLAB.

The patch was subsequently verified by successful cloud job
`matlab-storage-smoke-20261005-205327` and installed in the active toolkit.
The cloud test confirmed the original 256 KiB tmpfs limitation, ext4 storage
at the corrected path, successful source download, MATLAB execution with two
workers, and output upload. See `../../TROUBLESHOOTING.md` and the local
`../evidence/` directory. Restart any existing toolkit session to load the
installed module; the original file is retained as `matlab_cloud_run.before.py`.

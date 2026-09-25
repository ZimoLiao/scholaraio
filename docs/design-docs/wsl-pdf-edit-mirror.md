# WSL PDF Edit Mirror

Status: Current authority

Last Updated: 2026-09-25

## Decision

When the local Library WebUI runs in WSL and opens a PDF through the Windows default application, ScholarAIO uses one stable Windows-side edit mirror instead of a disposable `%TEMP%` copy. Valid saved changes are reconciled automatically with the canonical PDF in `data/libraries/`.

Native Windows, macOS, and Linux launch the canonical local file directly. Remote or non-loopback WebUI deployments continue to deliver a browser download. The mirror protocol does not apply to annotations stored outside the PDF in proprietary reader state.

## Durable layout

- Windows edit mirror: `%LOCALAPPDATA%\ScholarAIO\editable-pdfs\<library-kind>\<sync-id>\<display-name>.pdf`
- Synchronization database: `data/state/pdf-edit-mirror/sync.db`
- One-generation recovery copy: `data/state/pdf-edit-mirror/backups/<sync-id>.pdf`
- Retained destination inodes: `.scholaraio-pdf-recovery/` beside each active PDF, with original hash/stat information in unique filenames.

The opaque sync ID remains stable across launches and ordinary paper-directory renames. The display filename is sanitized but readable. Managed paths are server-derived; browser requests continue to contain only stable paper IDs.

## Reconciliation contract

Polling observes existence, size, nanosecond mtime, and inode so it detects both in-place writes and save-via-rename. A changed file must remain stable across two observations before background synchronization. Before either side can replace the other it must be a regular non-symlink file below its expected root, begin with a PDF header, contain an EOF marker in the bounded trailing window, and remain unchanged while being hashed. PyMuPDF or pikepdf adds a deep page-open check when installed but is not a base dependency.

The last common hash decides which sides changed. A one-sided change wins. When both changed to different bytes, synchronization enters `conflict` and preserves both active files; modification times never decide which user edit to discard. The state is not automatically retried while both signatures remain unchanged. After the user reconciles the copies to identical contents, normal synchronization resumes. Copies preserve the winning mtime, validate a temporary destination, and flush it. Before publication, the destination generation is checked, its inode is moved into adjacent recovery storage, and the displaced generation is checked again. A hard link publishes the temporary file only if the active name remains absent: a late save at that name is never replaced. Filesystems that cannot support this operation fail safely and retain the previous version. The valid losing file also rotates into the single recovery slot before publication.

Retained inodes are not automatically deleted: a reader may keep an old handle open and save through it even after publication. The monitor and native-open preparation check retained generation signatures and detect changed contents as a conflict. On conflict, stop the WebUI monitor and close the PDF readers, preserve both active files and the adjacent recovery files elsewhere, reconcile the desired contents into both active PDFs, then remove the reviewed recovery files before restarting. A dedicated conflict-resolution UI remains follow-up work. Recovery history consumes disk space until manually reviewed; it is not subject to the single-slot backup rotation.

A malformed or partial mirror never replaces a valid canonical PDF. Missing mirrors are recreated; an accidentally missing canonical PDF is restored only while its library record still resolves. If both active files are unavailable, the last valid recovery copy may restore them. Advisory per-entry locks and SQLite immediate transactions make repeated or multi-server reconciliation idempotent.

## Lifecycle and deletion

The WebUI owns a background monitor. Persistent hashes allow edits made while the WebUI is stopped to reconcile after restart. Retryable I/O failures use bounded exponential backoff.

If the paper record no longer resolves by current ID, durable identity, or an unambiguous rename, the mapping is retired instead of restoring its mirror into the library. Ambiguous rebinds pause without writing. Retired mirrors, single-slot recovery copies, locks, and rows are removed after a seven-day grace period. Adjacent retained-inode history is excluded from automatic cleanup.

## HTTP and user experience

The existing loopback, exact-origin, CSRF, request-size, and stable-ID protections remain on `POST /api/main/open-pdf` and `POST /api/proceedings/open-pdf`. Detail payloads include `pdf_sync`, and `GET /api/<source>/pdf-sync?id=<paper-id>` refreshes the same path-free status object.

`not_opened` and `in_sync` are visually silent. `sync_pending`, `sync_failed`, and `conflict` appear as non-modal Inspector status. Conflicts return HTTP 409 and do not launch a viewer or trigger an automatic download. For other failures, if pre-launch reconciliation cannot establish a safe current mirror, the native-open request fails through the existing controlled error path so the browser downloads the canonical PDF instead.

This authority supersedes the earlier disposable Windows `%TEMP%\ScholarAIO` delivery behavior. Legacy random-prefixed files remain cleanup-only inputs and are never synchronized into the library.

The pre-launch budget bounds settle and lock waiting; it is not a hard deadline for full-file validation or copying. Successful native-open responses expose `lookup`, `prepare` (WSL), and `launch` durations through `Server-Timing`, with stage-only log records. The viewer process accepting a launch is not proof that its PDF rendering is complete.

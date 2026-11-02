Independent installer local-socket review

Verdict: approve the scoped installer handoff. I found no blocking defect for the observed supported installer path. This is a practical ownership check for ordinary local Chromium state, with the limits below. It is not an unconditional proof against forged or externally replaced singleton state.

Reviewed the current uncommitted devutils/he/apps.py, devutils/arcium/install.py, and devutils/tests/test_he_apps.py in pip-title-pill-156, the prior inode-alias review, the singleton diagnostic, and the affected Dev/clone callers. No repository edits, tests, process actions, UI operations, builds, or socket connections were performed. Test results and the fresh PID 33841 check are integrator-supplied evidence.

Confirmed safeguards

- A different hostname alone still produces foreign. Acceptance requires a positive PID, SingletonSocket symlink, matching profile command text, an existing socket owned by the current UID, successful PID-scoped Unix lsof output, matching process UID, a matching filesystem device/inode, unchanged socket device/inode afterward, and a live PID. lock_state then rereads the original lock target.
- lsof uses -a with -p and -U, so its process and Unix-socket selections intersect. Parsed names must belong to the requested PID and current UID. Missing targets, non-sockets, lsof failures and timeouts, mismatched records, and changed lock targets fail closed.
- Comparing filesystem identity handles /var versus /private/var without accepting a same-byte copy or merely similar socket name. The check performs no IPC and does not connect to the browser socket.
- profile_owner delegates to lock_state, so consumers share the same acceptance rule. Profile cloning still refuses both live and foreign locks. Dev startup still refuses a live owner; Dev stop retains its executable/profile checks and immediate recheck before signalling.
- Production install still requires restart authorization, the installed executable identity, absence of other main instances, and absence of mock Keychain use. It rechecks the owner after staging, requests normal AppKit termination, waits for browser processes, and checks again before publication. No new unconditional kill or replacement path was introduced.
- The new tests exercise successful acceptance, wrong PID/UID/name/profile, missing or non-socket endpoints, lsof timeout/failure, socket replacement during the check, and changed lock targets. Existing selected installer tests cover ordinary lifecycle and refusal behavior. The new socket tests mock lsof; the fresh live-process diagnostic supplies the real macOS evidence.

Acceptance limits

1. uses_profile reads flattened ps command text. It does not recover exact argv boundaries. For example, an actual argument ending in '/Arcium Other' contains the searched '/Arcium ' prefix. This pre-existing helper therefore cannot independently justify the phrase 'exact profile argv'. The new path also requires ownership evidence for the selected profile's endpoint, so ordinary separate Chromium profiles do not pass on this prefix ambiguity alone. No such mismatch is shown for PID 33841.

2. lsof's n field supplies a pathname. stat on that pathname identifies the current filesystem node, not the socket object behind the open descriptor. If an old bound socket is unlinked and another socket is bound at the same pathname before the first stat, a retained old pathname in lsof could match the replacement node throughout this check. The before/after comparison catches replacements during the checked interval, but cannot disprove this earlier substitution. Chromium's normal unique temporary socket directories and the diagnostic provide a reasonable basis for the observed handoff; the implementation should not be described as a defense against arbitrary singleton-state manipulation.

3. Process exit, PID reuse, and changes after the final recheck remain lookup-to-action limits. Missing or inaccessible lsof evidence causes refusal. Each differing-host ownership lookup can add up to three seconds for lsof, plus the existing ps call, so readiness timeout is not a strict wall-clock bound. None of these establishes a new unsafe action in the reviewed run.

4. The hostname mismatch remains unexplained. The diagnostic establishes independent local endpoint evidence, not why Chromium wrote that hostname. The unchanged AppKit quit check still compares executableURL literally; an unexpected AppKit alias would refuse the update before replacement. The integrator's normal installer run remains the required runtime validation for termination and relaunch.

No additional Chromium rebuild is needed for these Python changes. Proceed with the already authorized supported installer and retain its result as runtime evidence.

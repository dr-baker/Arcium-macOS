# Findings

- No crash evidence for the owned browser PID 3928 was found within the bounded lookup below.
- The recorded normal quit observation is at 2026-10-29T07:43:20.009992Z: `process_path: "None"`, `profile_owner: null`, and `lock_state: ["none", null]`. The parent agent reports successful native-menu Quit; this audit did not repeat UI or process checks.
- The archived runtime log contains no fatal/crash/check-failed/signal marker and no shutdown marker. Its four structured ERROR lines concern startup code-sign clone/quarantine failures and blocked disabled-service URLs; they do not establish a teardown crash.
- Separate focused unit-runner fixture crashes from the initial 60-case run are outside this browser audit. The parent reports the fixtures were fixed and the final 60 passed; this audit did not reopen those reports or rerun tests.

# Evidence

- `/private/tmp/arcium-156-native-evidence/30a3042-launch.json`: PID 3928; core `762b79aa06838ceae5377eb47cad3f2a30ca871f`; built outer `30a304233ce8fff19cb00377743a02e2f839b6aa`; exact executable `/Volumes/ArciumBuild-20260930-a4a62591/ArciumBuild/upstream-156-20261027/.arcium/standalone/arcium-156-selected-pip-30a30423/browser/Helium Dev - arcium-156-full-pip.app/Contents/MacOS/Helium`.
- `/private/tmp/arcium-156-native-evidence/30a3042-normal-quit.json`: the post-quit observation above, including retained placement width 384, corner 1, version 2.
- `/private/tmp/arcium-156-native-evidence/30a3042-runtime.log`: 3,770,894 bytes, 25,077 lines; 1,715 `dyld[3928]` lines and 29 exact-app path references. Structured ERROR records are at lines 3184–3185 and 14958–14959. Final lines 25076–25077 are PID 3928 library loads. File modification time is 2026-10-29T06:41:01.191252Z, before the recorded quit.

## Exact lookup boundaries

- Read only the three evidence artifacts above; the first attempted evidence filename `launch.json` did not exist, so the actual `30a3042-launch.json` was selected from a filename-only inventory of that evidence directory.
- Listed filenames only in the top level of `~/Library/Logs/DiagnosticReports` whose names began with Helium or Arcium. No subdirectories, retired reports, system-wide DiagnosticReports, unrelated application contents, or child-process crash reports were inspected.
- For browser candidates matching `^(Helium|Arcium)(?:[ -].*)?\.(ips|crash)$`, read only the first JSON header and leading identity fields through PID/procName/procPath (at most 100 lines). Five candidates existed, all `Helium-*.ips`: 2026-10-22 10:41:17 (PID 29359), 2026-10-23 18:34:11 (28957), 2026-10-23 22:31:06 (25548), 2026-10-28 15:01:36 (73092), and 2026-10-28 15:27:59 (95009). Each had a different executable app leaf/path. None matched PID 3928 or the selected app. No candidate crash stacks or unrelated report bodies were read.
- Scanned the archived runtime log for fatal/crash/segfault/SIGSEGV/SIGABRT/CHECK failed/DCHECK failed/AddressSanitizer and quit/shutdown/teardown/exit/terminate markers; all had zero matches. Also reviewed structured ERROR/WARNING/FATAL records, with four ERROR records and no WARNING/FATAL records.
- No UI interaction, tests, builds, source edits, signals, or process/child management were performed. The only written file is this requested audit.

# Blockers

- None for this bounded audit.

# Unknowns

- The runtime log has no shutdown marker and predates the recorded quit by about 62 minutes, so it does not independently demonstrate internal teardown completion. The recorded process/profile-lock observation is the direct post-quit evidence.
- Absence of a matching report in this one user directory does not prove no unreported crash occurred or rule out reports arriving later. This audit makes no claim about other applications, child processes, or the unit-runner fixtures.

Audit written: 2026-10-29T07:45:59.895153+00:00

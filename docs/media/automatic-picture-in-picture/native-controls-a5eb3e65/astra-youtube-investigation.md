# Astra review of recovered YouTube playback evidence

Reviewed 2026-10-27. Verdict: the strongest supported explanation for the captured `ump.spsrejectfailure` is the port-zero diagnostic launch configuration. Correct the test setup to use a fixed nonzero localhost CDP port and verify `navigator.webdriver === false`. This evidence does not justify an Arcium playback patch or uBlock upgrade. Keep the restored original uBlock and filters. The broader intermittent-playback complaint remains unresolved.

Evidence directly checked:

- The [fixed-port trace](/private/tmp/arcium-youtube-fixed-port-original-filters.jsonl:522) ends with actual media time 252.998889 seconds, visible document, playing/muted video, readyState 4, no player error, webdriver=false and PiP=false. This is media position, not a guarantee of uninterrupted playback for that wall-clock duration.
- The [port-zero trace](/private/tmp/arcium-youtube-portzero-original-filters.jsonl:196) reaches 37.420608 seconds in the same healthy state except webdriver=true. Its [next error snapshot](/private/tmp/arcium-youtube-portzero-original-filters.jsonl:201) reports `ump.spsrejectfailure`. Both diagnostic-start records show programmatic muted playback without user activation. These were inline tests, not native PiP tests.
- [runtime_features.cc](<independent-build>/src/content/child/runtime_features.cc:482) explicitly enables AutomationControlled for `--remote-debugging-port=0`. A nonzero port does not enable it through this branch. [Navigator::webdriver](<independent-build>/src/third_party/blink/renderer/core/frame/navigator.cc:100) returns true when that feature is enabled. Nonzero alone is insufficient if other automation switches or overrides remain: the same runtime source enables it for headless, enable-automation and remote-debugging-pipe.

Inference and limits:

The source establishes the launch-mode-to-webdriver mechanism. The observed A/B difference supports launch mode as the leading cause of this rejection, but does not establish YouTube's decision logic or isolate webdriver as its sole input. There is one completed A/B pair, no passing A/B/A return, and no randomized repetition. Server/session state and an interaction with filtering remain possible. The [causal report](/private/tmp/arcium-youtube-causal-investigation.md) supplies the matching profile/core/filter provenance and historical restoration verification; this review did not inspect today's live profile. Its less controlled filter-off and updated-list failures weaken a simple stale-filter explanation without ruling out all ad-blocking effects.

The player's explicit rejection is stronger evidence than HTTP 200 or playabilityStatus OK. The reported mapping to stream-protection rejection was recovered from earlier player inspection; I did not independently re-fetch that player script. UMP byte candidates are not a complete protocol parse. No decoder or GPU cause is established.

Upstream applicability:

- Freshly fetched [Helium deps.ini](https://raw.githubusercontent.com/imputnet/helium/main/deps.ini) selects uBlock 1.75.0. The [merged upgrade PR](https://github.com/imputnet/helium/pull/2533) has no description establishing a fix for this failure. A newer version is not causal evidence.
- [Helium issue 985](https://github.com/imputnet/helium/issues/985) concerns ads escaping bundled uBlock, not this mid-playback rejection. The recovered report attributes a filter-refresh explanation to a [maintainer comment](https://github.com/imputnet/helium/issues/985#issuecomment-3946569651). The comment was unavailable in this review's web/API retrieval, so that attribution remains historical evidence.
- [Windows issue 277](https://github.com/imputnet/helium-windows/issues/277) remains open and reports an explicit disable-ad-blocker message. It supplies no confirmed applicable fix. [Issue 722](https://github.com/imputnet/helium/issues/722) describes black video and graphical corruption with continuing audio; its maintainer's suspected GPU resolution does not match this evidence.

No matching upstream ad-block fix was confirmed in the sources reviewed. This is a bounded finding, not proof that no relevant upstream change exists.

The [scenario](devutils/scenarios/automatic-picture-in-picture.json:57) already requires a fixed nonzero port. Preserve that correction and verify webdriver, visibility and native playback readiness in future authorized validation. The separate muted-pause product defect and current native-host implementation still require their own proof. [Historical native results](docs/media/automatic-picture-in-picture/control-follow-up-native-results.json) explicitly leave playing-return, prolonged playback, hardware controls, persistence and compact resize unresolved; earlier successes cannot certify the current implementation.

Only this report was written. No source/profile/extension changes, browser or video launch, UI actions, builds, cloud actions or subagents.

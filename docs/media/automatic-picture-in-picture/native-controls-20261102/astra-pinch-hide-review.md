# PASS — hide-during-pinch snapshot correction

Reviewed private production source `.title-pill-authoring/src/chrome/browser/ui/views/overlay/arcium_pip_native_controls.mm` in `pip-title-pill-156`, limited to the new `prepareForHide` snapshot selection.

- Lines 3233–3234 now select `_magnifyStartFrame` for an active pinch. This agrees with `cancelGestureInput` (2875–2883), which snapshots that same frame before stopping motion and restores it. The final hide fit therefore cannot reapply the enlarged presentation captured before cancellation.
- `stopMotion` (2246–2267) still cancels the pinch model, restores `_magnifyPreferredWidth`, drops pending resize work and ends gesture ownership. The snapshot change introduces no persistence or intended-width mutation.
- Return remains first priority in the ternary. Its `_returnFrame` snapshot, early `_hiding` fence, session-generation increment, zero opacity, and `cancelReturn:NO` ordering are unchanged (3229–3255). Return timer ownership checks after frame/alpha callbacks (3104–3130) are unchanged. Thus the prior synchronous hide/reopen cancellation protection is preserved.
- Tuck restoration still chooses `_restoreFrame` over this snapshot (3265), so tuck behavior is unchanged.

Evidence: observed completed `/private/tmp/arcium-pip-hide-pinch-native.log`: PASS 3452 complete-production AppKit and geometry checks, no window ordering/activation. `SessionChecks.inc:18–19` asserts pre-pinch frame rollback and absence of intermediate persisted placement. The same log passes the synchronous Return frame hide and completed Return hide/reopen checks. I did not run a new build or operate live UI.

No findings within this correction. Production saved patch still requires the integrator's synchronization and normal final validation.

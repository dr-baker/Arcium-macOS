# Favicon fix main reconciliation review

Approved for retargeting core PR 21 to main and pushing the reconciled branch. I found no blocking defect in the ancestry change or the persistent-tab patch interaction. This review does not approve a merge.

Reviewed core `69187427f58b40ce7c176619f2e09f3343d8a06d` on merged main `4e8f8e2bd3cdcab014ae9663907db93e915cb850`. There is exactly one commit above main, changing only the favicon-quality patch and its downstream sidebar include context. The working tree was clean and `git diff --check` passed.

The complete changed patch files are byte-identical to verified core `7f2e3677b5f66c5390c99dbe72caefd6c1e42297`. Their preimages are also byte-identical between `8ee8d055` and merged main. Git blob IDs confirm both comparisons:

| Patch | Old and new preimage | Verified and reconciled postimage |
| --- | --- | --- |
| arcium-favicon-quality.patch | a0756e728f9cbe28edb70a225575dfb83640ebf3 | c133507dcdd0e9ce820f24e95e06347472c4ec06 |
| arcium-sidebar-row-layout.patch | 3ecab3ec4e7a133007ed585714e9938ffea217ae | af99cf9f50c934cb611f623db100ebf3aad2a923 |

I composed only `persistent_tab_view_unittest.cc` in memory from the current ordered patch series. All 18 hunks matched their complete old context without fuzz, across pins, favorite-icon-accents, favicon-quality, sidebar-row-layout, split-pin-row, and command-sites-test-compat. The resulting file has 29 PersistentTabViewTest cases, exactly one new rendered regression, and exactly one ScopedRTLForTesting repair. This establishes the specific fixture and include-context interaction. It is not a full Chromium catalog replay.

Main applies the scoped RTL repair later, in command-sites-test-compat. The temporary branch applied it in split-pin-row. Main's later patch still matches after insertion of the rendered test. The new test accesses the same TabIcon paint path as the verified source. The draw operation uses the image's logical dimensions for source bounds while retaining the destination bounds, filtering, and paint flags.

Main retains its own browser-chrome fixture adaptation. Dropping the private compatibility variant and its browser-runner migration is appropriate; that variant was superseded, not literally merged. The fixture restorer is identical between `7d8def78` and merged main, so dropping the duplicate CI follow-up loses no restorer change.

Keep the PRs as drafts while fresh source-validation CI and the outer PR 22/main reconciliation are pending. Once those pass and outer PR 23 contains its intended evidence, changelog, and exact core pin, I have no review objection to marking them ready for review. This recommendation does not certify a new build or native run.

The rendered red-to-green result, 29 passing tests, optimized build, native 100/110/125% checks, persistence, and teardown evidence remain historical proof for outer `c28bf9a280e5853a01c033f57adefcfe031e82ec` / core `7f2e3677b5f66c5390c99dbe72caefd6c1e42297`. The reconciled main catalog has not been fully replayed, compiled, or exercised natively by this review. Main changes test fixtures and product behavior beyond these two byte-identical patch files, so the preserved binary must not be described as a build of `69187427`.

Update the evidence README's draft rationale after reconciliation and scope its sentence about later evidence-only commits to that historical stage. Retain the explicit compiled revisions and the historical browser-test link failure; neither describes validation of the new head.

No shared build, he command, UI, source edit, or application directory inspection was used. Only this report was written.

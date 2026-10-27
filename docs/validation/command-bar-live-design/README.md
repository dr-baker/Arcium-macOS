# Live production design proof

These are actual native Studio window captures with the production Views/Skia
renderer and inert public example data. They are not captures of the Swift
approximation. The proof app used an independent copied bundle and scenario;
existing browser and Studio profiles were untouched. It quit normally afterward.

[Dark](studio-dark.png) and [light](studio-light.png) retain the same fixture,
query `a`, and selected Project notes result. In [44-point rows](row-height-44.png)
and [64-point rows](row-height-64.png), the same running process picks up the
changed design value without compiling or relaunching. Larger rows reduce the
number visible in the bounded preview; the fixture stays unchanged. Values were
verified in scenario data and native accessibility; the detailed slider readout
remained below the inspector fold.

The replayed public recipe's command panel implementation and generated design
header match the compiled proof SDK byte for byte. [proof.json](proof.json)
records their hashes and the captured source generation. This is renderer-source
proof, not a fresh full Chromium build of the publication branches.

The inspector still has the previous thumbnail artwork and Advanced label;
those change in the following picker-polish PR. No native MP4 recording tool was
available. Parent-window captures that omit child sheets are excluded.

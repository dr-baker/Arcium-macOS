# Coming from Arc

Arcium adds Spaces, Favorites, Pins, Peek, Little Arc, and an Arc-inspired sidebar
workflow to Helium. It is in development. This guide describes the implementation
in this branch; publication and live verification results belong in the release
notes for the build you install.

The current macOS product requires macOS 26 or later.

## Set up your workspace

1. Open Settings with Command-Comma. In Tabs & Spaces, choose Vertical tabs for
   a sidebar layout and choose its side. In Appearance, adjust Sidebar width.
2. In Appearance, choose how a collapsed sidebar behaves. Icon rail keeps
   compact tab access; Fully hidden hides the sidebar. **Keep top bar visible**
   keeps the address bar visible in Fully hidden and Zen mode. The separate
   sidebar pin remains in Tabs & Spaces and applies to Zen mode.
3. In Keyboard Shortcuts, review the Arc-inspired preset. It applies supported
   actions and reports unsupported ones. It saves the prior shortcut state so
   you can restore it. Applying the preset also selects Fully hidden; you can
   change that appearance choice afterward. Restore previous restores both the
   saved shortcuts and the pre-preset collapse style, replacing later edits to
   those settings.
4. Use Spaces to organize work within a browser profile. Favorites are shared
   across that profile; Pins and their folders belong to a Space. Ordinary tabs
   remain separate from saved sidebar items. Selecting a Space activates its
   window or creates a window for that Space.

Spaces in one profile share cookies and sign-ins. Use separate browser profiles
for separate account identities. Choosing a default Space affects new windows
and persistent items; it does not move already-open windows.
The current interface selects default and imported Spaces. It does not expose
commands to create, rename, or delete a Space.

## Bring your Arc sidebar

Quit Arc normally so its saved sidebar is current, and back up both browsers'
data before importing. Open native Settings, then General, **More settings…**,
and Import data in browser Settings. Choose the Arc source profile and enable
**Import sidebar as Pins**. This option imports the
sidebar as saved Favorites, Pins, and folders. With the option off, the importer
uses tabs and tab groups. The option is a choice for that import, not a permanent
setting.

Refreshing a Pins-mode import replaces the imported Space trees belonging to
that Arc source profile. The refresh also removes local Pins and folders added
inside those trees and replaces edits to their home pages. Back up Arcium before
refreshing. For the installed app, quit Arcium and copy
`~/Library/Application Support/Arcium` to a separate backup location. If you use
a custom profile directory, back up that directory instead.

Check your Spaces, folder order, and saved items after importing and again after
a normal quit and relaunch. Import each source profile into the intended browser
profile. Matching directory names alone do not establish that two profiles
represent the same account.

When refreshing a tabs-mode import, Arcium must be able to replace the previous
imported tabs without a close confirmation. If an imported page has unload
handlers or cannot be closed, the refresh stops before changing the import.
Save any work, close those imported tabs yourself, and retry. Importing the
sidebar as dormant Pins does not require replacing those live tabs.

For passwords and optional cookies, follow the explicit mapping and dry-run
steps in [Arc daily-driver migration](arc-daily-driver-migration.md). That tool
requires both browsers to be closed before applying changes. Some websites
require a new sign-in even after cookie migration.

## Choose the behavior you want

| Setting | Effect |
| --- | --- |
| Enable Peek | Previews eligible links while keeping the saved item's home anchored. Turning it off requests closure of an active Peek and returns eligible link clicks to ordinary navigation. If you cancel the page's unsaved-change prompt, the same document stays open as an ordinary tab and Peek remains off. |
| Suggest Favorites and Pins in the address bar | Includes saved sidebar items among address-bar results. Turning it off preserves the items and ordinary suggestions. |
| Open external links in Little Arc | Routes links opened from other apps through Little Arc. Turning it off uses the ordinary browser window or tab path. |
| Keep top bar visible | Keeps the address bar visible in Zen mode and when the collapsed sidebar is Fully hidden. Turning it off lets those modes hide the top bar. The sidebar pin remains a separate Zen control in Tabs & Spaces. |
| Show Spaces in Dock menu | Shows Spaces in the app's Dock menu. Turning it off shows profile shortcuts when there are multiple profiles. A single profile keeps the ordinary window commands. New Incognito Window remains available when permitted. This setting applies across profiles. |
| Show sidebar collapse button | Shows the collapse button in Vertical layout. Other collapse commands still work when it is hidden. |
| Show New Tab button | Shows the New Tab button in Dynamic layout. Other New Tab commands still work when it is hidden. |
| Enter Picture-in-Picture automatically | Leaving an eligible playing tab can open Picture-in-Picture automatically. Turning it off prevents new automatic entries and keeps an already-open window. Manual Picture-in-Picture is independent. |

Layout-specific controls retain their saved values while another layout is
selected. A disabled row can also indicate a browser feature or policy that
prevents editing. Turning off a behavior switch does not delete saved Spaces,
Favorites, or Pins.

Automatic Picture-in-Picture is experimental. The browser flag **Browser
initiated automatic picture in picture** defaults to off, which disables the
native setting. When the flag is enabled, audible video from an HTTPS or local
file page can qualify. Site permissions still apply. Switching away from the
playing tab triggers entry; turning the setting on alone does not open a window.

## Adjust window colors and effects

Appearance offers Everyday and Advanced views of the same saved colors and
effects. Both show why decorative controls are unavailable. To enable those
controls, switch to Advanced and enable backdrop customization. If a renderer
override prevents color effects, select the Automatic backend and relaunch
Arcium normally as the guidance describes.

While decorative editing is disabled, the color canvas keeps its saved markers
but does not select, edit, or move them. Enabling customization restores the
saved colors. Controls accent remains independent, subject to its own theme
and policy availability.

## Use the sidebar each day

Review your effective bindings in Keyboard Shortcuts. Arc defaults supplies
supported Arc-style bindings; the controls below assume that preset where
applicable.

| Action | Control |
| --- | --- |
| Pin or unpin the current page | Command-D |
| Collapse or expand the sidebar | Command-S |
| Show or hide the toolbar | Command-Shift-D |
| Preview recent tabs | Control-Tab with the default Recent Tab binding |

Control-Tab follows the action assigned in Keyboard Shortcuts. Explicit Recent
Tab actions use recent order and a held-Control preview even when **Cycle tabs
by recent use** is off. That preference controls standard tab-cycling actions;
it does not disable an explicit Recent Tab action.

A Pin keeps its saved home page while its live tab navigates. Use its return-home
control to return to that page. Closing the live tab leaves the saved item
dormant in the sidebar; opening it again starts from its home page. Removing the
saved item is a separate action.

## Arc-like additions and related controls

This inventory separates the browsing additions from their supporting macOS
integration. It does not promise complete Arc parity.

| Addition | What is implemented | Limits or controls |
| --- | --- | --- |
| Spaces | Named workspaces, window assignment, a default Space, and session restoration. | Spaces share the enclosing profile's cookies. The current UI selects default and imported Spaces. There is no master disable switch. |
| Favorites | Profile-wide persistent sidebar items. | Saved items remain when suggestions or Peek are disabled. |
| Pins and folders | Space-specific saved items, folder hierarchy, anchored home navigation, and restoration. | There is no master disable switch; hiding the system needs a complete data and session contract first. |
| Arc sidebar import | Imports Arc's saved hierarchy into native Spaces and persistent items, or into tabs and groups. | Select Import sidebar as Pins for persistent sidebar items. Refresh replaces the source-owned Space trees, including local edits in those trees. |
| Address-bar integration | Favorites and Pins can appear as suggestions. | Independently switchable. |
| Peek | Eligible link previews and an explicit context-menu action. | Independently switchable. Closing the source page waits for both pages' close decisions; Cancel preserves their original documents. |
| Little Arc | External-link routing through a small browser window. | Handles one eligible HTTP(S) external URL per request. Multiple URLs and other schemes use the ordinary path. A shortcut to open a new Little Arc search window is unsupported. |
| Recent-tab switching | Recent-use cycling and explicit Recent Tab shortcuts with previews. | The cycling preference does not remove previews from explicit Recent Tab commands. |
| Sidebar layouts | Vertical tabs, configurable side and width, collapse styles, and Zen controls. | Classic, Compact, and Dynamic layouts are also available. |
| Arc-inspired shortcuts | A preset for supported actions, saved previous bindings, and restoration. | Unsupported actions are reported; review bindings before applying. |
| Split-tab access | Existing split and focus actions exposed through shortcut customization. | No separate master feature toggle. |
| macOS Dock integration | Space shortcuts in the Dock menu. | The app-wide toggle exposes profile shortcuts with multiple profiles, or ordinary window commands with a single profile. |
| Native Settings | Profile-aware macOS window for General, Tabs & Spaces, Appearance, and Keyboard Shortcuts. | Browser preferences remain owned by Chromium; some settings remain in browser WebUI. |
| Chrome appearance | Everyday and Advanced backdrop controls, spatial colors and harmony, shared control accent, material/glass effects, rounded frame, and border controls. | Availability depends on the current configuration and theme. |
| Sizing | Browser UI scale and sidebar width. | These resize browser chrome without changing web page zoom. |
| Automatic Picture-in-Picture | Preference support and automatic-entry behavior behind the browser feature. | Experimental and disabled by the baseline feature configuration. |

Helium's privacy features remain part of the browser. Helium Noise has a global
control in browser Privacy settings and per-site exceptions through Page Info.
It is separate from the Arc-style workflow additions above.

For a control-by-control inventory and acceptance criteria, see the
[feature settings audit](feature-settings-audit.md). For source ownership and
development, see [Helium maintainer onboarding](helium-maintainer-onboarding.md).

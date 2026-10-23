# Coming from Arc

Arcium adds an Arc-inspired sidebar workflow to Helium. This guide covers the current preview. See the [release notes](preview-release.md) for its limits.

To bring over existing data, start with [Import from Arc](import-from-arc.md). Sidebar import and password migration use different tools.

## Set up your workspace

Open Settings with **Command-Comma**. In Tabs & Spaces, choose Vertical tabs and the side of the window. In Appearance, adjust sidebar width, browser UI scale, colors, and collapse behavior. UI scale changes browser controls independently of webpage zoom.

Use the **+** in the sidebar's Space bar to create a Space. Choose its name, icon, profile, and theme. Right-click a Space icon to edit or delete it. Deletion asks for confirmation; the last Space cannot be deleted.

Spaces hold their own Pins and folders. Local Favorites are shared within the profile. Imported Arc Favorites appear in Spaces belonging to their Arc source profile. Spaces in one profile share cookies and sign-ins, so use separate browser profiles for separate accounts. Choosing a default Space affects new windows and saved items; it does not move existing windows.

## Keep useful pages

A Pin keeps its saved home page while its live tab navigates. Use its return-home control to go back. Closing the live tab leaves the saved Pin dormant; opening it again starts at home. Removing the saved item is a separate action.

Local Favorites stay available across the profile. Pins and folders belong to their Space. Ordinary tabs remain separate from saved sidebar items.

## Find and preview pages

**Command-T** opens the command bar. Search tabs, Pins, Favorites, or the web. Click its input and scroll upward to reveal the scope tabs; the selected scope expands its label.

Hold **Control** and press **Tab** to preview recently used tabs. Control-Tab follows the binding in Keyboard Shortcuts. An explicit Recent Tab action uses recent order and the held-Control preview even when **Cycle tabs by recent use** is off. That preference controls standard tab cycling.

Enable Peek to preview eligible links over the source page, or choose **Open Link in Peek** from a link's context menu. A preview can become an ordinary tab or saved sidebar item. If an unsaved-change prompt prevents closure, cancelling preserves the document.

Enable **Open external links in Little Arc** to open one eligible HTTP or HTTPS link from another app in a compact window. Multiple URLs and other schemes use the ordinary browser path. A shortcut to open an empty Little Arc search window is not implemented.

## Choose your layout

Appearance offers **Top bar** and **Sidebar** navigation. Sidebar navigation is available with left Vertical tabs in ordinary windows outside fullscreen. Incognito, Guest, right-side, horizontal, and fullscreen layouts use the standard top bar while keeping the saved choice.

For an address-bar-free layout, choose Top bar navigation and turn **Show top bar** off. Command-L still gives you a place to enter an address.

Choose **Icon rail** to keep compact sidebar access when collapsed, or **Fully hidden** to hide it. Zen controls let you pin the top bar or sidebar. **Keep top bar visible in Zen mode** also applies to Fully hidden; it is unavailable while Sidebar navigation is active.

Sidebar navigation hides standard toolbar items and the bookmarks bar without changing their preferences. Enable **Show Extensions button** for access to the existing Extensions menu in the sidebar header. Returning to Top bar restores the standard presentation.

## Colors and glass

Give each Space a palette with movable glows and its own Browser and Pages appearance modes. Native Appearance settings also control grain, rounded frame, and border width.

Surface customization separates **Text surfaces**, for the command bar and floating controls, from **Containers**, for the recent-tab switcher and Peek. Each group has its own material, tint intensity, and opacity. Tint controls the theme color; opacity controls neutral light or dark backing. Peek also has separate backdrop blur and dimming.

The current menu offers Flat, Clear, Liquid, Chromium glassmorphic, and Solid materials. Availability depends on the renderer, theme, and policy. Read a disabled control's explanation before changing other settings. Turning off decorative customization preserves its saved colors.

## Shortcuts and optional behavior

Keyboard Shortcuts offers an Arc-inspired preset. It applies supported actions, reports unsupported ones, and saves the previous bindings. Applying it also selects Fully hidden. **Restore previous** restores the saved shortcuts and collapse style, replacing later edits to those settings.

| Action | Control with the relevant default or Arc preset |
| --- | --- |
| Pin or unpin the current page | Command-D |
| Collapse or expand the sidebar | Command-S |
| Show or hide the toolbar | Command-Shift-D |
| Preview recent tabs | Control-Tab |

**Suggest Favorites and Pins in the address bar** controls saved-item suggestions without deleting those items. **Show Spaces in Dock menu** controls Space shortcuts in the Dock. Turning it off uses profile shortcuts when multiple profiles exist, or ordinary window commands for one profile.

Automatic Picture-in-Picture is experimental. Its native setting is unavailable while the **Browser initiated automatic picture in picture** feature is off. With that feature enabled, eligible audible video can enter Picture-in-Picture when you switch away. Site permissions still apply; turning the setting on alone does not open a window.

For detailed behavior and preference ownership, see [feature settings contracts](feature-settings-audit.md) and [native settings bindings](native-settings-bindings.md).

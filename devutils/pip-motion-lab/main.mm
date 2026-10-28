#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>
#include "Motion.hpp"
#include <memory>

using namespace pip_motion;

struct Parameter {
  const char *key, *label;
  double low, high;
  double Settings::*member;
  const char *help;
  bool optional = false;
};
static const Parameter parameters[] = {
  {"response", "Spring response (seconds)", .15, .90, &Settings::response,
    "How quickly the spring brings the window to its destination.\n\n"
    "Lower: faster and tighter. Higher: slower and floatier.\n\n"
    "This is the spring's response parameter, not the total animation duration. Damping and release velocity also affect the movement."},
  {"damping", "Damping · 1 = no bounce", .65, 1.35, &Settings::damping,
    "Controls how much the spring bounces as it settles.\n\n"
    "Below 1: more bounce. At 1: critically damped. Above 1: a more restrained, usually slower return.\n\n"
    "Strong release momentum can still carry the window past a target."},
  {"projection", "Momentum projection (seconds)", 0, .90, &Settings::projection,
    "Estimates where your flick is headed when choosing a corner or edge.\n\n"
    "Projected position = release position + velocity × projection time.\n\n"
    "At 0.5 seconds, a 1,000-point/second release looks about 500 points ahead. Higher favors distant docks; lower favors nearby docks. Zero chooses by release position alone.\n\n"
    "Used for faster flicks in Smart mode and releases in Always snap. Slow deliberate attraction stays local. Spring response and damping control how the window gets there."},
  {"margin", "Screen inset (points)", 0, 36, &Settings::margin,
    "The gap between a resting docked window and the display's visible work-area edges.\n\n"
    "Higher: leaves more breathing room. Lower: rests closer to the edges.\n\n"
    "The work area excludes space reserved for the menu bar and Dock."},
  {"stash_distance", "Tuck past edge (points)", 20, 160, &Settings::stash_distance,
    "How far the window must cross the left or right screen edge before releasing it tucks it away.\n\n"
    "Lower: a smaller push is enough. Higher: requires pushing farther offscreen.\n\n"
    "A fast outward flick near a side can also trigger tucking."},
  {"stash_velocity", "Outward tuck speed (points/s)", 300, 1800, &Settings::stash_velocity,
    "The outward release speed needed to tuck near a side. The flick must be mostly horizontal.\n\n"
    "Lower: easier to tuck with a flick. Higher: requires a faster flick.\n\n"
    "The same threshold lets a fast inward flick restore a tucked window."},
  {"restore_distance", "Pull to restore (points)", 10, 80, &Settings::restore_distance,
    "How far inward you must pull a tucked window before releasing to restore it.\n\n"
    "Lower: a shorter pull restores. Higher: requires a longer pull.\n\n"
    "Clicking the exposed strip or making a fast inward flick also restores it."},
  {"handle", "Visible tucked strip (points)", 20, 52, &Settings::handle,
    "The width of the strip left onscreen when the window is tucked.\n\n"
    "Higher: easier to grab, but occupies more screen space. Lower: hides more of the window.\n\n"
    "Also limits spring overshoot so a grabbable part of the window remains onscreen."},
  {"resistance", "Vertical boundary resistance", .05, .85, &Settings::resistance,
    "How much the window follows your pointer when pulled beyond the top or bottom boundary.\n\n"
    "Lower: less movement for the same pull, so the edge feels firmer. Higher: more movement, so it feels softer.\n\n"
    "Affects dragging beyond vertical boundaries. Damping controls spring bounce after release."},
  {"free_speed", "Leave here below speed (points/s)", 0, 800, &Settings::free_speed,
    "In Smart mode, releases at or below this speed count as deliberate placement.\n\n"
    "Away from a dock, the window stays where dropped. Near a dock, it snaps locally. Faster releases project toward a dock.\n\n"
    "Higher: more drops stay where placed. Lower: you must release more slowly. Briefly pausing before release helps place precisely.", true},
  {"snap_distance", "Snap attraction distance (points)", 0, 180, &Settings::snap_distance,
    "In Smart mode, how close a slow drop must be to the nearest allowed dock to snap there.\n\n"
    "Higher: a larger attraction zone. Lower: more freedom to leave the window near a dock. Zero requires exact alignment.\n\n"
    "Measured from the window's dropped position to the nearest corner or side-edge dock. Faster flicks use momentum projection instead.", true},
};
static constexpr size_t parameterCount = sizeof(parameters) / sizeof(parameters[0]);

static NSString *phaseName(Phase phase) {
  switch (phase) {
    case Phase::Resting: return @"Resting";
    case Phase::Dragging: return @"Dragging";
    case Phase::Settling: return @"Settling";
    case Phase::Tucked: return @"Tucked";
  }
}

@class MotionLab;
@interface ExampleView : NSView
@property(nonatomic, weak) MotionLab *lab;
@property(nonatomic) Side tucked;
@end

@interface ExamplePanel : NSPanel
@end
@implementation ExamplePanel
- (NSRect)constrainFrameRect:(NSRect)frame toScreen:(NSScreen *)screen { return frame; }
- (BOOL)canBecomeKeyWindow { return NO; }
@end

@interface MotionLab : NSObject <NSApplicationDelegate, NSWindowDelegate> {
  std::unique_ptr<Motion> motion;
  NSWindow *controls;
  ExamplePanel *panel;
  ExampleView *example;
  NSMutableArray<NSSlider *> *sliders;
  NSMutableArray<NSTextField *> *fields;
  NSPopUpButton *dockMenu, *presetMenu, *placementMenu;
  NSTextField *status, *fileStatus, *explanation;
  NSTimer *animationTimer, *fileTimer, *saveTimer;
  double lastTick;
  NSString *settingsPath, *statePath;
  NSData *lastSettingsData;
}
- (instancetype)initWithSettingsPath:(NSString *)path;
- (void)begin:(NSEvent *)event;
- (void)drag:(NSEvent *)event;
- (void)end:(NSEvent *)event;
@end

@implementation ExampleView
- (BOOL)acceptsFirstMouse:(NSEvent *)event { return YES; }
- (BOOL)mouseDownCanMoveWindow { return NO; }
- (void)mouseDown:(NSEvent *)event { [self.lab begin:event]; }
- (void)mouseDragged:(NSEvent *)event { [self.lab drag:event]; }
- (void)mouseUp:(NSEvent *)event { [self.lab end:event]; }
- (void)drawRect:(NSRect)dirty {
  NSRect bounds = self.bounds;
  [[NSBezierPath bezierPathWithRoundedRect:bounds xRadius:16 yRadius:16] addClip];
  NSGradient *gradient = [[NSGradient alloc] initWithStartingColor:
      [NSColor colorWithSRGBRed:.12 green:.30 blue:.38 alpha:1]
      endingColor:[NSColor colorWithSRGBRed:.05 green:.08 blue:.15 alpha:1]];
  [gradient drawInRect:bounds angle:25];
  [[NSColor colorWithWhite:1 alpha:.08] setFill];
  [[NSBezierPath bezierPathWithOvalInRect:NSMakeRect(150, -90, 260, 260)] fill];
  [@"PiP Motion Lab" drawAtPoint:NSMakePoint(22, 118) withAttributes:@{
    NSFontAttributeName:[NSFont systemFontOfSize:21 weight:NSFontWeightSemibold],
    NSForegroundColorAttributeName:NSColor.whiteColor}];
  [@"Drag · flick · interrupt · tuck" drawAtPoint:NSMakePoint(22, 91) withAttributes:@{
    NSFontAttributeName:[NSFont systemFontOfSize:13],
    NSForegroundColorAttributeName:[NSColor colorWithWhite:1 alpha:.65]}];
  [@"Native window · no video · no Chromium" drawAtPoint:NSMakePoint(22, 20) withAttributes:@{
    NSFontAttributeName:[NSFont systemFontOfSize:11],
    NSForegroundColorAttributeName:[NSColor colorWithWhite:1 alpha:.45]}];
  if (self.tucked != Side::None) {
    CGFloat x = self.tucked == Side::Left ? bounds.size.width - 14 : 14;
    CGFloat sign = self.tucked == Side::Left ? 1 : -1;
    NSBezierPath *chevron = NSBezierPath.bezierPath;
    [chevron moveToPoint:NSMakePoint(x - sign * 3, 83)];
    [chevron lineToPoint:NSMakePoint(x + sign * 3, 90)];
    [chevron lineToPoint:NSMakePoint(x - sign * 3, 97)];
    chevron.lineWidth = 2;
    [NSColor.whiteColor setStroke]; [chevron stroke];
  }
}
@end

static NSTextField *label(NSString *text, NSRect frame, CGFloat size) {
  NSTextField *view = [NSTextField labelWithString:text];
  view.frame = frame;
  view.font = [NSFont systemFontOfSize:size];
  return view;
}

@interface HelpButton : NSButton {
  NSString *helpText;
  NSPopover *helpPopover;
}
- (instancetype)initWithFrame:(NSRect)frame name:(NSString *)name help:(NSString *)help;
@end

@implementation HelpButton
- (instancetype)initWithFrame:(NSRect)frame name:(NSString *)name help:(NSString *)help {
  if ((self = [super initWithFrame:frame])) {
    helpText = help;
    self.title = @""; self.bordered = NO;
    self.image = [NSImage imageWithSystemSymbolName:@"info.circle" accessibilityDescription:nil];
    self.imagePosition = NSImageOnly;
    self.contentTintColor = NSColor.secondaryLabelColor;
    self.toolTip = help;
    self.accessibilityLabel = [@"About " stringByAppendingString:name];
    self.accessibilityHelp = help;
    self.target = self; self.action = @selector(showHelp:);
  }
  return self;
}
- (void)showHelp:(id)sender {
  if (helpPopover.shown) { [helpPopover close]; return; }
  NSTextField *text = [NSTextField wrappingLabelWithString:helpText];
  text.font = [NSFont systemFontOfSize:13]; text.selectable = YES;
  NSSize measured = [helpText boundingRectWithSize:NSMakeSize(348, CGFLOAT_MAX)
      options:NSStringDrawingUsesLineFragmentOrigin | NSStringDrawingUsesFontLeading
      attributes:@{NSFontAttributeName:text.font}].size;
  text.frame = NSMakeRect(16, 14, 348, std::ceil(measured.height) + 4);
  NSViewController *controller = [[NSViewController alloc] init];
  controller.view = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 380, NSMaxY(text.frame) + 14)];
  [controller.view addSubview:text];
  helpPopover = [[NSPopover alloc] init];
  helpPopover.behavior = NSPopoverBehaviorTransient;
  helpPopover.contentViewController = controller;
  [helpPopover showRelativeToRect:self.bounds ofView:self preferredEdge:NSMaxXEdge];
}
@end

static void addHelp(NSView *parent, NSRect frame, NSString *name, NSString *text) {
  [parent addSubview:[[HelpButton alloc] initWithFrame:frame name:name help:text]];
}

@implementation MotionLab
- (instancetype)initWithSettingsPath:(NSString *)path {
  if ((self = [super init])) {
    settingsPath = path;
    statePath = [[path stringByDeletingLastPathComponent] stringByAppendingPathComponent:@"state.json"];
  }
  return self;
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
  NSScreen *screen = NSScreen.mainScreen;
  for (NSScreen *candidate in NSScreen.screens) {
    if (CGDisplayIsBuiltin([candidate.deviceDescription[@"NSScreenNumber"] unsignedIntValue])) {
      screen = candidate; break;
    }
  }
  NSRect area = screen.visibleFrame;
  NSData *previousData = [NSData dataWithContentsOfFile:statePath];
  id previousState = previousData ? [NSJSONSerialization JSONObjectWithData:previousData options:0 error:nil] : nil;
  motion = std::make_unique<Motion>(pip_motion::Rect{area.origin.x, area.origin.y, area.size.width, area.size.height});
  controls = [[NSWindow alloc] initWithContentRect:NSMakeRect(area.origin.x + 28,
      NSMaxY(area) - 868, 536, 840)
      styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
      backing:NSBackingStoreBuffered defer:NO];
  controls.title = @"PiP Motion Lab — live tuning";
  controls.delegate = self;
  controls.releasedWhenClosed = NO;
  NSView *content = controls.contentView;
  [content addSubview:label(@"Tune the movement", NSMakeRect(24, 796, 480, 28), 22)];
  NSTextField *intro = label(@"Drop slowly to leave it there; flick to dock. Push past a side to tuck.\nClick the exposed strip to restore. Re-grab an animation to interrupt it.",
      NSMakeRect(24, 745, 490, 44), 12);
  intro.textColor = NSColor.secondaryLabelColor;
  [content addSubview:intro];
  presetMenu = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(24, 709, 210, 28) pullsDown:NO];
  [presetMenu addItemsWithTitles:@[@"iOS-like baseline", @"Snappy", @"Soft spring", @"Position only", @"Custom"]];
  presetMenu.target = self; presetMenu.action = @selector(presetChanged:);
  [content addSubview:presetMenu];
  addHelp(content, NSMakeRect(238, 714, 18, 18), @"Presets",
      @"Loads a set of numeric tuning values while preserving your docking and placement modes.\n\n"
      "iOS-like baseline uses the defaults. Snappy uses a faster spring and shorter projection. Soft spring is slower with some bounce. Position only sets projection to zero. Custom means values were changed individually.\n\n"
      "Reset all variables also resets the docking and placement modes.");
  dockMenu = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(274, 709, 214, 28) pullsDown:NO];
  [dockMenu addItemsWithTitles:@[@"Dock at four corners", @"Dock anywhere on side edges"]];
  dockMenu.target = self; dockMenu.action = @selector(dockingChanged:);
  [content addSubview:dockMenu];
  addHelp(content, NSMakeRect(494, 714, 18, 18), @"Docking mode",
      @"Chooses the allowed resting destinations when a release snaps.\n\n"
      "Four corners: docks at a corner of the visible work area. Side edges: docks on the left or right while allowing any height.\n\n"
      "Momentum projection can choose a farther destination. Slow deliberate attraction uses the nearest dock.");
  placementMenu = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(24, 671, 288, 28) pullsDown:NO];
  [placementMenu addItemsWithTitles:@[@"Smart · slow drop stays, flick snaps", @"Always snap to dock", @"Always leave where dropped"]];
  placementMenu.target = self; placementMenu.action = @selector(placementChanged:);
  [content addSubview:placementMenu];
  addHelp(content, NSMakeRect(318, 676, 18, 18), @"Placement mode",
      @"Smart: slow releases stay where dropped unless near a dock; faster flicks snap using momentum.\n\n"
      "Always snap: every release docks. Always leave: releases stop where dropped, within the visible inset.\n\n"
      "Side tucking still works in every mode. The two attraction controls below tune Smart mode.");
  [self button:@"Reset all variables" frame:NSMakeRect(348, 671, 164, 28) action:@selector(resetVariables:) tag:0];
  sliders = NSMutableArray.array; fields = NSMutableArray.array;
  for (size_t i = 0; i < parameterCount; ++i) {
    CGFloat y = 626 - i * 43;
    NSTextField *heading = label(@(parameters[i].label), NSMakeRect(24, y + 16, 370, 18), 11);
    [heading sizeToFit]; [content addSubview:heading];
    addHelp(content, NSMakeRect(NSMaxX(heading.frame) + 6, y + 15, 18, 18),
        @(parameters[i].label), @(parameters[i].help));
    NSSlider *slider = [NSSlider sliderWithValue:motion->settings.*parameters[i].member
        minValue:parameters[i].low maxValue:parameters[i].high target:self action:@selector(sliderChanged:)];
    slider.frame = NSMakeRect(24, y - 2, 392, 22); slider.tag = i; slider.continuous = YES;
    slider.accessibilityLabel = @(parameters[i].label);
    slider.accessibilityHelp = @(parameters[i].help);
    [sliders addObject:slider]; [content addSubview:slider];
    NSTextField *field = [[NSTextField alloc] initWithFrame:NSMakeRect(434, y + 1, 78, 24)];
    field.tag = i; field.target = self; field.action = @selector(fieldChanged:);
    field.alignment = NSTextAlignmentRight;
    field.accessibilityLabel = [@(parameters[i].label) stringByAppendingString:@" value"];
    field.accessibilityHelp = @(parameters[i].help);
    [fields addObject:field]; [content addSubview:field];
  }
  explanation = label(@"", NSMakeRect(24, 153, 488, 22), 11);
  explanation.textColor = NSColor.secondaryLabelColor; [content addSubview:explanation];
  NSArray *titles = @[@"↖ Throw", @"↗ Throw", @"↙ Throw", @"↘ Throw"];
  for (NSInteger i = 0; i < 4; ++i)
    [self button:titles[i] frame:NSMakeRect(24 + i * 124, 115, 116, 28) action:@selector(sampleThrow:) tag:i];
  [self button:@"Replay throw" frame:NSMakeRect(24, 79, 154, 28) action:@selector(replay:) tag:0];
  [self button:@"Tuck / restore" frame:NSMakeRect(190, 79, 154, 28) action:@selector(toggleTuck:) tag:0];
  [self button:@"Reset position" frame:NSMakeRect(356, 79, 156, 28) action:@selector(reset:) tag:0];
  status = label(@"", NSMakeRect(24, 48, 488, 20), 11);
  status.font = [NSFont monospacedSystemFontOfSize:11 weight:NSFontWeightRegular];
  [content addSubview:status];
  fileStatus = label(@"Settings save and reload live · no rebuild needed", NSMakeRect(24, 22, 416, 18), 10);
  fileStatus.textColor = NSColor.secondaryLabelColor; [content addSubview:fileStatus];
  [self button:@"JSON…" frame:NSMakeRect(446, 17, 70, 25) action:@selector(reveal:) tag:0];

  panel = [[ExamplePanel alloc] initWithContentRect:NSMakeRect(motion->position.x,
      motion->position.y, motion->size.width, motion->size.height)
      styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
      backing:NSBackingStoreBuffered defer:NO];
  panel.title = @"PiP motion example";
  panel.opaque = NO; panel.backgroundColor = NSColor.clearColor;
  panel.hasShadow = YES; panel.hidesOnDeactivate = NO;
  panel.level = NSFloatingWindowLevel;
  panel.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces |
      NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorStationary;
  example = [[ExampleView alloc] initWithFrame:NSMakeRect(0, 0, 320, 180)];
  example.lab = self; panel.contentView = example;
  [self syncControls];
  if ([NSFileManager.defaultManager fileExistsAtPath:settingsPath]) [self reloadSettings];
  else [self saveSettings];
  if ([previousState isKindOfClass:NSDictionary.class] &&
      [previousState[@"x"] isKindOfClass:NSNumber.class] && [previousState[@"y"] isKindOfClass:NSNumber.class]) {
    double x = [previousState[@"x"] doubleValue], y = [previousState[@"y"] doubleValue];
    if (std::isfinite(x) && std::isfinite(y)) {
      motion->placeAt({x, y});
      if ([previousState[@"tucked"] boolValue]) {
        motion->tuck(x < NSMidX(area) ? Side::Left : Side::Right);
        [self startAnimation];
      }
    }
  }
  [controls makeKeyAndOrderFront:nil]; [panel orderFrontRegardless];
  [NSApp activateIgnoringOtherApps:YES];
  [self showPosition];
  fileTimer = [NSTimer timerWithTimeInterval:.5 target:self selector:@selector(checkFile:) userInfo:nil repeats:YES];
  [NSRunLoop.mainRunLoop addTimer:fileTimer forMode:NSRunLoopCommonModes];
}
- (void)button:(NSString *)title frame:(NSRect)frame action:(SEL)action tag:(NSInteger)tag {
  NSButton *button = [NSButton buttonWithTitle:title target:self action:action];
  button.frame = frame; button.tag = tag; [controls.contentView addSubview:button];
}
- (void)syncControls {
  for (size_t i = 0; i < parameterCount; ++i) {
    double value = motion->settings.*parameters[i].member;
    sliders[i].doubleValue = value;
    fields[i].stringValue = [NSString stringWithFormat:parameters[i].high > 10 ? @"%.0f" : @"%.3f", value];
  }
  [dockMenu selectItemAtIndex:motion->settings.docking == Docking::Corners ? 0 : 1];
  [placementMenu selectItemAtIndex:static_cast<NSInteger>(motion->settings.placement)];
}
- (void)apply:(Settings)settings save:(BOOL)save {
  motion->retune(settings); [self syncControls]; [self startAnimation];
  if (save) {
    [saveTimer invalidate];
    saveTimer = [NSTimer scheduledTimerWithTimeInterval:.15 target:self selector:@selector(saveSettings) userInfo:nil repeats:NO];
  }
}
- (void)sliderChanged:(NSSlider *)sender {
  Settings next = motion->settings; next.*parameters[sender.tag].member = sender.doubleValue;
  [presetMenu selectItemAtIndex:4]; [self apply:next save:YES];
}
- (void)fieldChanged:(NSTextField *)sender {
  NSScanner *scanner = [NSScanner scannerWithString:sender.stringValue];
  double value;
  const auto& parameter = parameters[sender.tag];
  if (![scanner scanDouble:&value] || !scanner.isAtEnd || !std::isfinite(value) || value < parameter.low || value > parameter.high) {
    fileStatus.stringValue = [NSString stringWithFormat:@"Enter a value from %.2f to %.2f", parameter.low, parameter.high];
    [self syncControls]; return;
  }
  Settings next = motion->settings; next.*parameter.member = value;
  [presetMenu selectItemAtIndex:4]; [self apply:next save:YES];
}
- (void)dockingChanged:(NSPopUpButton *)sender {
  Settings next = motion->settings;
  next.docking = sender.indexOfSelectedItem == 0 ? Docking::Corners : Docking::SideEdges;
  [presetMenu selectItemAtIndex:4]; [self apply:next save:YES];
}
- (void)placementChanged:(NSPopUpButton *)sender {
  Settings next = motion->settings;
  next.placement = static_cast<Placement>(sender.indexOfSelectedItem);
  [presetMenu selectItemAtIndex:4]; [self apply:next save:YES];
}
- (void)presetChanged:(NSPopUpButton *)sender {
  if (sender.indexOfSelectedItem == 4) return;
  Settings next;
  next.docking = motion->settings.docking;
  next.placement = motion->settings.placement;
  if (sender.indexOfSelectedItem == 1) { next.response = .28; next.projection = .35; }
  if (sender.indexOfSelectedItem == 2) { next.response = .60; next.damping = .85; }
  if (sender.indexOfSelectedItem == 3) next.projection = 0;
  [self apply:next save:YES];
}
- (void)sampleThrow:(NSButton *)sender {
  pip_motion::Point v{sender.tag % 2 == 0 ? -1100.0 : 1100.0, sender.tag < 2 ? 600.0 : -600.0};
  motion->throwFrom(motion->centerOrigin(), v, false); [self startAnimation];
}
- (void)replay:(id)sender { motion->replay(); [self startAnimation]; }
- (void)toggleTuck:(id)sender {
  if (motion->tucked != Side::None) motion->restore(); else motion->tuck(Side::None);
  [self startAnimation];
}
- (void)reset:(id)sender { motion->reset(); [self showPosition]; [self stopAnimation]; }
- (void)resetVariables:(id)sender {
  [controls makeFirstResponder:nil];
  [saveTimer invalidate]; saveTimer = nil;
  motion->resetSettings();
  [self syncControls]; [presetMenu selectItemAtIndex:0];
  [self startAnimation]; [self saveSettings];
}
- (void)reveal:(id)sender { [NSWorkspace.sharedWorkspace activateFileViewerSelectingURLs:@[[NSURL fileURLWithPath:settingsPath]]]; }
- (pip_motion::Point)point:(NSEvent *)event {
  NSPoint p = [event.window convertPointToScreen:event.locationInWindow]; return {p.x, p.y};
}
- (void)begin:(NSEvent *)event {
  [self stopAnimation]; motion->begin([self point:event], event.timestamp); [self showPosition];
}
- (void)drag:(NSEvent *)event {
  motion->drag([self point:event], event.timestamp); [self showPosition];
}
- (void)end:(NSEvent *)event { motion->end(event.timestamp); [self startAnimation]; }
- (void)startAnimation {
  [self showPosition];
  if (motion->phase != Phase::Settling || animationTimer) return;
  lastTick = NSProcessInfo.processInfo.systemUptime;
  animationTimer = [NSTimer timerWithTimeInterval:1.0/120 target:self selector:@selector(tick:) userInfo:nil repeats:YES];
  [NSRunLoop.mainRunLoop addTimer:animationTimer forMode:NSRunLoopCommonModes];
}
- (void)stopAnimation { [animationTimer invalidate]; animationTimer = nil; }
- (void)tick:(NSTimer *)timer {
  double now = NSProcessInfo.processInfo.systemUptime;
  motion->step(std::min(.05, now - lastTick)); lastTick = now;
  [self showPosition];
  if (motion->phase != Phase::Settling) [self stopAnimation];
}
- (void)showPosition {
  [panel setFrameOrigin:NSMakePoint(motion->position.x, motion->position.y)];
  example.tucked = motion->tucked; example.needsDisplay = YES;
  status.stringValue = [NSString stringWithFormat:@"%@  ·  x %.0f  y %.0f  →  %.0f, %.0f",
      phaseName(motion->phase), motion->position.x, motion->position.y, motion->target.x, motion->target.y];
  if (motion->decision == Decision::Keep || motion->decision == Decision::Dock) {
    explanation.stringValue = [NSString stringWithFormat:@"%@ · release %.0f pt/s · nearest dock %.0f pt away",
        motion->decision == Decision::Keep ? @"Left here" : @"Snapped", motion->release_speed, motion->dock_distance];
  } else if (motion->decision == Decision::Tuck) explanation.stringValue = @"Tucked · click the strip or pull inward to restore";
  else if (motion->decision == Decision::Restore)
    explanation.stringValue = motion->phase == Phase::Resting ? @"Restored to the side at the same height" :
        motion->phase == Phase::Dragging ? @"Grabbed during restore · release to continue or drag to place" :
        @"Restoring to the side at the same height";
  else explanation.stringValue = @"Smart mode leaves slow drops away from a dock where you put them";
  // The state file is an observable checkpoint, not a frame-by-frame trace.
  if (motion->phase != Phase::Settling && motion->phase != Phase::Dragging) [self writeState];
}
- (NSDictionary *)settingsDictionary {
  NSMutableDictionary *dict = [@{@"version":@1, @"docking":motion->settings.docking == Docking::Corners ? @"corners" : @"edges"} mutableCopy];
  dict[@"placement"] = @[@"smart", @"always-dock", @"free"][static_cast<NSInteger>(motion->settings.placement)];
  for (const auto& parameter : parameters) dict[@(parameter.key)] = @(motion->settings.*parameter.member);
  return dict;
}
- (void)writeState {
  NSDictionary *state = @{@"pid":@(NSProcessInfo.processInfo.processIdentifier),
    @"phase":phaseName(motion->phase), @"x":@(motion->position.x), @"y":@(motion->position.y),
    @"target_x":@(motion->target.x), @"target_y":@(motion->target.y),
    @"tucked":@(motion->tucked != Side::None), @"settings":[self settingsDictionary],
    @"native_frame":@[@(panel.frame.origin.x), @(panel.frame.origin.y), @(panel.frame.size.width), @(panel.frame.size.height)],
    @"decision":explanation.stringValue,
    @"work_area":@[@(motion->area().x), @(motion->area().y), @(motion->area().width), @(motion->area().height)]};
  NSData *data = [NSJSONSerialization dataWithJSONObject:state options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys error:nil];
  [data writeToFile:statePath atomically:YES];
}
- (void)saveSettings {
  NSError *error = nil;
  NSData *data = [NSJSONSerialization dataWithJSONObject:[self settingsDictionary]
      options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys error:&error];
  if (data && [data writeToFile:settingsPath options:NSDataWritingAtomic error:&error]) {
    lastSettingsData = data;
    fileStatus.stringValue = @"Saved · JSON edits also reload live";
  } else fileStatus.stringValue = [@"Save failed: " stringByAppendingString:error.localizedDescription ?: @"unknown error"];
}
- (void)reloadSettings {
  NSData *data = [NSData dataWithContentsOfFile:settingsPath];
  if (!data || [data isEqualToData:lastSettingsData]) return;
  lastSettingsData = data;
  NSError *error = nil;
  id object = [NSJSONSerialization JSONObjectWithData:data options:0 error:&error];
  BOOL valid = [object isKindOfClass:NSDictionary.class];
  NSDictionary *dict = valid ? object : @{};
  valid = valid && [dict[@"version"] isEqual:@1] &&
      ([dict[@"docking"] isEqual:@"corners"] || [dict[@"docking"] isEqual:@"edges"]);
  Settings next;
  for (const auto& parameter : parameters) {
    id value = dict[@(parameter.key)];
    if (!value && parameter.optional) continue;
    BOOL numeric = [value isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)value) != CFBooleanGetTypeID();
    double number = numeric ? [value doubleValue] : NAN;
    if (!std::isfinite(number) || number < parameter.low || number > parameter.high) valid = NO;
    else next.*parameter.member = number;
  }
  NSString *placement = dict[@"placement"] ?: @"smart";
  NSArray *placements = @[@"smart", @"always-dock", @"free"];
  NSUInteger placementIndex = [placements indexOfObject:placement];
  if (placementIndex == NSNotFound) valid = NO;
  else next.placement = static_cast<Placement>(placementIndex);
  if (!valid) {
    fileStatus.stringValue = @"Invalid settings file · keeping the last valid values"; return;
  }
  next.docking = [dict[@"docking"] isEqual:@"corners"] ? Docking::Corners : Docking::SideEdges;
  [saveTimer invalidate]; saveTimer = nil;
  [presetMenu selectItemAtIndex:4]; [self apply:next save:NO];
  fileStatus.stringValue = @"Reloaded JSON · all controls are live";
}
- (void)checkFile:(NSTimer *)timer { [self reloadSettings]; }
- (void)windowWillClose:(NSNotification *)notification { [NSApp terminate:nil]; }
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender { return YES; }
- (void)applicationWillTerminate:(NSNotification *)notification {
  [self stopAnimation]; [fileTimer invalidate]; [saveTimer invalidate];
}
@end

int main(int argc, const char *argv[]) {
  @autoreleasepool {
    NSString *path = nil;
    for (int i = 1; i + 1 < argc; ++i)
      if (strcmp(argv[i], "--settings") == 0) path = @(argv[++i]);
    if (!path) path = [[NSBundle.mainBundle.bundlePath stringByDeletingLastPathComponent]
        stringByAppendingPathComponent:@"settings.json"];
    [NSFileManager.defaultManager createDirectoryAtPath:[path stringByDeletingLastPathComponent]
        withIntermediateDirectories:YES attributes:nil error:nil];
    NSApplication *app = NSApplication.sharedApplication;
    [app setActivationPolicy:NSApplicationActivationPolicyRegular];
    NSMenu *menu = [NSMenu new];
    NSMenuItem *appMenu = [NSMenuItem new]; [menu addItem:appMenu];
    appMenu.submenu = [NSMenu new];
    [appMenu.submenu addItemWithTitle:@"Quit PiP Motion Lab" action:@selector(terminate:) keyEquivalent:@"q"];
    app.mainMenu = menu;
    MotionLab *delegate = [[MotionLab alloc] initWithSettingsPath:path];
    app.delegate = delegate; [app run];
  }
  return 0;
}

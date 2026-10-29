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
  {"stash_percent", "Tuck past edge (% of width)", 0, 75, &Settings::stash_percent,
    "The percentage of the window's width that must be past the left or right screen edge when you release to tuck it.\n\n"
    "25% means one quarter of the window is offscreen. 50% means half. This scales with the window's size.\n\n"
    "Lower: a smaller push is enough. Higher: more of the window must be offscreen.\n\n"
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

// Release feedback lives in the lab, not the motion model; it only reads predictions.
struct Feedback {
  bool enabled = true;
  double outline = .50;
  double dim = .22;
  double fade = 0;
};
struct FeedbackParameter {
  const char *key, *label;
  double low, high;
  double Feedback::*member;
  const char *help;
};
static const FeedbackParameter feedbackParameters[] = {
  {"feedback_outline", "Landing outline", 0, 1, &Feedback::outline,
    "How visible the landing outline is while you drag.\n\n"
    "Higher: easier to spot on busy backgrounds. Lower: quieter. Zero hides it.\n\n"
    "The outline only appears where letting go would snap or restore the window."},
  {"feedback_dim", "Tuck dim", 0, .6, &Feedback::dim,
    "How much the window darkens once letting go would tuck it, and while it stays tucked.\n\n"
    "Higher: the tucked state is more obvious. Zero keeps only the chevron."},
  {"feedback_fade", "Fade (s)", 0, .3, &Feedback::fade,
    "How long the hints take to appear and disappear, in seconds.\n\n"
    "Zero switches instantly. A short fade keeps hints calm when you hover near a threshold."},
};
static constexpr size_t feedbackParameterCount = sizeof(feedbackParameters) / sizeof(feedbackParameters[0]);

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
@end

// Tucked look: optional dim plus the chevron on the edge that stays onscreen.
@interface ShadeView : NSView
@property(nonatomic) Side side;
@property(nonatomic) CGFloat dim;
@end
@implementation ShadeView
- (NSView *)hitTest:(NSPoint)point { return nil; }
- (void)drawRect:(NSRect)dirty {
  NSRect bounds = self.bounds;
  [[NSBezierPath bezierPathWithRoundedRect:bounds xRadius:16 yRadius:16] addClip];
  if (self.dim > 0) {
    [[NSColor colorWithWhite:0 alpha:self.dim] setFill];
    NSRectFillUsingOperation(bounds, NSCompositingOperationSourceOver);
  }
  if (self.side == Side::None) return;
  CGFloat x = self.side == Side::Left ? bounds.size.width - 14 : 14;
  CGFloat sign = self.side == Side::Left ? 1 : -1;
  NSBezierPath *chevron = NSBezierPath.bezierPath;
  [chevron moveToPoint:NSMakePoint(x - sign * 3, 83)];
  [chevron lineToPoint:NSMakePoint(x + sign * 3, 90)];
  [chevron lineToPoint:NSMakePoint(x - sign * 3, 97)];
  chevron.lineWidth = 2;
  [NSColor.whiteColor setStroke]; [chevron stroke];
}
@end

@interface GhostOutline : NSView
@end
@implementation GhostOutline
- (NSView *)hitTest:(NSPoint)point { return nil; }
- (void)drawRect:(NSRect)dirty {
  NSBezierPath *path = [NSBezierPath bezierPathWithRoundedRect:NSInsetRect(self.bounds, .5, .5)
      xRadius:15.5 yRadius:15.5];
  path.lineWidth = 1;
  [[NSColor.labelColor colorWithAlphaComponent:.22] setStroke]; [path stroke];
}
@end

static NSImage *roundedMask(CGFloat radius) {
  NSImage *image = [NSImage imageWithSize:NSMakeSize(radius * 2 + 1, radius * 2 + 1) flipped:NO
      drawingHandler:^BOOL(NSRect rect) {
    [NSColor.blackColor setFill];
    [[NSBezierPath bezierPathWithRoundedRect:rect xRadius:radius yRadius:radius] fill];
    return YES;
  }];
  image.capInsets = NSEdgeInsetsMake(radius, radius, radius, radius);
  image.resizingMode = NSImageResizingModeStretch;
  return image;
}

static void fadeTo(id object, CGFloat alpha, double duration) {
  if (duration <= 0) {
    [object setAlphaValue:alpha];
    return;
  }
  [NSAnimationContext runAnimationGroup:^(NSAnimationContext *context) {
    context.duration = duration;
    context.timingFunction = [CAMediaTimingFunction functionWithName:kCAMediaTimingFunctionEaseOut];
    [[object animator] setAlphaValue:alpha];
  }];
}

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
  NSTimer *animationTimer, *fileTimer, *saveTimer, *dragTimer;
  double lastTick;
  NSString *settingsPath, *statePath;
  NSData *lastSettingsData;
  Feedback feedback;
  ShadeView *shade;
  ExamplePanel *ghost;
  NSButton *feedbackToggle;
  NSMutableArray<NSSlider *> *feedbackSliders;
  NSMutableArray<NSTextField *> *feedbackFields;
  BOOL shadeShown, ghostShown;
  CGFloat ghostAlpha;
  double lastEventTimestamp, lastEventUptime;
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
  [@"Opus PiP Lab" drawAtPoint:NSMakePoint(22, 118) withAttributes:@{
    NSFontAttributeName:[NSFont systemFontOfSize:21 weight:NSFontWeightSemibold],
    NSForegroundColorAttributeName:NSColor.whiteColor}];
  [@"Drag · flick · interrupt · tuck" drawAtPoint:NSMakePoint(22, 91) withAttributes:@{
    NSFontAttributeName:[NSFont systemFontOfSize:13],
    NSForegroundColorAttributeName:[NSColor colorWithWhite:1 alpha:.65]}];
  [@"Native window · no video · no Chromium" drawAtPoint:NSMakePoint(22, 20) withAttributes:@{
    NSFontAttributeName:[NSFont systemFontOfSize:11],
    NSForegroundColorAttributeName:[NSColor colorWithWhite:1 alpha:.45]}];
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
      std::max(area.origin.y, NSMaxY(area) - 928), 536, 900)
      styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
      backing:NSBackingStoreBuffered defer:NO];
  controls.title = @"Opus PiP Lab — live tuning";
  controls.delegate = self;
  controls.releasedWhenClosed = NO;
  NSView *content = controls.contentView;
  [content addSubview:label(@"Tune the movement", NSMakeRect(24, 856, 480, 28), 22)];
  NSTextField *intro = label(@"Drop slowly to leave it there; flick to dock. Push past a side to tuck.\nClick the exposed strip to restore. Re-grab an animation to interrupt it.",
      NSMakeRect(24, 805, 490, 44), 12);
  intro.textColor = NSColor.secondaryLabelColor;
  [content addSubview:intro];
  presetMenu = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(24, 769, 210, 28) pullsDown:NO];
  [presetMenu addItemsWithTitles:@[@"iOS-like baseline", @"Snappy", @"Soft spring", @"Position only", @"Custom"]];
  presetMenu.target = self; presetMenu.action = @selector(presetChanged:);
  [content addSubview:presetMenu];
  addHelp(content, NSMakeRect(238, 774, 18, 18), @"Presets",
      @"Loads a set of numeric tuning values while preserving your docking and placement modes.\n\n"
      "iOS-like baseline uses the defaults. Snappy uses a faster spring and shorter projection. Soft spring is slower with some bounce. Position only sets projection to zero. Custom means values were changed individually.\n\n"
      "Reset all variables also resets the docking and placement modes.");
  dockMenu = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(274, 769, 214, 28) pullsDown:NO];
  [dockMenu addItemsWithTitles:@[@"Dock at four corners", @"Dock anywhere on side edges"]];
  dockMenu.target = self; dockMenu.action = @selector(dockingChanged:);
  [content addSubview:dockMenu];
  addHelp(content, NSMakeRect(494, 774, 18, 18), @"Docking mode",
      @"Chooses the allowed resting destinations when a release snaps.\n\n"
      "Four corners: docks at a corner of the visible work area. Side edges: docks on the left or right while allowing any height.\n\n"
      "Momentum projection can choose a farther destination. Slow deliberate attraction uses the nearest dock.");
  placementMenu = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(24, 731, 288, 28) pullsDown:NO];
  [placementMenu addItemsWithTitles:@[@"Smart · slow drop stays, flick snaps", @"Always snap to dock", @"Always leave where dropped"]];
  placementMenu.target = self; placementMenu.action = @selector(placementChanged:);
  [content addSubview:placementMenu];
  addHelp(content, NSMakeRect(318, 736, 18, 18), @"Placement mode",
      @"Smart: slow releases stay where dropped unless near a dock; faster flicks snap using momentum.\n\n"
      "Always snap: every release docks. Always leave: releases stop where dropped, within the visible inset.\n\n"
      "Side tucking still works in every mode. The two attraction controls below tune Smart mode.");
  [self button:@"Reset all variables" frame:NSMakeRect(348, 731, 164, 28) action:@selector(resetVariables:) tag:0];
  sliders = NSMutableArray.array; fields = NSMutableArray.array;
  for (size_t i = 0; i < parameterCount; ++i) {
    CGFloat y = 686 - i * 40;
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
  NSBox *separator = [[NSBox alloc] initWithFrame:NSMakeRect(24, 272, 488, 1)];
  separator.boxType = NSBoxSeparator; [content addSubview:separator];
  feedbackToggle = [NSButton checkboxWithTitle:@"Release feedback" target:self action:@selector(feedbackToggled:)];
  feedbackToggle.frame = NSMakeRect(22, 242, 150, 20);
  [content addSubview:feedbackToggle];
  addHelp(content, NSMakeRect(160, 243, 18, 18), @"Release feedback",
      @"Quiet hints while you drag that show what letting go would do.\n\n"
      "A faint outline marks where the window will come to rest when it would snap or restore. No outline means it stays where you drop it. "
      "Outlines appear only while you move at or below “Leave here below speed”, so flicks stay uncluttered.\n\n"
      "Once letting go would tuck the window, it dims and shows its chevron. Pull it far enough to restore and it brightens again.\n\n"
      "Turn off to compare with no added feedback. The tucked chevron still appears.");
  feedbackSliders = NSMutableArray.array; feedbackFields = NSMutableArray.array;
  for (size_t i = 0; i < feedbackParameterCount; ++i) {
    const auto& parameter = feedbackParameters[i];
    CGFloat x = 24 + i * 166;
    NSTextField *heading = label(@(parameter.label), NSMakeRect(x, 213, 100, 18), 11);
    [heading sizeToFit]; [content addSubview:heading];
    addHelp(content, NSMakeRect(NSMaxX(heading.frame) + 4, 212, 18, 18), @(parameter.label), @(parameter.help));
    NSTextField *field = [[NSTextField alloc] initWithFrame:NSMakeRect(x + 104, 211, 50, 22)];
    field.tag = i; field.target = self; field.action = @selector(feedbackFieldChanged:);
    field.alignment = NSTextAlignmentRight;
    field.accessibilityLabel = [@(parameter.label) stringByAppendingString:@" value"];
    field.accessibilityHelp = @(parameter.help);
    [feedbackFields addObject:field]; [content addSubview:field];
    NSSlider *slider = [NSSlider sliderWithValue:feedback.*parameter.member minValue:parameter.low
        maxValue:parameter.high target:self action:@selector(feedbackSliderChanged:)];
    slider.frame = NSMakeRect(x, 186, 154, 22); slider.tag = i; slider.continuous = YES;
    slider.accessibilityLabel = @(parameter.label);
    slider.accessibilityHelp = @(parameter.help);
    [feedbackSliders addObject:slider]; [content addSubview:slider];
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
  panel.title = @"Opus PiP example";
  panel.opaque = NO; panel.backgroundColor = NSColor.clearColor;
  panel.hasShadow = YES; panel.hidesOnDeactivate = NO;
  panel.level = NSFloatingWindowLevel;
  panel.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces |
      NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorStationary;
  example = [[ExampleView alloc] initWithFrame:NSMakeRect(0, 0, 320, 180)];
  example.lab = self; example.wantsLayer = YES; panel.contentView = example;
  shade = [[ShadeView alloc] initWithFrame:example.bounds];
  shade.wantsLayer = YES; shade.alphaValue = 0;
  [example addSubview:shade];

  // Landing outline: a click-through frosted shape kept just below the PiP window.
  ghost = [[ExamplePanel alloc] initWithContentRect:panel.frame
      styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
      backing:NSBackingStoreBuffered defer:NO];
  ghost.opaque = NO; ghost.backgroundColor = NSColor.clearColor;
  ghost.hasShadow = NO; ghost.hidesOnDeactivate = NO; ghost.ignoresMouseEvents = YES;
  ghost.excludedFromWindowsMenu = YES; ghost.alphaValue = 0;
  ghost.level = NSFloatingWindowLevel;
  ghost.collectionBehavior = panel.collectionBehavior | NSWindowCollectionBehaviorIgnoresCycle |
      NSWindowCollectionBehaviorTransient;
  NSVisualEffectView *frost = [[NSVisualEffectView alloc] initWithFrame:example.bounds];
  frost.material = NSVisualEffectMaterialPopover;
  frost.blendingMode = NSVisualEffectBlendingModeBehindWindow;
  frost.state = NSVisualEffectStateActive;
  frost.maskImage = roundedMask(16);
  GhostOutline *outline = [[GhostOutline alloc] initWithFrame:frost.bounds];
  outline.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
  [frost addSubview:outline];
  ghost.contentView = frost;
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
  [ghost orderWindow:NSWindowBelow relativeTo:panel.windowNumber];
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
  feedbackToggle.state = feedback.enabled ? NSControlStateValueOn : NSControlStateValueOff;
  for (size_t i = 0; i < feedbackParameterCount; ++i) {
    double value = feedback.*feedbackParameters[i].member;
    feedbackSliders[i].doubleValue = value; feedbackSliders[i].enabled = feedback.enabled;
    feedbackFields[i].stringValue = [NSString stringWithFormat:@"%.2f", value];
    feedbackFields[i].enabled = feedback.enabled;
  }
}
- (void)scheduleSave {
  [saveTimer invalidate];
  saveTimer = [NSTimer scheduledTimerWithTimeInterval:.15 target:self selector:@selector(saveSettings) userInfo:nil repeats:NO];
}
- (void)apply:(Settings)settings save:(BOOL)save {
  motion->retune(settings); [self syncControls]; [self startAnimation];
  if (save) [self scheduleSave];
}
- (void)applyFeedback:(Feedback)next {
  feedback = next; [self syncControls]; [self scheduleSave];
  [self updateFeedback];
}
- (void)feedbackToggled:(NSButton *)sender {
  Feedback next = feedback; next.enabled = sender.state == NSControlStateValueOn;
  [self applyFeedback:next];
}
- (void)feedbackSliderChanged:(NSSlider *)sender {
  Feedback next = feedback; next.*feedbackParameters[sender.tag].member = sender.doubleValue;
  [self applyFeedback:next];
}
- (void)feedbackFieldChanged:(NSTextField *)sender {
  NSScanner *scanner = [NSScanner scannerWithString:sender.stringValue];
  double value;
  const auto& parameter = feedbackParameters[sender.tag];
  if (![scanner scanDouble:&value] || !scanner.isAtEnd || !std::isfinite(value) || value < parameter.low || value > parameter.high) {
    fileStatus.stringValue = [NSString stringWithFormat:@"Enter a value from %.2f to %.2f", parameter.low, parameter.high];
    [self syncControls]; return;
  }
  Feedback next = feedback; next.*parameter.member = value;
  [self applyFeedback:next];
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
  feedback = Feedback{};
  [self syncControls]; [presetMenu selectItemAtIndex:0];
  [self startAnimation]; [self saveSettings];
}
- (void)reveal:(id)sender { [NSWorkspace.sharedWorkspace activateFileViewerSelectingURLs:@[[NSURL fileURLWithPath:settingsPath]]]; }
- (pip_motion::Point)point:(NSEvent *)event {
  NSPoint p = [event.window convertPointToScreen:event.locationInWindow]; return {p.x, p.y};
}
- (void)noteEvent:(NSEvent *)event {
  lastEventTimestamp = event.timestamp;
  lastEventUptime = NSProcessInfo.processInfo.systemUptime;
}
// Event time advanced by local elapsed time, so a held pointer's velocity decays
// even when no further drag events arrive and event clocks differ from uptime.
- (double)dragTime {
  return lastEventTimestamp + (NSProcessInfo.processInfo.systemUptime - lastEventUptime);
}
- (void)begin:(NSEvent *)event {
  [self stopAnimation]; [self noteEvent:event];
  motion->begin([self point:event], event.timestamp); [self showPosition];
  [dragTimer invalidate];
  dragTimer = [NSTimer timerWithTimeInterval:1.0/60 target:self selector:@selector(dragTick:) userInfo:nil repeats:YES];
  [NSRunLoop.mainRunLoop addTimer:dragTimer forMode:NSRunLoopCommonModes];
}
- (void)drag:(NSEvent *)event {
  [self noteEvent:event];
  motion->drag([self point:event], event.timestamp); [self showPosition];
}
- (void)end:(NSEvent *)event {
  [dragTimer invalidate]; dragTimer = nil;
  motion->end(event.timestamp); [self startAnimation];
}
- (void)dragTick:(NSTimer *)timer {
  if (motion->phase != Phase::Dragging) { [dragTimer invalidate]; dragTimer = nil; }
  [self updateFeedback];
}
- (NSString *)dockName:(pip_motion::Point)target {
  const auto area = motion->area();
  const bool left = target.x + motion->size.width / 2 < area.x + area.width / 2;
  if (motion->settings.docking == Docking::SideEdges) return left ? @"left edge" : @"right edge";
  const bool top = target.y + motion->size.height / 2 > area.y + area.height / 2;
  return [NSString stringWithFormat:@"%@-%@ corner", top ? @"top" : @"bottom", left ? @"left" : @"right"];
}
- (void)updateFeedback {
  const bool dragging = motion->phase == Phase::Dragging;
  const Outcome outcome = dragging ? motion->predict([self dragTime]) : Outcome{};
  bool tuckLook = motion->tucked != Side::None;
  Side side = motion->tucked;
  bool showGhost = false;
  // A press that has not moved the window is a click; its release is feedback enough.
  if (feedback.enabled && dragging && outcome.moved) {
    tuckLook = outcome.decision == Decision::Tuck;
    side = outcome.side;
    // Hysteresis keeps the outline steady while speed hovers around the threshold.
    const double gate = motion->settings.free_speed;
    const double hide = gate + std::max(60.0, gate / 2);
    showGhost = (outcome.decision == Decision::Dock || outcome.decision == Decision::Restore) &&
        outcome.speed <= (ghostShown ? hide : gate) && feedback.outline > 0;
  }
  const double fade = feedback.enabled ? feedback.fade : 0;
  const CGFloat dim = feedback.enabled ? feedback.dim : 0;
  if (dim != shade.dim) { shade.dim = dim; shade.needsDisplay = YES; }
  if (tuckLook && side != shade.side) { shade.side = side; shade.needsDisplay = YES; }
  if (tuckLook != shadeShown) { shadeShown = tuckLook; fadeTo(shade, tuckLook ? 1 : 0, fade); }
  if (showGhost) {
    NSRect frame = NSMakeRect(outcome.target.x, outcome.target.y, motion->size.width, motion->size.height);
    if (!NSEqualRects(frame, ghost.frame)) [ghost setFrame:frame display:YES];
    if (!ghostShown) [ghost orderWindow:NSWindowBelow relativeTo:panel.windowNumber];
  }
  ghostShown = showGhost;
  const CGFloat alpha = showGhost ? feedback.outline : 0;
  if (alpha != ghostAlpha) { ghostAlpha = alpha; fadeTo(ghost, alpha, fade); }
  if (!dragging) return;
  switch (outcome.decision) {
    case Decision::Keep:
      explanation.stringValue = [NSString stringWithFormat:@"Release now: stays here · moving %.0f pt/s", outcome.speed]; break;
    case Decision::Dock:
      explanation.stringValue = [NSString stringWithFormat:@"Release now: snaps to the %@ · moving %.0f pt/s%@",
          [self dockName:outcome.target], outcome.speed, showGhost ? @" · outline shown" : @""]; break;
    case Decision::Tuck:
      explanation.stringValue = outcome.side == Side::Left ? @"Release now: tucks into the left edge" :
          @"Release now: tucks into the right edge"; break;
    case Decision::Restore:
      explanation.stringValue = @"Release now: restores to the side"; break;
    case Decision::None: break;
  }
}
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
  [self updateFeedback];
  // The state file is an observable checkpoint, not a frame-by-frame trace.
  if (motion->phase != Phase::Settling && motion->phase != Phase::Dragging) [self writeState];
}
- (NSDictionary *)settingsDictionary {
  NSMutableDictionary *dict = [@{@"version":@1, @"docking":motion->settings.docking == Docking::Corners ? @"corners" : @"edges"} mutableCopy];
  dict[@"placement"] = @[@"smart", @"always-dock", @"free"][static_cast<NSInteger>(motion->settings.placement)];
  for (const auto& parameter : parameters) dict[@(parameter.key)] = @(motion->settings.*parameter.member);
  dict[@"feedback"] = feedback.enabled ? @YES : @NO;
  for (const auto& parameter : feedbackParameters) dict[@(parameter.key)] = @(feedback.*parameter.member);
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
  BOOL migratedTuckDistance = NO;
  if (valid && !dict[@"stash_percent"] && dict[@"stash_distance"]) {
    id legacy = dict[@"stash_distance"];
    BOOL numeric = [legacy isKindOfClass:NSNumber.class] &&
        CFGetTypeID((__bridge CFTypeRef)legacy) != CFBooleanGetTypeID();
    double points = numeric ? [legacy doubleValue] : NAN;
    if (!std::isfinite(points) || points < 20 || points > 160) valid = NO;
    else {
      NSMutableDictionary *converted = [dict mutableCopy];
      converted[@"stash_percent"] = @(100 * points / motion->size.width);
      [converted removeObjectForKey:@"stash_distance"];
      dict = converted;
      migratedTuckDistance = YES;
    }
  }
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
  Feedback nextFeedback;
  id enabled = dict[@"feedback"];
  if (enabled && !([enabled isKindOfClass:NSNumber.class] &&
                   CFGetTypeID((__bridge CFTypeRef)enabled) == CFBooleanGetTypeID())) valid = NO;
  else if (enabled) nextFeedback.enabled = [enabled boolValue];
  for (const auto& parameter : feedbackParameters) {
    id value = dict[@(parameter.key)];
    if (!value) continue;
    BOOL numeric = [value isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)value) != CFBooleanGetTypeID();
    double number = numeric ? [value doubleValue] : NAN;
    if (!std::isfinite(number) || number < parameter.low || number > parameter.high) valid = NO;
    else nextFeedback.*parameter.member = number;
  }
  if (!valid) {
    fileStatus.stringValue = @"Invalid settings file · keeping the last valid values"; return;
  }
  next.docking = [dict[@"docking"] isEqual:@"corners"] ? Docking::Corners : Docking::SideEdges;
  [saveTimer invalidate]; saveTimer = nil;
  feedback = nextFeedback;
  [presetMenu selectItemAtIndex:4]; [self apply:next save:NO];
  if (migratedTuckDistance) [self saveSettings];
  else fileStatus.stringValue = @"Reloaded JSON · all controls are live";
}
- (void)checkFile:(NSTimer *)timer { [self reloadSettings]; }
- (void)windowWillClose:(NSNotification *)notification { [NSApp terminate:nil]; }
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender { return YES; }
- (void)applicationWillTerminate:(NSNotification *)notification {
  [self stopAnimation]; [fileTimer invalidate]; [saveTimer invalidate]; [dragTimer invalidate];
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
    [appMenu.submenu addItemWithTitle:@"Quit Opus PiP Lab" action:@selector(terminate:) keyEquivalent:@"q"];
    app.mainMenu = menu;
    MotionLab *delegate = [[MotionLab alloc] initWithSettingsPath:path];
    app.delegate = delegate; [app run];
  }
  return 0;
}

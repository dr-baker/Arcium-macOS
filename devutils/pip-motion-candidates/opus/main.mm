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
  bool haptics = true;
  double lift = .70;
  double settle = .60;
  double press = .60;
  double glow = 0;
  double edge = .60;
  double lean = 14;
  double dockShadow = .80;
};
struct FeedbackParameter {
  const char *key, *label;
  double low, high;
  double Feedback::*member;
  const char *help;
};
static const FeedbackParameter feedbackParameters[] = {
  {"feedback_lift", "Lift", 0, 1, &Feedback::lift,
    "How much the shadow grows and softens when you pick the window up.\n\n"
    "After release, the window stays lifted while it travels and sets down as it arrives.\n\n"
    "Zero keeps the resting shadow."},
  {"feedback_settle", "Settle", 0, 1, &Feedback::settle,
    "How far the window lowers toward the desk while letting go would leave it where it is.\n\n"
    "The shadow tightens and the shrink eases off, as if you are setting it down. Releasing finishes the motion.\n\n"
    "Zero keeps it fully lifted until release."},
  {"feedback_press", "Press", 0, 1, &Feedback::press,
    "How much the window dips and springs back when it lands after you let go, like setting a cup on a table.\n\n"
    "Applies when it stays put and when it arrives at a dock, tuck or restore. Zero turns it off."},
  {"feedback_glow", "Hold glow", 0, 1, &Feedback::glow,
    "How brightly the border glows while letting go would leave the window where it is.\n\n"
    "In Smart mode it appears as you slow down away from a dock. Zero turns it off."},
  {"feedback_edge", "Edge shade", 0, 1, &Feedback::edge,
    "How dark the shadow cast by the screen's rim gets on the part of the window going into a side.\n\n"
    "It starts faint as you push in, deepens once letting go would tuck, and stays while tucked. Zero leaves only the chevron."},
  {"feedback_lean", "Dock lean", 0, 40, &Feedback::lean,
    "How far, in points, the window leans toward the dock it would snap to, with its shadow cast further toward it.\n\n"
    "The pull builds as you get close to a dock, or anywhere while you move slowly enough to snap.\n\n"
    "Zero turns the lean off. Reduce Motion also turns it off."},
  {"feedback_dock_shadow", "Dock shadow", 0, 1, &Feedback::dockShadow,
    "How far the window's shadow slides toward the dock it would snap to, up to 110 points.\n\n"
    "At 1 the shadow sits on the destination while the window hovers where you hold it. It builds with proximity, and is full while you move slowly enough to snap.\n\n"
    "Zero keeps the shadow under the window."},
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

// The panel is padded so the window can draw its own shadow; only the card takes clicks.
static constexpr CGFloat kPad = 200;

@interface PassView : NSView
@end
@implementation PassView
- (NSView *)hitTest:(NSPoint)point { return nil; }
@end

@interface RootView : NSView
@end
@implementation RootView
- (NSView *)hitTest:(NSPoint)point {
  NSView *hit = [super hitTest:point];
  return hit == self ? nil : hit;
}
@end

static CGColorRef gray(CGFloat white, CGFloat alpha) {
  return [NSColor colorWithWhite:white alpha:alpha].CGColor;
}
static double smoothstep(double x) {
  x = std::clamp(x, 0.0, 1.0);
  return x * x * (3 - 2 * x);
}
// Frame-rate independent exponential approach with separate rise and fall times.
static void approach(double& value, double target, double rise, double fall, double dt) {
  const double tau = target > value ? rise : fall;
  value = target + (value - target) * std::exp(-dt / tau);
  if (std::abs(value - target) < 1e-3) value = target;
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
  NSTimer *animationTimer, *fileTimer, *saveTimer, *visualTimer;
  double lastTick;
  NSString *settingsPath, *statePath;
  NSData *lastSettingsData;
  Feedback feedback;
  CALayer *stage, *ambientShadow, *contactShadow, *glowShadow, *overlay;
  CAGradientLayer *rimShade;
  CAShapeLayer *chevron, *rimLight;
  CATextLayer *intentText, *cueText;
  NSButton *feedbackToggle, *hapticsToggle;
  NSMutableArray<NSSlider *> *feedbackSliders;
  NSMutableArray<NSTextField *> *feedbackFields;
  double lift, glow, edgeAmount, leanX, leanY, shadowX, shadowY, lastVisualTime, releaseDistance, rimShadeStrength;
  Side chevronSide;
  BOOL leaning, awaitingLanding;
  double pressStart, lastHaptic, pendingSince;
  int hapticKey, pendingKey;
  Outcome stableOutcome;
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
@end

// The card artwork, rendered once into a layer so the whole card can scale with its shadow.
static void drawCard(NSRect bounds) {
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
}

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
    CGFloat y = 686 - i * 38;
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
  NSBox *separator = [[NSBox alloc] initWithFrame:NSMakeRect(24, 296, 488, 1)];
  separator.boxType = NSBoxSeparator; [content addSubview:separator];
  feedbackToggle = [NSButton checkboxWithTitle:@"Release feedback" target:self action:@selector(feedbackToggled:)];
  feedbackToggle.frame = NSMakeRect(22, 268, 150, 20);
  [content addSubview:feedbackToggle];
  hapticsToggle = [NSButton checkboxWithTitle:@"Haptics" target:self action:@selector(hapticsToggled:)];
  hapticsToggle.frame = NSMakeRect(206, 268, 80, 20);
  [content addSubview:hapticsToggle];
  addHelp(content, NSMakeRect(282, 269, 18, 18), @"Haptics",
      @"Force Touch trackpad taps for every event: pickup, each change in what letting go would do, and landing.\n\n"
      "Every tap uses the lightest alignment pattern, at most one every 0.15 seconds.\n\n"
      "macOS only plays haptics while a finger is on the trackpad, so a landing after a long flight may be silent. Mice have no haptics.");
  addHelp(content, NSMakeRect(160, 269, 18, 18), @"Release feedback",
      @"Physical cues for holding and letting go.\n\n"
      "Picking the window up deepens and softens its shadow and shrinks it slightly. After release it stays lifted while it travels, sets down where it comes to rest, and dips once as it lands.\n\n"
      "While letting go would leave it where it is, it lowers toward the desk. Near a dock it would snap to, it leans toward the dock and casts its shadow that way.\n\n"
      "Pushed into a side, the screen's rim casts a shadow on the part going in, and the chevron fades in with depth. The shadow deepens once letting go would tuck.\n\n"
      "Turn off to compare with no added feedback. The tucked chevron still appears.");
  feedbackSliders = NSMutableArray.array; feedbackFields = NSMutableArray.array;
  for (size_t i = 0; i < feedbackParameterCount; ++i) {
    const auto& parameter = feedbackParameters[i];
    CGFloat x = 24 + (i % 4) * 124, row = i < 4 ? 220 : 172;
    NSTextField *heading = label(@(parameter.label), NSMakeRect(x, row + 24, 100, 18), 11);
    [heading sizeToFit]; [content addSubview:heading];
    addHelp(content, NSMakeRect(NSMaxX(heading.frame) + 4, row + 23, 18, 18), @(parameter.label), @(parameter.help));
    NSTextField *field = [[NSTextField alloc] initWithFrame:NSMakeRect(x + 72, row, 42, 22)];
    field.tag = i; field.target = self; field.action = @selector(feedbackFieldChanged:);
    field.alignment = NSTextAlignmentRight;
    field.accessibilityLabel = [@(parameter.label) stringByAppendingString:@" value"];
    field.accessibilityHelp = @(parameter.help);
    [feedbackFields addObject:field]; [content addSubview:field];
    NSSlider *slider = [NSSlider sliderWithValue:feedback.*parameter.member minValue:parameter.low
        maxValue:parameter.high target:self action:@selector(feedbackSliderChanged:)];
    slider.frame = NSMakeRect(x, row, 66, 22); slider.tag = i; slider.continuous = YES;
    slider.accessibilityLabel = @(parameter.label);
    slider.accessibilityHelp = @(parameter.help);
    [feedbackSliders addObject:slider]; [content addSubview:slider];
  }
  explanation = label(@"", NSMakeRect(24, 147, 488, 22), 11);
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

  const CGFloat w = motion->size.width, h = motion->size.height;
  const CGRect card = CGRectMake(kPad, kPad, w, h);
  panel = [[ExamplePanel alloc] initWithContentRect:NSMakeRect(motion->position.x - kPad,
      motion->position.y - kPad, w + 2 * kPad, h + 2 * kPad)
      styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
      backing:NSBackingStoreBuffered defer:NO];
  panel.title = @"Opus PiP example";
  panel.opaque = NO; panel.backgroundColor = NSColor.clearColor;
  panel.hasShadow = NO; panel.hidesOnDeactivate = NO;
  panel.level = NSFloatingWindowLevel;
  panel.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces |
      NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorStationary;
  RootView *root = [[RootView alloc] initWithFrame:NSMakeRect(0, 0, w + 2 * kPad, h + 2 * kPad)];
  root.wantsLayer = YES; panel.contentView = root;
  const CGFloat scale = screen.backingScaleFactor;
  // One stage holds the shadows, card and overlay so they lift and scale together.
  PassView *host = [[PassView alloc] initWithFrame:root.bounds];
  host.layer = [CALayer layer]; host.wantsLayer = YES;
  [root addSubview:host];
  stage = [CALayer layer];
  stage.bounds = CGRectMake(0, 0, w, h);
  stage.position = CGPointMake(CGRectGetMidX(card), CGRectGetMidY(card));
  [host.layer addSublayer:stage];
  CGPathRef shape = CGPathCreateWithRoundedRect(stage.bounds, 16, 16, nullptr);
  auto shadowLayer = [&](CGColorRef color) {
    CALayer *layer = [CALayer layer];
    layer.frame = stage.bounds; layer.shadowPath = shape; layer.shadowColor = color;
    layer.shadowOpacity = 0;
    [stage addSublayer:layer];
    return layer;
  };
  glowShadow = shadowLayer(gray(1, 1));
  ambientShadow = shadowLayer(gray(0, 1));
  contactShadow = shadowLayer(gray(0, 1));
  glowShadow.shadowOffset = CGSizeZero; glowShadow.shadowRadius = 8;
  CGPathRelease(shape);
  NSImage *artwork = [NSImage imageWithSize:NSMakeSize(w, h) flipped:NO drawingHandler:^BOOL(NSRect rect) {
    drawCard(rect); return YES;
  }];
  CALayer *cardLayer = [CALayer layer];
  cardLayer.frame = stage.bounds; cardLayer.contentsScale = scale;
  cardLayer.contents = [artwork layerContentsForContentsScale:scale];
  [stage addSublayer:cardLayer];

  // Live readout on the card: what release would do, and which cues are animating.
  auto textLayer = [&](CGRect frame, NSFont *font, CGFloat alpha) {
    CATextLayer *text = [CATextLayer layer];
    text.frame = frame; text.contentsScale = scale;
    text.font = (__bridge CFTypeRef)font; text.fontSize = font.pointSize;
    text.foregroundColor = gray(1, alpha); text.truncationMode = kCATruncationEnd;
    text.string = @"";
    [stage addSublayer:text];
    return text;
  };
  intentText = textLayer(CGRectMake(22, 86, w - 44, 20), [NSFont systemFontOfSize:13 weight:NSFontWeightMedium], .8);
  cueText = textLayer(CGRectMake(22, 16, w - 44, 16), [NSFont monospacedDigitSystemFontOfSize:11 weight:NSFontWeightRegular], .55);

  // Overlay on the card: the screen rim's shadow, the chevron and the glowing border.
  overlay = [CALayer layer];
  overlay.frame = stage.bounds; overlay.cornerRadius = 16; overlay.masksToBounds = YES;
  [stage addSublayer:overlay];
  rimShade = [CAGradientLayer layer];
  rimShade.opacity = 0;
  NSMutableArray *stops = NSMutableArray.array;
  for (int i = 0; i < 16; ++i) [stops addObject:@(i / 15.0)];
  rimShade.locations = stops;
  [overlay addSublayer:rimShade];
  chevron = [CAShapeLayer layer];
  chevron.bounds = CGRectMake(0, 0, 10, 18); chevron.contentsScale = scale;
  chevron.fillColor = nil; chevron.strokeColor = gray(1, 1);
  chevron.lineWidth = 2; chevron.lineCap = kCALineCapRound; chevron.lineJoin = kCALineJoinRound;
  chevron.opacity = 0;
  [overlay addSublayer:chevron];
  rimLight = [CAShapeLayer layer];
  rimLight.frame = overlay.bounds; rimLight.contentsScale = scale;
  CGPathRef rim = CGPathCreateWithRoundedRect(CGRectInset(overlay.bounds, .75, .75), 15.25, 15.25, nullptr);
  rimLight.path = rim; CGPathRelease(rim);
  rimLight.fillColor = nil; rimLight.strokeColor = gray(1, .9); rimLight.lineWidth = 1.5;
  rimLight.opacity = 0;
  [overlay addSublayer:rimLight];

  // Transparent, unscaled event target over the card.
  example = [[ExampleView alloc] initWithFrame:NSRectFromCGRect(card)];
  example.lab = self;
  [root addSubview:example];
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
  feedbackToggle.state = feedback.enabled ? NSControlStateValueOn : NSControlStateValueOff;
  hapticsToggle.state = feedback.haptics ? NSControlStateValueOn : NSControlStateValueOff;
  hapticsToggle.enabled = feedback.enabled;
  for (size_t i = 0; i < feedbackParameterCount; ++i) {
    double value = feedback.*feedbackParameters[i].member;
    feedbackSliders[i].doubleValue = value; feedbackSliders[i].enabled = feedback.enabled;
    feedbackFields[i].stringValue = [NSString stringWithFormat:feedbackParameters[i].high > 1 ? @"%.1f" : @"%.2f", value];
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
  [self wakeVisuals]; [self updateVisuals];
}
- (void)feedbackToggled:(NSButton *)sender {
  Feedback next = feedback; next.enabled = sender.state == NSControlStateValueOn;
  [self applyFeedback:next];
}
- (void)hapticsToggled:(NSButton *)sender {
  Feedback next = feedback; next.haptics = sender.state == NSControlStateValueOn;
  [self applyFeedback:next];
  [self haptic:NSHapticFeedbackPatternAlignment];
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
  releaseDistance = 0; awaitingLanding = NO;
  motion->throwFrom(motion->centerOrigin(), v, false); [self startAnimation];
}
- (void)replay:(id)sender { releaseDistance = 0; awaitingLanding = NO; motion->replay(); [self startAnimation]; }
- (void)toggleTuck:(id)sender {
  releaseDistance = 0; awaitingLanding = NO;
  if (motion->tucked != Side::None) motion->restore(); else motion->tuck(Side::None);
  [self startAnimation];
}
- (void)reset:(id)sender { releaseDistance = 0; awaitingLanding = NO; motion->reset(); [self showPosition]; [self stopAnimation]; }
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
  awaitingLanding = NO; hapticKey = pendingKey = -1;
  motion->begin([self point:event], event.timestamp);
  [self haptic:NSHapticFeedbackPatternAlignment];
  [self showPosition];
}
- (void)drag:(NSEvent *)event {
  [self noteEvent:event];
  motion->drag([self point:event], event.timestamp); [self showPosition];
}
- (void)end:(NSEvent *)event {
  motion->end(event.timestamp);
  releaseDistance = length(motion->target - motion->position);
  awaitingLanding = YES;
  [self startAnimation];
}
- (void)haptic:(NSHapticFeedbackPattern)pattern {
  const double now = NSProcessInfo.processInfo.systemUptime;
  if (!feedback.enabled || !feedback.haptics || now - lastHaptic < .15) return;
  lastHaptic = now;
  [NSHapticFeedbackManager.defaultPerformer performFeedbackPattern:pattern
      performanceTime:NSHapticFeedbackPerformanceTimeNow];
}
// Identity of a release outcome for haptics: decision, side and which dock.
- (int)hapticKeyFor:(const Outcome &)outcome {
  int key = static_cast<int>(outcome.decision) * 100 + static_cast<int>(outcome.side) * 10;
  if (outcome.decision == Decision::Dock) {
    const auto area = motion->area();
    key += outcome.target.x + motion->size.width / 2 < area.x + area.width / 2;
    if (motion->settings.docking == Docking::Corners)
      key += 2 * (outcome.target.y + motion->size.height / 2 > area.y + area.height / 2);
  }
  return key;
}
- (void)land {
  awaitingLanding = NO;
  pressStart = NSProcessInfo.processInfo.systemUptime;
  [self haptic:NSHapticFeedbackPatternAlignment];
  [self wakeVisuals];
}
- (NSString *)dockName:(pip_motion::Point)target {
  const auto area = motion->area();
  const bool left = target.x + motion->size.width / 2 < area.x + area.width / 2;
  if (motion->settings.docking == Docking::SideEdges) return left ? @"left edge" : @"right edge";
  const bool top = target.y + motion->size.height / 2 > area.y + area.height / 2;
  return [NSString stringWithFormat:@"%@-%@ corner", top ? @"top" : @"bottom", left ? @"left" : @"right"];
}
- (void)wakeVisuals {
  if (visualTimer) return;
  lastVisualTime = NSProcessInfo.processInfo.systemUptime;
  visualTimer = [NSTimer timerWithTimeInterval:1.0/120 target:self selector:@selector(visualTick:) userInfo:nil repeats:YES];
  [NSRunLoop.mainRunLoop addTimer:visualTimer forMode:NSRunLoopCommonModes];
}
- (void)visualTick:(NSTimer *)timer {
  if ([self updateVisuals] && motion->phase != Phase::Dragging && motion->phase != Phase::Settling) {
    [visualTimer invalidate]; visualTimer = nil;
  }
}
// Physical cues derived from the release prediction: lift, hold glow, rim shadow and dock lean.
// Returns YES once every smoothed value has reached its target.
- (BOOL)updateVisuals {
  const double now = NSProcessInfo.processInfo.systemUptime;
  const double dt = std::clamp(now - lastVisualTime, 0.0, .05);
  lastVisualTime = now;
  const bool on = feedback.enabled;
  const bool dragging = motion->phase == Phase::Dragging;
  const Outcome outcome = dragging ? motion->predict([self dragTime]) : Outcome{};
  // A press that has not moved the window is a click: it lifts, but previews nothing.
  const bool moved = dragging && outcome.moved;
  const auto area = motion->area();
  const pip_motion::Point position = motion->position;
  const double w = motion->size.width, h = motion->size.height, handle = motion->settings.handle;

  // Cues and haptics follow a debounced outcome so threshold chatter (speed hovering at the
  // deliberate limit, or position at a snap or tuck boundary) does not flicker the window.
  Outcome shown = outcome;
  if (moved) {
    const int key = [self hapticKeyFor:outcome];
    if (hapticKey < 0) { hapticKey = pendingKey = key; stableOutcome = outcome; }
    if (key != pendingKey) { pendingKey = key; pendingSince = now; }
    else if (key != hapticKey && now - pendingSince >= .1) {
      [self haptic:NSHapticFeedbackPatternAlignment];
      hapticKey = key;
    }
    if (key == hapticKey) stableOutcome = outcome;
    shown = stableOutcome;
    if (shown.decision == outcome.decision) { shown.target = outcome.target; shown.side = outcome.side; }
  }
  const bool keep = moved && shown.decision == Decision::Keep;
  double liftTarget = 0;
  // Held where it will stay, the window lowers toward the desk; release finishes setting it down.
  if (dragging) liftTarget = keep ? 1 - feedback.settle : 1;
  else if (motion->phase == Phase::Settling && releaseDistance > 1)
    liftTarget = std::sqrt(std::clamp(length(motion->target - position) / releaseDistance, 0.0, 1.0));
  const double glowTarget = keep ? 1 : 0;

  // Magnetic pull toward the dock release would snap to: it builds with proximity, and is full
  // whenever the drag is slow enough to snap. Hysteresis steadies the slow-speed gate.
  const double gate = motion->settings.free_speed;
  const bool slow = outcome.speed <= (leaning ? gate + std::max(60.0, gate / 2) : gate);
  pip_motion::Point leanTarget{}, shadowTarget{};
  leaning = false;
  if (on && moved && shown.decision == Decision::Dock &&
      !NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion) {
    const pip_motion::Point toward = shown.target - position;
    const double distance = length(toward);
    const double reach = 2 * std::max(motion->settings.snap_distance, 48.0);
    const double engage = std::max(slow ? 1.0 : 0.0, smoothstep(1 - distance / reach));
    if (engage > 0 && distance > .5) {
      leaning = true;
      leanTarget = toward * (engage * std::min(feedback.lean, distance * .6) / distance);
      // The shadow slides toward the destination, as if already resting there.
      shadowTarget = toward * (engage * feedback.dockShadow * std::min(110.0, distance) / distance);
    }
  }

  // The screen rim casts a shadow on the part of the window going into a side.
  const double leftOver = area.x - position.x;
  const double rightOver = position.x + w - area.x - area.width;
  Side side = moved && shown.decision == Decision::Tuck ? shown.side :
      motion->tucked != Side::None ? motion->tucked : leftOver > rightOver ? Side::Left : Side::Right;
  const double over = side == Side::Left ? leftOver : rightOver;
  const double depth = std::clamp(over / std::max(1.0, w - handle), 0.0, 1.0);
  const double tuckDistance = std::max(1.0, w * motion->settings.stash_percent / 100);
  const bool committed = moved ? shown.decision == Decision::Tuck : motion->tucked != Side::None;
  const double edgeTarget = committed ? .7 + .3 * depth : .28 * smoothstep(over / tuckDistance);

  approach(lift, on ? liftTarget : 0, .07, .14, dt);
  approach(glow, on ? glowTarget : 0, .09, .14, dt);
  approach(edgeAmount, on ? edgeTarget : 0, .12, .14, dt);
  approach(leanX, leanTarget.x, .08, .10, dt);
  approach(leanY, leanTarget.y, .08, .10, dt);
  approach(shadowX, shadowTarget.x, .26, .16, dt);
  approach(shadowY, shadowTarget.y, .26, .16, dt);

  [CATransaction begin];
  [CATransaction setDisableActions:YES];
  const CGRect card = CGRectMake(kPad + leanX, kPad + leanY, w, h);
  if (!NSEqualPoints(example.frame.origin, NSPointFromCGPoint(card.origin))) [example setFrameOrigin:card.origin];
  // Lifting grows and softens the shadow while the card shrinks slightly with it.
  const double l = lift * feedback.lift;
  // A landing dips the card once and springs back.
  const double pressAge = now - pressStart, pressTime = .24;
  const bool pressing = on && pressAge >= 0 && pressAge < pressTime;
  const double dip = pressing ? .02 * feedback.press * (1 - std::cos(2 * M_PI * pressAge / pressTime)) / 2 : 0;
  const double cardScale = (1 - .025 * l) * (1 - dip);
  stage.position = CGPointMake(CGRectGetMidX(card), CGRectGetMidY(card));
  stage.transform = CATransform3DMakeScale(cardScale, cardScale, 1);
  ambientShadow.shadowRadius = 18 + 14 * l;
  ambientShadow.shadowOpacity = .30 + .06 * l;
  ambientShadow.shadowOffset = CGSizeMake(shadowX, -(8 + 10 * l) + shadowY);
  contactShadow.shadowRadius = 4 + 3 * l;
  contactShadow.shadowOpacity = .16 * (1 - .75 * l);
  contactShadow.shadowOffset = CGSizeMake(leanX * .5, -(2 + 2 * l) + leanY * .5);
  glowShadow.shadowOpacity = .45 * glow * feedback.glow;
  rimLight.opacity = .6 * glow * feedback.glow;

  // Screen edge in card coordinates, accounting for lean and the lift scale about the card's center.
  const double rimScreen = side == Side::Left ? area.x : area.x + area.width;
  const double rim = w / 2 + (rimScreen - (position.x + leanX + w / 2)) / cardScale;
  const double reach = std::max(88.0, handle * 3);
  if (rimShadeStrength != feedback.edge || !rimShade.colors) {
    // Exponential falloff: dense at the rim with a long, soft tail and no visible stop.
    rimShadeStrength = feedback.edge;
    NSMutableArray *colors = NSMutableArray.array;
    for (int i = 0; i < 16; ++i) {
      const double t = i / 15.0;
      const double falloff = (std::exp(-3.2 * t) - std::exp(-3.2)) / (1 - std::exp(-3.2));
      [colors addObject:(__bridge id)gray(0, feedback.edge * falloff)];
    }
    rimShade.colors = colors;
  }
  rimShade.frame = side == Side::Left ? CGRectMake(rim, 0, reach, h) : CGRectMake(rim - reach, 0, reach, h);
  rimShade.startPoint = CGPointMake(side == Side::Left ? 0 : 1, .5);
  rimShade.endPoint = CGPointMake(side == Side::Left ? 1 : 0, .5);
  rimShade.opacity = edgeAmount;

  // The chevron stays where it rests once tucked, centered in the visible strip, and only fades in.
  Side chevronTarget = on ? side : motion->tucked;
  double chevronAlpha = on ? std::pow(edgeAmount, 1.3) : motion->tucked != Side::None;
  double chevronX = (chevronTarget == Side::Left ? w - handle / 2 : handle / 2);
  if (chevronTarget != Side::None && chevronTarget != chevronSide) {
    chevronSide = chevronTarget;
    CGMutablePathRef path = CGPathCreateMutable();
    const bool left = chevronSide == Side::Left;
    CGPathMoveToPoint(path, nullptr, left ? 2 : 8, 2);
    CGPathAddLineToPoint(path, nullptr, left ? 8 : 2, 9);
    CGPathAddLineToPoint(path, nullptr, left ? 2 : 8, 16);
    chevron.path = path; CGPathRelease(path);
  }
  chevron.position = CGPointMake(chevronX, 90);
  chevron.opacity = chevronAlpha;

  NSString *intent;
  auto describe = [&](Decision decision, Side tuckSide, pip_motion::Point target, NSString *prefix) {
    switch (decision) {
      case Decision::Keep: return [prefix stringByAppendingString:@"stay here"];
      case Decision::Dock: return [prefix stringByAppendingFormat:@"snap to the %@", [self dockName:target]];
      case Decision::Tuck: return [prefix stringByAppendingString:tuckSide == Side::Left ? @"tuck left" : @"tuck right"];
      case Decision::Restore: return [prefix stringByAppendingString:@"restore"];
      case Decision::None: return prefix;
    }
  };
  if (dragging) intent = moved ? describe(shown.decision, shown.side, shown.target, @"Release → ") : @"Picked up";
  else if (motion->phase == Phase::Settling)
    intent = describe(motion->decision, motion->tucked, motion->target, @"Settling → ");
  else if (motion->phase == Phase::Tucked) intent = motion->tucked == Side::Left ? @"Tucked left" : @"Tucked right";
  else intent = pressing ? @"Landed" : @"Resting";
  NSMutableArray<NSString *> *cues = NSMutableArray.array;
  if (!on) [cues addObject:@"Feedback off"];
  if (l > .01) [cues addObject:[NSString stringWithFormat:@"lift %.0f%%", l * 100]];
  if (keep && feedback.settle > 0) [cues addObject:@"lowered"];
  if (std::hypot(leanX, leanY) > .5) [cues addObject:[NSString stringWithFormat:@"lean %.0f pt", std::hypot(leanX, leanY)]];
  if (std::hypot(shadowX, shadowY) > .5) [cues addObject:[NSString stringWithFormat:@"shadow → %.0f pt", std::hypot(shadowX, shadowY)]];
  if (edgeAmount > .01 && feedback.edge > 0) [cues addObject:[NSString stringWithFormat:@"rim %.0f%%", edgeAmount * 100]];
  if (glow > .01 && feedback.glow > 0) [cues addObject:@"glow"];
  if (dip > 0) [cues addObject:@"press"];
  NSString *cueLine = cues.count ? [cues componentsJoinedByString:@" · "] : @"no cues";
  if (![intentText.string isEqual:intent]) intentText.string = intent;
  if (![cueText.string isEqual:cueLine]) cueText.string = cueLine;
  [CATransaction commit];

  if (dragging) {
    switch (outcome.decision) {
      case Decision::Keep:
        explanation.stringValue = [NSString stringWithFormat:@"Release now: stays here · moving %.0f pt/s", outcome.speed]; break;
      case Decision::Dock:
        explanation.stringValue = [NSString stringWithFormat:@"Release now: snaps to the %@ · moving %.0f pt/s%@",
            [self dockName:outcome.target], outcome.speed, leaning ? @" · leaning" : @""]; break;
      case Decision::Tuck:
        explanation.stringValue = outcome.side == Side::Left ? @"Release now: tucks into the left edge" :
            @"Release now: tucks into the right edge"; break;
      case Decision::Restore:
        explanation.stringValue = @"Release now: restores to the side"; break;
      case Decision::None: break;
    }
  }
  return !pressing && lift == (on ? liftTarget : 0) && glow == (on ? glowTarget : 0) &&
      edgeAmount == (on ? edgeTarget : 0) && leanX == leanTarget.x && leanY == leanTarget.y &&
      shadowX == shadowTarget.x && shadowY == shadowTarget.y;
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
  if (motion->phase != Phase::Settling && awaitingLanding) [self land];
  [self showPosition];
  if (motion->phase != Phase::Settling) [self stopAnimation];
}
- (void)showPosition {
  [panel setFrameOrigin:NSMakePoint(motion->position.x - kPad, motion->position.y - kPad)];
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
  [self wakeVisuals]; [self updateVisuals];
  // The state file is an observable checkpoint, not a frame-by-frame trace.
  if (motion->phase != Phase::Settling && motion->phase != Phase::Dragging) [self writeState];
}
- (NSDictionary *)settingsDictionary {
  NSMutableDictionary *dict = [@{@"version":@1, @"docking":motion->settings.docking == Docking::Corners ? @"corners" : @"edges"} mutableCopy];
  dict[@"placement"] = @[@"smart", @"always-dock", @"free"][static_cast<NSInteger>(motion->settings.placement)];
  for (const auto& parameter : parameters) dict[@(parameter.key)] = @(motion->settings.*parameter.member);
  dict[@"feedback"] = feedback.enabled ? @YES : @NO;
  dict[@"feedback_haptics"] = feedback.haptics ? @YES : @NO;
  for (const auto& parameter : feedbackParameters) dict[@(parameter.key)] = @(feedback.*parameter.member);
  return dict;
}
- (void)writeState {
  const NSRect cardFrame = NSInsetRect(panel.frame, kPad, kPad);
  NSDictionary *state = @{@"pid":@(NSProcessInfo.processInfo.processIdentifier),
    @"phase":phaseName(motion->phase), @"x":@(motion->position.x), @"y":@(motion->position.y),
    @"target_x":@(motion->target.x), @"target_y":@(motion->target.y),
    @"tucked":@(motion->tucked != Side::None), @"settings":[self settingsDictionary],
    @"native_frame":@[@(NSMinX(cardFrame)), @(NSMinY(cardFrame)), @(NSWidth(cardFrame)), @(NSHeight(cardFrame))],
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
  for (NSString *key in @[@"feedback", @"feedback_haptics"]) {
    id flag = dict[key];
    if (!flag) continue;
    if (!([flag isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)flag) == CFBooleanGetTypeID())) valid = NO;
    else if ([key isEqual:@"feedback"]) nextFeedback.enabled = [flag boolValue];
    else nextFeedback.haptics = [flag boolValue];
  }
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
  [self stopAnimation]; [fileTimer invalidate]; [saveTimer invalidate]; [visualTimer invalidate];
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

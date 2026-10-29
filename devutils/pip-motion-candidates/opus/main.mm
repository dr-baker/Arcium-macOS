#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>
#include "SettingsSchema.h"
#include <memory>
#include <vector>

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
  {"resistance", "Edge resistance", .05, .85, &Settings::resistance,
    "How much the window follows your pointer beyond an inset boundary: top and bottom in every mode, plus the sides in Press any edge.\n\n"
    "Lower: less movement for the same pull, so the edge feels firmer. Higher: more movement, so it feels softer.\n\n"
    "Changing this while held keeps the window and its current depth still. Damping controls spring bounce after release."},
  {"free_speed", "Leave here below speed (points/s)", 0, 800, &Settings::free_speed,
    "In Smart mode, releases at or below this speed count as deliberate placement.\n\n"
    "Away from a dock, the window stays where dropped. Near a dock, it snaps locally. Faster releases project toward a dock.\n\n"
    "Higher: more drops stay where placed. Lower: you must release more slowly. Briefly pausing before release helps place precisely.", true},
  {"snap_distance", "Snap attraction distance (points)", 0, 180, &Settings::snap_distance,
    "In Smart mode, how close a slow drop must be to the nearest allowed dock to snap there.\n\n"
    "Higher: a larger attraction zone. Lower: more freedom to leave the window near a dock. Zero requires exact alignment.\n\n"
    "Measured from the window's dropped position to the nearest corner or side-edge dock. Faster flicks use momentum projection instead.\n\n"
    "Not used by Press into any edge, where only pressing docks.", true},
  {"press_dock", "Press to dock (% of size)", 0, 20, &Settings::press_dock,
    "Press any edge: how far the window must be pushed into an edge before letting go snaps it flush there.\n\n"
    "Measured as resisted travel past this drag’s boundary divided by the window’s width or height. The readout shows “depth N%”. Re-grabbing outside the inset starts fresh depth at the grabbed position. Pushing into two edges snaps to that corner.\n\n"
    "Lower: a lighter push snaps. Higher: a firmer push is needed, leaving room to place close to an edge.", true},
  {"press_tuck", "Press to tuck (% of size)", 2, 40, &Settings::press_tuck,
    "Press any edge: how far the window must be pushed into the left or right before letting go tucks it.\n\n"
    "When tuck depth is higher than dock depth, the interval between them docks on that side. Tuck takes priority at or above its threshold, even if set below dock depth. The top and bottom never tuck. Softer resistance reaches the same depth with less push.\n\n"
    "Lower: a shorter push tucks. Higher: tucking needs a longer, more deliberate push.", true},
};
static constexpr size_t parameterCount = sizeof(parameters) / sizeof(parameters[0]);

// Release feedback lives in the lab, not the motion model; it only reads predictions.
struct Feedback {
  bool enabled = true;
  bool haptics = true;
  double lift = .75;
  double pickupShadow = -.44;
  double shadowBox = .20;
  double shadowIntensity = 1.10;
  double settle = .62;
  double settleDelay = .08;
  double settleEase = .28;
  double press = .40;
  double glow = 0;
  double edge = .80;
  double lean = 40;
  double dockShadow = .90;
};
// The lab's starting and Reset values: Daniel's tuning. The model's own defaults stay as the
// iOS-like baseline its checks and spring presets use.
static Settings labDefaults() {
  Settings s;
  s.response = .625; s.damping = .759; s.projection = .266; s.margin = 21.93;
  s.stash_percent = 30; s.stash_velocity = 1009; s.restore_distance = 29.86;
  s.handle = 26.35; s.resistance = .631; s.free_speed = 800; s.snap_distance = 64;
  s.press_dock = 2; s.press_tuck = 24.7;
  s.docking = Docking::AllEdges; s.placement = Placement::Smart;
  return s;
}
struct FeedbackParameter {
  const char *key, *label;
  double low, high;
  double Feedback::*member;
  const char *help;
};
static const FeedbackParameter feedbackParameters[] = {
  {"feedback_lift", "Lift", 0, 1, &Feedback::lift,
    "How much the window rises when you pick it up: it grows slightly toward you and its centered shadow spreads, both on one spring.\n\n"
    "After release, the window stays lifted while it travels and sets down as it arrives.\n\n"
    "Zero keeps the resting shadow."},
  {"feedback_pickup_shadow", "Pickup shadow", -1, 1, &Feedback::pickupShadow,
    "How the shadow changes as the window lifts, from sharpening to softening.\n\n"
    "+1 softens: the shadow spreads wider and blurrier, like an object rising away from the desk under room light.\n\n"
    "0 keeps its spread and edge unchanged. −1 sharpens: the shadow tightens and darkens, like a spotlight overhead.\n\n"
    "Lift sets how strong the change is."},
  {"feedback_shadow_box", "Shadow box", .2, .95, &Feedback::shadowBox,
    "Size of the light over the middle of the screen, as a fraction of the work area.\n\n"
    "Over the light, the window casts its shadow straight down. Outside it, the shadow falls away from the light toward the screen edges, longer the farther out and the higher the window is lifted, up to 26 points.\n\n"
    "A box rather than a single point keeps windows near the middle from casting far. Lower: shadows angle outward sooner. Higher: only windows near the edges cast outward."},
  {"feedback_shadow_intensity", "Shadow intensity", 0, 2, &Feedback::shadowIntensity,
    "How dark both shadows are, resting and lifted.\n\n"
    "1 is the designed darkness. Zero removes the shadows; 2 doubles them."},
  {"feedback_settle", "Settle", 0, 1, &Feedback::settle,
    "Preempts release: while letting go would leave the window where it is, it sets itself down before you let go.\n\n"
    "The window shrinks back to its resting size and its shadows return to their resting look. It deepens as you slow and is full once you hold still; speeding up lifts it again.\n\n"
    "1 settles fully. Zero keeps the full held look until release."},
  {"feedback_settle_delay", "Settle delay", 0, .6, &Feedback::settleDelay,
    "Seconds the hand must stay slow before the window starts settling.\n\n"
    "Speeding up again cancels the wait and lifts the window straight back, so brief slowdowns mid-drag do not flicker.\n\n"
    "Higher: calmer, settles only on a real pause. Zero: settles the moment you slow down."},
  {"feedback_settle_ease", "Settle ease", .1, 1, &Feedback::settleEase,
    "Spring response, in seconds, of the settle animation once the delay has passed.\n\n"
    "Higher: a slower, softer glide toward the desk. Lower: a quicker drop.\n\n"
    "Lifting back when you speed up always uses a faster response, under half of this value."},
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
  NSPopUpButton *presetMenu;
  NSSegmentedControl *dockControl, *placementControl;
  NSTextField *hint;
  NSMutableArray<NSTextField *> *headings, *feedbackHeadings;
  NSTextField *status, *fileStatus, *explanation;
  NSTimer *animationTimer, *fileTimer, *saveTimer, *visualTimer;
  double lastTick;
  NSString *settingsPath, *statePath;
  NSData *lastSettingsData;
  NSDictionary *legacyPressThresholds;
  Feedback feedback;
  CALayer *stage, *ambientShadow, *contactShadow, *glowShadow, *overlay;
  CAGradientLayer *rimShade;
  CAShapeLayer *chevron, *rimLight;
  CATextLayer *intentText, *cueText;
  NSButton *feedbackToggle, *hapticsToggle;
  NSMutableArray<NSSlider *> *feedbackSliders;
  NSMutableArray<NSTextField *> *feedbackFields;
  double lift, liftVelocity, castX, castY, settleAmount, settleVelocity, handSpeed, slowSince, glow, edgeAmount, leanX, leanY, shadowX, shadowY, lastVisualTime, releaseDistance, rimShadeStrength;
  Side chevronSide;
  BOOL leaning, awaitingLanding, moving, settleTapped;
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
  motion->settings = labDefaults();
  // Tuning window: behavior choices on top, grouped values in tabs, try-it actions below.
  const CGFloat W = 536, H = 896;
  controls = [[NSWindow alloc] initWithContentRect:NSMakeRect(area.origin.x + 28,
      std::max(area.origin.y, NSMaxY(area) - H - 28), W, H)
      styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
      backing:NSBackingStoreBuffered defer:NO];
  controls.title = @"Opus PiP Lab";
  controls.delegate = self;
  controls.releasedWhenClosed = NO;
  NSView *content = controls.contentView;

  NSTextField *title = label(@"Tune the PiP window", NSMakeRect(24, H - 46, 300, 26), 20);
  title.font = [NSFont systemFontOfSize:20 weight:NSFontWeightSemibold];
  [content addSubview:title];
  presetMenu = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(338, H - 46, 150, 26) pullsDown:YES];
  [presetMenu addItemWithTitle:@"Presets"]; presetMenu.lastItem.tag = -1;
  [presetMenu addItemWithTitle:@"Daniel’s tuning"]; presetMenu.lastItem.tag = 6;
  NSArray *presetTitles = @[@"Grounded", @"iOS-like baseline", @"Snappy", @"Soft spring", @"Position only"];
  for (NSUInteger i = 0; i < presetTitles.count; ++i) {
    [presetMenu addItemWithTitle:presetTitles[i]]; presetMenu.lastItem.tag = i + 1;
  }
  [presetMenu.menu addItem:NSMenuItem.separatorItem];
  [presetMenu addItemWithTitle:@"Reset everything"]; presetMenu.lastItem.tag = 9;
  presetMenu.target = self; presetMenu.action = @selector(presetChanged:);
  [content addSubview:presetMenu];
  addHelp(content, NSMakeRect(494, H - 42, 18, 18), @"Presets",
      @"Daniel’s tuning: the lab defaults, saved from your Oct 28 session, with Press any edge and Smart drops: response 0.62, damping 0.76, projection 0.27, resistance 0.63, leave-here speed 800, inset 22, press to dock 2% and tuck 25%; lift 0.75, pickup shadow −0.44, shadow box 0.20, shadow intensity 1.10, settle 0.62 after 0.08 s with ease 0.28, press 0.40, edge shade 0.80, dock lean 40, dock shadow 0.90.\n\n"
      "Grounded: a calm, natural tuning for every value, with corner snapping and Smart drops. "
      "Leave-here speed 180, snap distance 64, projection 0.40, response 0.44 with no bounce, inset 16, tuck at 30% or 1000 pt/s, restore after 24 pt; "
      "lift 0.60, settle 0.75, press 0.40, edge shade 0.50, dock lean 12, dock shadow 0.90, no glow, haptics on.\n\n"
      "iOS-like baseline, Snappy and Soft spring change only response, damping and projection. Position only sets projection to zero. They keep all other motion and feedback tuning.\n\n"
      "Reset everything restores every compiled default, including the choices above the tabs.");

  auto modeRow = [&](NSString *name, NSArray<NSString *> *labels, SEL action, CGFloat y) {
    NSTextField *caption = label(name, NSMakeRect(24, y + 4, 74, 18), 12);
    caption.textColor = NSColor.secondaryLabelColor; [content addSubview:caption];
    NSSegmentedControl *control = [NSSegmentedControl segmentedControlWithLabels:labels
        trackingMode:NSSegmentSwitchTrackingSelectOne target:self action:action];
    control.frame = NSMakeRect(100, y, 388, 26);
    control.segmentDistribution = NSSegmentDistributionFillEqually;
    [content addSubview:control];
    return control;
  };
  dockControl = modeRow(@"Snaps to", @[@"Corners", @"Side edges", @"Press any edge"], @selector(dockingChanged:), H - 88);
  addHelp(content, NSMakeRect(494, H - 84, 18, 18), @"Snaps to",
      @"Where a release can snap.\n\n"
      "Corners: the four corners of the visible work area. Side edges: flush against the left or right, at any height.\n\n"
      "Press any edge: every edge resists like a soft wall. Push a little into an edge to snap flush to it anywhere along it, into two edges for a corner, or hard into a side to tuck. Nearness alone never snaps.\n\n"
      "Fast flicks use momentum projection to choose a farther destination.");
  placementControl = modeRow(@"A drop", @[@"Smart", @"Always snaps", @"Stays put"], @selector(placementChanged:), H - 122);
  addHelp(content, NSMakeRect(494, H - 118, 18, 18), @"A drop",
      @"What letting go does away from a tuck.\n\n"
      "Smart: a slow drop stays where you put it unless it is close to a snap point; a flick snaps. Always snaps: every release snaps. Stays put: releases stop where dropped, inside the screen inset.\n\n"
      "Tucking works in every mode. Controls that do not apply to the current choices are dimmed.");
  hint = [NSTextField wrappingLabelWithString:@""];
  hint.frame = NSMakeRect(24, H - 170, 488, 36);
  hint.font = [NSFont systemFontOfSize:12]; hint.textColor = NSColor.secondaryLabelColor;
  [content addSubview:hint];

  NSTabView *tabs = [[NSTabView alloc] initWithFrame:NSMakeRect(18, 176, W - 36, H - 176 - 176)];
  NSMutableArray<NSView *> *pages = NSMutableArray.array;
  for (NSString *name in @[@"Feel", @"Edges", @"Cues"]) {
    NSTabViewItem *item = [[NSTabViewItem alloc] initWithIdentifier:name];
    item.label = name;
    item.view = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, NSWidth(tabs.contentRect), NSHeight(tabs.contentRect))];
    [tabs addTabViewItem:item];
    [pages addObject:item.view];
  }
  [content addSubview:tabs];
  const CGFloat pageWidth = NSWidth(tabs.contentRect), pageTop = NSHeight(tabs.contentRect) - 42;
  auto makeRow = [&](NSString *name, NSString *help, double low, double high, double value, NSInteger tag,
                     SEL sliderAction, SEL fieldAction, NSMutableArray *rowSliders,
                     NSMutableArray *rowFields, NSMutableArray *rowHeadings) {
    NSTextField *heading = label(name, NSZeroRect, 11); [heading sizeToFit];
    NSSlider *slider = [NSSlider sliderWithValue:value minValue:low maxValue:high target:self action:sliderAction];
    slider.tag = tag; slider.continuous = YES;
    slider.accessibilityLabel = name; slider.accessibilityHelp = help;
    NSTextField *field = [[NSTextField alloc] initWithFrame:NSZeroRect];
    field.tag = tag; field.target = self; field.action = fieldAction;
    field.alignment = NSTextAlignmentRight;
    field.accessibilityLabel = [name stringByAppendingString:@" value"]; field.accessibilityHelp = help;
    [rowSliders addObject:slider]; [rowFields addObject:field]; [rowHeadings addObject:heading];
  };
  auto placeRow = [&](NSView *page, CGFloat y, NSTextField *heading, NSString *help, NSSlider *slider, NSTextField *field) {
    heading.frameOrigin = NSMakePoint(12, y + 16); [page addSubview:heading];
    addHelp(page, NSMakeRect(NSMaxX(heading.frame) + 5, y + 15, 18, 18), heading.stringValue, help);
    slider.frame = NSMakeRect(12, y - 2, pageWidth - 110, 22); [page addSubview:slider];
    field.frame = NSMakeRect(pageWidth - 88, y + 1, 72, 24); [page addSubview:field];
  };
  sliders = NSMutableArray.array; fields = NSMutableArray.array; headings = NSMutableArray.array;
  for (size_t i = 0; i < parameterCount; ++i)
    makeRow(@(parameters[i].label), @(parameters[i].help), parameters[i].low, parameters[i].high,
            motion->settings.*parameters[i].member, i, @selector(sliderChanged:), @selector(fieldChanged:),
            sliders, fields, headings);
  const std::vector<std::vector<const char *>> pageKeys = {
    {"response", "damping", "projection", "free_speed", "snap_distance", "margin"},
    {"resistance", "press_dock", "press_tuck", "stash_percent", "stash_velocity", "restore_distance", "handle"}};
  for (size_t page = 0; page < pageKeys.size(); ++page) {
    CGFloat y = pageTop;
    for (const char *key : pageKeys[page]) {
      for (size_t i = 0; i < parameterCount; ++i) {
        if (strcmp(parameters[i].key, key) != 0) continue;
        placeRow(pages[page], y, headings[i], @(parameters[i].help), sliders[i], fields[i]);
        y -= 38;
      }
    }
  }

  NSView *cues = pages[2];
  feedbackToggle = [NSButton checkboxWithTitle:@"Release feedback" target:self action:@selector(feedbackToggled:)];
  feedbackToggle.frame = NSMakeRect(10, pageTop + 4, 140, 20);
  [cues addSubview:feedbackToggle];
  addHelp(cues, NSMakeRect(150, pageTop + 5, 18, 18), @"Release feedback",
      @"Physical cues for holding and letting go.\n\n"
      "Picking the window up deepens and softens its shadow and shrinks it slightly. After release it stays lifted while it travels, sets down where it comes to rest, and dips once as it lands.\n\n"
      "Held where it will stay, it lowers toward the desk. Held near where it would snap, it leans that way and its shadow slides there.\n\n"
      "Pushed into a side, the screen's rim casts a shadow on the part going in, and the chevron fades in with depth. The shadow deepens once letting go would tuck.\n\n"
      "Turn off to compare with no added feedback. The tucked chevron still appears.");
  hapticsToggle = [NSButton checkboxWithTitle:@"Haptics" target:self action:@selector(hapticsToggled:)];
  hapticsToggle.frame = NSMakeRect(196, pageTop + 4, 80, 20);
  [cues addSubview:hapticsToggle];
  addHelp(cues, NSMakeRect(272, pageTop + 5, 18, 18), @"Haptics",
      @"Force Touch trackpad taps for every event: pickup, each change in what letting go would do, and landing.\n\n"
      "Stay here taps when the settle animation finishes, not when the outcome changes. With Settle at zero it taps on the change.\n\n"
      "Every tap uses the lightest alignment pattern, at most one every 0.15 seconds.\n\n"
      "macOS only plays haptics while a finger is on the trackpad, so a landing after a long flight may be silent. Mice have no haptics.");
  feedbackSliders = NSMutableArray.array; feedbackFields = NSMutableArray.array; feedbackHeadings = NSMutableArray.array;
  for (size_t i = 0; i < feedbackParameterCount; ++i) {
    const auto& parameter = feedbackParameters[i];
    makeRow(@(parameter.label), @(parameter.help), parameter.low, parameter.high, feedback.*parameter.member, i,
            @selector(feedbackSliderChanged:), @selector(feedbackFieldChanged:),
            feedbackSliders, feedbackFields, feedbackHeadings);
    placeRow(cues, pageTop - 34 - i * 34, feedbackHeadings[i], @(parameter.help), feedbackSliders[i], feedbackFields[i]);
  }

  explanation = label(@"", NSMakeRect(24, 150, 488, 18), 11);
  explanation.textColor = NSColor.secondaryLabelColor; [content addSubview:explanation];
  status = label(@"", NSMakeRect(24, 130, 488, 16), 11);
  status.font = [NSFont monospacedSystemFontOfSize:11 weight:NSFontWeightRegular];
  status.textColor = NSColor.tertiaryLabelColor;
  [content addSubview:status];
  NSTextField *tryLabel = label(@"Throw from center", NSMakeRect(24, 96, 120, 18), 12);
  tryLabel.textColor = NSColor.secondaryLabelColor; [content addSubview:tryLabel];
  NSArray *arrows = @[@"↖", @"↗", @"↙", @"↘"];
  for (NSInteger i = 0; i < 4; ++i)
    [self button:arrows[i] frame:NSMakeRect(144 + i * 46, 90, 42, 28) action:@selector(sampleThrow:) tag:i];
  [self button:@"Replay last throw" frame:NSMakeRect(334, 90, 178, 28) action:@selector(replay:) tag:0];
  [self button:@"Tuck / restore" frame:NSMakeRect(24, 56, 150, 28) action:@selector(toggleTuck:) tag:0];
  [self button:@"Reset position" frame:NSMakeRect(180, 56, 150, 28) action:@selector(reset:) tag:0];
  [self button:@"JSON…" frame:NSMakeRect(442, 56, 70, 28) action:@selector(reveal:) tag:0];
  fileStatus = label(@"Settings save and reload live · no rebuild needed", NSMakeRect(24, 24, 488, 16), 10);
  fileStatus.textColor = NSColor.secondaryLabelColor; [content addSubview:fileStatus];

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
// Whether a motion value affects the current snapping and drop choices.
- (BOOL)relevant:(const char *)key {
  const Settings& settings = motion->settings;
  const bool press = settings.docking == Docking::AllEdges;
  if (!strcmp(key, "snap_distance")) return settings.placement == Placement::Smart && !press;
  if (!strcmp(key, "projection")) return settings.placement != Placement::Free;
  if (!strcmp(key, "press_dock") || !strcmp(key, "press_tuck")) return press;
  if (!strcmp(key, "stash_percent")) return !press;
  return YES;
}
- (NSString *)hintText {
  const Settings& settings = motion->settings;
  if (settings.docking == Docking::AllEdges) {
    NSString *drop = settings.placement == Placement::Free ? @"Drops stay where you leave them." :
        settings.placement == Placement::AlwaysDock ? @"Every drop snaps to the nearest edge." :
        @"Slow drops stay put; flicks throw to the nearest edge.";
    return [drop stringByAppendingString:@" Push a little into any edge to snap flush to it, into two edges for a corner, or hard into a side to tuck."];
  }
  NSString *where = settings.docking == Docking::Corners ? @"a corner" : @"the left or right edge";
  NSString *drop = settings.placement == Placement::Free ? @"Drops stay where you leave them; nothing snaps." :
      settings.placement == Placement::AlwaysDock ? [NSString stringWithFormat:@"Every drop snaps to %@.", where] :
      [NSString stringWithFormat:@"Slow drops stay put unless close to %@; flicks throw there.", where];
  return [drop stringByAppendingString:@" Push past a side to tuck; click the strip to bring it back."];
}
- (void)syncControls {
  for (size_t i = 0; i < parameterCount; ++i) {
    const auto& parameter = parameters[i];
    const double value = motion->settings.*parameter.member;
    const BOOL on = [self relevant:parameter.key];
    sliders[i].doubleValue = value; sliders[i].enabled = on; fields[i].enabled = on;
    fields[i].stringValue = [NSString stringWithFormat:!strncmp(parameter.key, "press", 5) ? @"%.1f" :
        parameter.high > 10 ? @"%.0f" : @"%.3f", value];
    headings[i].textColor = on ? NSColor.labelColor : NSColor.tertiaryLabelColor;
  }
  dockControl.selectedSegment = static_cast<NSInteger>(motion->settings.docking);
  placementControl.selectedSegment = static_cast<NSInteger>(motion->settings.placement);
  hint.stringValue = [self hintText];
  feedbackToggle.state = feedback.enabled ? NSControlStateValueOn : NSControlStateValueOff;
  hapticsToggle.state = feedback.haptics ? NSControlStateValueOn : NSControlStateValueOff;
  hapticsToggle.enabled = feedback.enabled;
  for (size_t i = 0; i < feedbackParameterCount; ++i) {
    const double value = feedback.*feedbackParameters[i].member;
    feedbackSliders[i].doubleValue = value; feedbackSliders[i].enabled = feedback.enabled;
    feedbackFields[i].stringValue = [NSString stringWithFormat:feedbackParameters[i].high > 1 ? @"%.1f" : @"%.2f", value];
    feedbackFields[i].enabled = feedback.enabled;
    feedbackHeadings[i].textColor = feedback.enabled ? NSColor.labelColor : NSColor.tertiaryLabelColor;
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
  [self apply:next save:YES];
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
  [self apply:next save:YES];
}
- (void)dockingChanged:(NSSegmentedControl *)sender {
  Settings next = motion->settings;
  next.docking = static_cast<Docking>(sender.selectedSegment);
  [self apply:next save:YES];
}
- (void)placementChanged:(NSSegmentedControl *)sender {
  Settings next = motion->settings;
  next.placement = static_cast<Placement>(sender.selectedSegment);
  [self apply:next save:YES];
}
- (void)presetChanged:(NSPopUpButton *)sender {
  const NSInteger choice = sender.selectedItem.tag;
  if (choice == 1) { [self grounded:nil]; return; }
  if (choice == 6) { [self danielsTuning]; return; }
  if (choice == 9) { [self resetVariables:nil]; fileStatus.stringValue = @"Reset everything · saved"; return; }
  if (choice < 2) return;
  Settings next = springPreset(motion->settings, static_cast<SpringPreset>(choice - 2));
  [self apply:next save:YES];
  fileStatus.stringValue = [NSString stringWithFormat:@"Applied %@ · saved", sender.selectedItem.title];
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
- (void)danielsTuning {
  [controls makeFirstResponder:nil];
  feedback = Feedback{};
  [self apply:labDefaults() save:YES];
  fileStatus.stringValue = @"Applied Daniel’s tuning · saved";
}
- (void)grounded:(id)sender {
  [controls makeFirstResponder:nil];
  Settings next;
  next.response = .44; next.damping = 1; next.projection = .40; next.margin = 16;
  next.stash_percent = 30; next.stash_velocity = 1000; next.restore_distance = 24;
  next.handle = 28; next.resistance = .35; next.free_speed = 180; next.snap_distance = 64;
  next.docking = Docking::Corners; next.placement = Placement::Smart;
  Feedback tuned;
  tuned.lift = .60; tuned.pickupShadow = 1; tuned.shadowBox = .70; tuned.shadowIntensity = 1;
  tuned.settle = .75; tuned.settleDelay = .18; tuned.settleEase = .45; tuned.press = .40; tuned.glow = 0;
  tuned.edge = .50; tuned.lean = 12; tuned.dockShadow = .90;
  feedback = tuned;
  [self apply:next save:YES];
  fileStatus.stringValue = @"Applied grounded defaults · saved";
}
- (void)resetVariables:(id)sender {
  [controls makeFirstResponder:nil];
  [saveTimer invalidate]; saveTimer = nil;
  motion->resetSettings(labDefaults());
  feedback = Feedback{};
  [self syncControls];
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
  awaitingLanding = NO; hapticKey = pendingKey = -1; slowSince = -1; settleTapped = NO;
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
// Bit mask of the inset edges a dock target sits on: left 1, right 2, bottom 4, top 8.
- (int)edgesFor:(pip_motion::Point)target {
  const auto area = motion->area();
  const double margin = motion->settings.margin;
  const double left = area.x + margin, right = area.x + area.width - motion->size.width - margin;
  const double bottom = area.y + margin, top = area.y + area.height - motion->size.height - margin;
  return (std::abs(target.x - left) < .5) | (std::abs(target.x - right) < .5) << 1 |
      (std::abs(target.y - bottom) < .5) << 2 | (std::abs(target.y - top) < .5) << 3;
}
// Identity of a release outcome for haptics: decision, side and which dock.
- (int)hapticKeyFor:(const Outcome &)outcome {
  int key = static_cast<int>(outcome.decision) * 100 + static_cast<int>(outcome.side) * 10;
  if (outcome.decision == Decision::Dock && motion->settings.docking == Docking::AllEdges)
    return key + 20 + [self edgesFor:outcome.target];
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
  if (motion->settings.docking == Docking::AllEdges) {
    const int edges = [self edgesFor:target];
    NSString *across = edges & 1 ? @"left" : edges & 2 ? @"right" : nil;
    NSString *along = edges & 8 ? @"top" : edges & 4 ? @"bottom" : nil;
    if (across && along) return [NSString stringWithFormat:@"%@-%@ corner", along, across];
    return [NSString stringWithFormat:@"%@ edge", along ?: across ?: @"nearest"];
  }
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
  // Cues preview a gentle release from here. Mid-drag velocity says nothing about the eventual
  // release, so while the hand moves fast, stay and dock cues go neutral instead of chasing a
  // momentum-projected dock. Tuck and restore depend on position and still show.
  Outcome cue = dragging ? motion->predict([self dragTime], true) : Outcome{};
  const double gate = motion->settings.free_speed;
  moving = dragging && cue.speed > (moving ? gate : gate + std::max(60.0, gate / 2));
  if (moving && (cue.decision == Decision::Keep || cue.decision == Decision::Dock)) cue.decision = Decision::None;
  // A press that has not moved the window is a click: it lifts, but previews nothing.
  const bool moved = dragging && outcome.moved;
  const auto area = motion->area();
  const pip_motion::Point position = motion->position;
  const double w = motion->size.width, h = motion->size.height, handle = motion->settings.handle;

  // Cues and haptics follow a debounced outcome so threshold chatter (speed hovering at the
  // deliberate limit, or position at a snap or tuck boundary) does not flicker the window.
  Outcome shown = cue;
  if (moved) {
    const int key = [self hapticKeyFor:cue];
    if (hapticKey < 0) { hapticKey = pendingKey = key; stableOutcome = cue; }
    if (key != pendingKey) { pendingKey = key; pendingSince = now; }
    else if (key != hapticKey && now - pendingSince >= .1) {
      // With a settle animation, the stay-here tap waits until the card has finished settling.
      const bool settleTaps = cue.decision == Decision::Keep && on && feedback.settle > 0;
      if (cue.decision != Decision::None && !settleTaps) [self haptic:NSHapticFeedbackPatternAlignment];
      hapticKey = key;
    }
    if (key == hapticKey) stableOutcome = cue;
    shown = stableOutcome;
    if (shown.decision == cue.decision) { shown.target = cue.target; shown.side = cue.side; }
  }
  const bool keep = moved && shown.decision == Decision::Keep;
  // Hand speed rises quickly but eases down, so a slowing drag reads as a glide rather than a step.
  approach(handSpeed, dragging ? cue.speed : 0, .04, .12, dt);
  // Settling waits until the hand has stayed slow for the delay, then deepens as it slows further.
  if (!keep) slowSince = -1;
  else if (slowSince < 0) slowSince = now;
  const bool settleReady = keep && now - slowSince >= feedback.settleDelay;
  const double settleTarget = settleReady ? 1 - smoothstep(handSpeed / std::max(1.0, gate)) : 0;
  double liftTarget = 0;
  // The held look (lift and shrink) lasts the whole drag; settling toward the desk is a separate cue.
  if (dragging) liftTarget = 1;
  else if (motion->phase == Phase::Settling && releaseDistance > 1)
    liftTarget = std::sqrt(std::clamp(length(motion->target - position) / releaseDistance, 0.0, 1.0));
  const double glowTarget = keep ? 1 : 0;

  // Magnetic pull toward the dock a gentle release would snap to: full within the snap
  // distance, fading out by twice that (relevant in Always snap mode).
  pip_motion::Point leanTarget{}, shadowTarget{};
  leaning = false;
  if (on && moved && shown.decision == Decision::Dock &&
      !NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion) {
    const pip_motion::Point toward = shown.target - position;
    const double distance = length(toward);
    const double reach = 2 * dockCueDistance(motion->settings);
    const double engage = smoothstep((reach - distance) / (reach / 2));
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
  // In press mode the sides resist, so approach progress is the press toward the tuck distance.
  const bool pressingEdge = motion->settings.docking == Docking::AllEdges && dragging &&
      motion->tucked == Side::None && motion->pressed.x != 0;
  if (pressingEdge && !committed) side = motion->pressed.x < 0 ? Side::Left : Side::Right;
  const double approachLevel = pressingEdge ?
      .28 * smoothstep(std::abs(motion->depth().x) / std::max(1.0, motion->settings.press_tuck)) :
      .28 * smoothstep(over / tuckDistance);
  const double edgeTarget = committed ? .7 + .3 * depth : approachLevel;

  // One slightly underdamped spring drives the card's rise and its shadow together, so pickup
  // pops up a touch past held height and set-down lands with a faint give.
  const double liftGoal = on ? liftTarget : 0;
  pip_motion::spring(lift, liftVelocity, liftGoal, liftGoal > lift ? .26 : .32, .78, dt);
  if (std::abs(lift - liftGoal) < 1e-3 && std::abs(liftVelocity) < 1e-2) { lift = liftGoal; liftVelocity = 0; }
  // Settling in follows the tunable ease; lifting back out uses a faster response. After
  // release the settle holds, so a pre-settled card does not rise again while lift falls.
  double settleGoal = on ? settleTarget : 0;
  if (on && !dragging) {
    settleGoal = lift > 1e-3 || liftVelocity != 0 ? settleAmount : 0;
    settleAmount = settleGoal; settleVelocity = 0;
  }
  pip_motion::spring(settleAmount, settleVelocity, settleGoal,
      settleGoal > settleAmount ? feedback.settleEase : std::max(.12, .45 * feedback.settleEase), 1, dt);
  if (std::abs(settleAmount - settleGoal) < 1e-3 && std::abs(settleVelocity) < 1e-2) { settleAmount = settleGoal; settleVelocity = 0; }
  // One tap when the settle animation completes; it rearms once the card lifts well back up.
  if (dragging && keep && on && feedback.settle > 0 && !settleTapped && settleAmount >= .95) {
    settleTapped = YES; [self haptic:NSHapticFeedbackPatternAlignment];
  } else if (!keep || settleAmount < .5) settleTapped = NO;
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
  // The same lift spring drives the card scale and shadow spread. Settling preempts release:
  // it lowers the card back toward resting size and resting shadows while still held.
  const double settled = std::clamp(settleAmount, 0.0, 1.0) * feedback.settle;
  const double l = std::clamp(lift, -.15, 1.2) * feedback.lift * (1 - settled);
  // A landing dips the card once and springs back.
  const double pressAge = now - pressStart, pressTime = .24;
  const bool pressing = on && pressAge >= 0 && pressAge < pressTime;
  const double dip = pressing ? .02 * feedback.press * (1 - std::cos(2 * M_PI * pressAge / pressTime)) / 2 : 0;
  // Lifting brings the card toward you: it grows slightly as its shadow spreads.
  const double cardScale = (1 + .03 * l) * (1 - dip);
  stage.position = CGPointMake(CGRectGetMidX(card), CGRectGetMidY(card));
  stage.transform = CATransform3DMakeScale(cardScale, cardScale, 1);
  // Pickup shadow: +1 spreads and softens as it lifts, -1 tightens and darkens.
  const double k = std::clamp(feedback.pickupShadow, -1.0, 1.0);
  // Light comes from a box over the middle of the work area. A window over the box casts
  // straight down; outside it, the shadow falls away from the nearest point of the box, longer
  // the farther out and the higher the window. A box rather than a point keeps windows near the
  // center from casting far.
  const double b = feedback.shadowBox;
  const double cx = position.x + leanX + w / 2 - (area.x + area.width / 2);
  const double cy = position.y + leanY + h / 2 - (area.y + area.height / 2);
  auto away = [&](double offset, double half) {
    const double inner = half * b, outer = std::max(1.0, half - inner);
    return std::clamp((offset - std::clamp(offset, -inner, inner)) / outer, -1.0, 1.0);
  };
  const double cast = 26 * (.3 + .7 * std::max(l, 0.0));
  castX = away(cx, area.width / 2) * cast; castY = away(cy, area.height / 2) * cast;
  const double intensity = feedback.shadowIntensity;
  ambientShadow.shadowRadius = 18 + l * (k >= 0 ? 14 * k : 12 * k);
  ambientShadow.shadowOpacity = std::min(1.0, intensity * (.30 + l * (k >= 0 ? .06 * k : -.16 * k)));
  ambientShadow.shadowOffset = CGSizeMake(shadowX + castX, shadowY + castY);
  contactShadow.shadowRadius = 4 + 3 * l;
  contactShadow.shadowOpacity = std::min(1.0, intensity * .16 * (1 - .75 * l * std::max(k, 0.0)));
  contactShadow.shadowOffset = CGSizeMake(leanX * .5 + castX * .2, leanY * .5 + castY * .2);
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
  if (dragging) intent = !moved ? @"Picked up" : shown.decision == Decision::None ? @"Moving" :
      describe(shown.decision, shown.side, shown.target, @"Release → ");
  else if (motion->phase == Phase::Settling)
    intent = describe(motion->decision, motion->tucked, motion->target, @"Settling → ");
  else if (motion->phase == Phase::Tucked) intent = motion->tucked == Side::Left ? @"Tucked left" : @"Tucked right";
  else intent = pressing ? @"Landed" : @"Resting";
  NSMutableArray<NSString *> *cues = NSMutableArray.array;
  if (!on) [cues addObject:@"Feedback off"];
  if (l > .01) [cues addObject:[NSString stringWithFormat:@"lift %.0f%%", l * 100]];
  if (settled > .01) [cues addObject:[NSString stringWithFormat:@"settle %.0f%%", settled * 100]];
  else if (on && keep && !settleReady && feedback.settle > 0) [cues addObject:@"settle waiting"];
  if (std::hypot(leanX, leanY) > .5) [cues addObject:[NSString stringWithFormat:@"lean %.0f pt", std::hypot(leanX, leanY)]];
  if (std::hypot(shadowX, shadowY) > .5) [cues addObject:[NSString stringWithFormat:@"shadow → %.0f pt", std::hypot(shadowX, shadowY)]];
  if (std::hypot(castX, castY) > .5) [cues addObject:[NSString stringWithFormat:@"cast %.0f pt", std::hypot(castX, castY)]];
  if (dragging && length(motion->pressed) > .5) {
    const pip_motion::Point in = motion->depth();
    [cues addObject:[NSString stringWithFormat:@"depth %.1f%%", std::max(std::abs(in.x), std::abs(in.y))]];
  }
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
  return !pressing && lift == liftGoal && liftVelocity == 0 && settleAmount == settleGoal && settleVelocity == 0 && glow == (on ? glowTarget : 0) &&
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
  NSMutableDictionary *dict = [@{@"version":@2, @"docking":@[@"corners", @"edges", @"all-edges"][static_cast<NSInteger>(motion->settings.docking)]} mutableCopy];
  if (legacyPressThresholds) dict[@"legacy_press_thresholds"] = legacyPressThresholds;
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
  const auto prepared = prepareSettings(object);
  BOOL valid = prepared.has_value();
  NSDictionary *dict = prepared ? prepared->values : @{};
  valid = valid &&
      [@[@"corners", @"edges", @"all-edges"] containsObject:dict[@"docking"]];
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
  Settings next = labDefaults();
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
  next.docking = static_cast<Docking>([@[@"corners", @"edges", @"all-edges"] indexOfObject:dict[@"docking"]]);
  [saveTimer invalidate]; saveTimer = nil;
  feedback = nextFeedback;
  legacyPressThresholds = [dict[@"legacy_press_thresholds"] isKindOfClass:NSDictionary.class] ? dict[@"legacy_press_thresholds"] : nil;
  [self apply:next save:NO];
  if (migratedTuckDistance || prepared->rewrite) [self saveSettings];
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

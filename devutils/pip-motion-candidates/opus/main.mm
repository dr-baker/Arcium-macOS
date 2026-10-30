#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>
#include "SettingsSchema.h"
#include "Gestures.hpp"
#include <memory>
#include <random>
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
// Visual effects are lab-only additions on top of the shared feedback settings.
struct Feedback : pip_motion::FeedbackSettings {
  double settleMeter = .60, edgeGlow = 1, meters = 1, tilt = 5, stretch = 1.5, landingShadow = .60;
  double springTrace = 1, dust = .70;
};
static Settings labDefaults() { return pip_motion::selectedSettings(); }
struct FeedbackParameter {
  const char *key, *label;
  double low, high;
  double Feedback::*member;
  const char *help;
  bool effect = false;
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
  {"effect_settle_meter", "Settle meter", 0, 1, &Feedback::settleMeter,
    "A thin line traces around the window's border as it settles, completing just as the settle haptic taps.\n\n"
    "On completion a soft ring ripples outward from the border, so the tap is visible on screen and in recordings.\n\n"
    "Sets the brightness of both. Zero turns them off.", true},
  {"effect_edge_glow", "Edge glow", 0, 1, &Feedback::edgeGlow,
    "In Press any edge, the inset boundary appears as a glowing line planted on the screen where your press began, bending outward around the window.\n\n"
    "It shows stress with color: white when relaxed, then yellow, orange and red where the window bends it, reaching red at tuck depth on the sides. The string stays fully behind the glass window.\n\n"
    "Letting go into a tuck tears it into a burst of threads that recoil toward its ends and fray away. "
    "Any other release, including a dock, or pulling away, lets it spring back through straight where it is, without following the window.\n\n"
    "Sets its brightness. Zero turns it off.", true},
  {"effect_meters", "Meters", 0, 1, &Feedback::meters,
    "Floating readouts beside the window, made for recordings.\n\n"
    "PRESS appears while you push into an edge: a bar fills with depth past the dock and tuck marks, with the exact percentage. "
    "SETTLE appears while the window settles and reads SET when it finishes, with the haptic.\n\n"
    "Sets their opacity. Zero hides them.", true},
  {"effect_tilt", "Tilt", 0, 12, &Feedback::tilt,
    "Maximum tilt, in degrees, as the window moves: its leading edge tips away in perspective and it springs flat with a slight wobble when it stops.\n\n"
    "Builds with speed. Zero turns it off. Reduce Motion also turns it off.", true},
  {"effect_stretch", "Stretch", 0, 4, &Feedback::stretch,
    "How much a fast flick stretches the window along its direction of travel, in percent, narrowing it slightly across.\n\n"
    "Starts above 600 pt/s and is full by 3000 pt/s, recovering as it slows and lands. Above about 2% it reads as cartoonish. Reduce Motion turns it off.", true},
  {"effect_landing_shadow", "Landing shadow", 0, 1, &Feedback::landingShadow,
    "On landing, the tight contact shadow briefly flares outward and then tightens, as if the window pressed air out from under it.\n\n"
    "Pairs with the Press dip. Zero turns it off.", true},
  {"effect_spring_trace", "Spring trace", 0, 1, &Feedback::springTrace,
    "An always-visible velocity graph inside the glass window. It follows your direction while dragging, then fixes the arrow to the initial flight when tossed. At rest it reads zero and keeps the recent curve.\n\n"
    "The line crosses below zero when the spring reverses, including its return from overshoot. High speeds are compressed vertically so small rebounds remain visible. The readout is signed points per second. Sets its opacity. Zero hides it.", true},
  {"effect_dust", "Dust", 0, 1, &Feedback::dust,
    "Soft specks drift out from under the window when Stay here finishes settling, with its tap. Releasing an already settled window does not repeat them.\n\n"
    "A hard landing also kicks them up. Harder throws raise more, faster.\n\n"
    "Sets their brightness. Zero turns it off.", true},
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
@property(nonatomic, strong) NSTrackingArea *gestureTracking;
@property(nonatomic, weak) NSWindow *previousKeyWindow;
@end

// The panel is padded so the window can draw its own shadow; only the card takes clicks.
static constexpr CGFloat kPad = 200;
static constexpr CGFloat kCardRadius = 20;
// Recording meter capsule and its track, in the capsule's coordinates.
static constexpr CGFloat kHudW = 228, kHudH = 42, kTrackX = 72, kTrackW = 100, kTrackY = 15;

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

// A single closed stroke carries both pressure fields around the display's inset border.
@interface BorderString : NSObject
@property(nonatomic, strong) CALayer *group, *glow, *fields;
@property(nonatomic, strong) CAGradientLayer *horizontal, *vertical;
@property(nonatomic, strong) CAShapeLayer *shape;
@end
@implementation BorderString
@end

// Pressure sources stay planted in screen coordinates while the card moves away.
struct Membrane {
  pip_motion::Point normal;
  double center = 0, stress = 0;
  double boundary = 0, sign = 1, lo = 0, hi = 0, anchor = 0;
  double bend = 0, bendVelocity = 0, pressedBend = 1;
};
struct BorderSample {
  pip_motion::Point point;
  double perimeter = 0, visibility = 0;
};
// Arc length joins the four straights and four quarter-circles without a corner seam.
struct BorderGeometry {
  pip_motion::Rect bounds;
  double radius;
  double straightWidth() const { return std::max(0.0, bounds.width - 2 * radius); }
  double straightHeight() const { return std::max(0.0, bounds.height - 2 * radius); }
  double quarter() const { return M_PI * radius / 2; }
  double perimeter() const { return 2 * (straightWidth() + straightHeight()) + 4 * quarter(); }
  std::array<double, 8> sections() const {
    return {straightWidth(), quarter(), straightHeight(), quarter(), straightWidth(), quarter(), straightHeight(), quarter()};
  }
  double source(int axis, double sign, double anchor) const {
    const double sw = straightWidth(), sh = straightHeight(), q = quarter();
    if (axis == 0) return sign > 0 ? sw + q + std::clamp(anchor - bounds.y - radius, 0.0, sh) :
        2 * sw + 3 * q + sh + std::clamp(bounds.y + bounds.height - radius - anchor, 0.0, sh);
    return sign < 0 ? std::clamp(anchor - bounds.x - radius, 0.0, sw) :
        sw + 2 * q + sh + std::clamp(bounds.x + bounds.width - radius - anchor, 0.0, sw);
  }
  pip_motion::Point point(double at) const {
    const double l = bounds.x, b = bounds.y, r = l + bounds.width, t = b + bounds.height;
    const auto lengths = sections();
    for (int section = 0; section < 8; ++section) {
      if (at > lengths[section] && section != 7) { at -= lengths[section]; continue; }
      if (section == 0) return {l + radius + at, b};
      if (section == 2) return {r, b + radius + at};
      if (section == 4) return {r - radius - at, t};
      if (section == 6) return {l, t - radius - at};
      const pip_motion::Point center = section == 1 ? pip_motion::Point{r - radius, b + radius} :
          section == 3 ? pip_motion::Point{r - radius, t - radius} :
          section == 5 ? pip_motion::Point{l + radius, t - radius} : pip_motion::Point{l + radius, b + radius};
      const double angle = (section - 3) * M_PI / 4 + at / std::max(.001, radius);
      return center + pip_motion::Point{std::cos(angle) * radius, std::sin(angle) * radius};
    }
    return {l + radius, b};
  }
};
static double perimeterDelta(double a, double b, double perimeter) {
  return std::remainder(a - b, perimeter);
}
struct Thread { double x, y, vx, vy, angle, spin, length, curl, phase; };
struct Speck { double x, y, vx, vy, radius; };

static CGColorRef gray(CGFloat white, CGFloat alpha) {
  return [NSColor colorWithWhite:white alpha:alpha].CGColor;
}
// Stress runs from relaxed white through yellow and orange to red at the breaking point.
static void stressColor(double s, double rgb[3]) {
  static const double stops[4][4] = {{0, 1, 1, 1}, {.3, 1, .93, .55}, {.62, 1, .6, .22}, {1, 1, .27, .22}};
  s = std::clamp(s, 0.0, 1.0);
  int i = 1;
  while (i < 3 && s > stops[i][0]) ++i;
  const double t = (s - stops[i - 1][0]) / (stops[i][0] - stops[i - 1][0]);
  for (int c = 0; c < 3; ++c) rgb[c] = stops[i - 1][c + 1] + (stops[i][c + 1] - stops[i - 1][c + 1]) * t;
}
static CGColorRef rgba(const double rgb[3], CGFloat alpha) {
  return [NSColor colorWithSRGBRed:rgb[0] green:rgb[1] blue:rgb[2] alpha:alpha].CGColor;
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
- (BOOL)canBecomeKeyWindow { return !self.ignoresMouseEvents; }
// Native glass has no public active-state control. Keep this appearance-only
// AppKit hook confined to the lab card; it does not change actual keyboard focus.
- (BOOL)hasKeyAppearance { return !self.ignoresMouseEvents; }
- (BOOL)_hasKeyAppearance { return !self.ignoresMouseEvents; }
@end

@interface MotionLab : NSObject <NSApplicationDelegate, NSWindowDelegate> {
  std::unique_ptr<Motion> motion;
  std::unique_ptr<pip_motion::Gestures> gestures;
  id gestureMonitor;
  NSMagnificationGestureRecognizer *pinchRecognizer;
  NSUInteger pinchEvents;
  NSString *lastPinchRoute;
  double lastPinchDelta;
  BOOL consumeTrackpadMomentum, suppressMouseUp;
  NSTimer *returnTimer;
  double returnStart;
  NSRect returnFrame;
  CATransform3D returnTransform;
  pip_motion::Point returnDelta;
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
  NSTimer *fileTimer, *saveTimer;
  // One display-synchronized frame drives the spring, window placement and visuals.
  // CADisplayLink on macOS 14+, a refresh-rate timer before that.
  id frameLink;
  NSTimer *frameTimer;
  BOOL framesRunning, animating, frameDirty, statusFresh;
  double lastTick, renderTime, lastStatusUpdate, lastRenderAt;
  // Last velocity-graph inputs, so an unchanged graph is not rebuilt.
  size_t traceKeyCount;
  double traceKeyTime, traceKeyValue, traceKeyFirst, traceKeyWidth, traceKeyHeight, traceKeyDX, traceKeyDY, traceKeyPeak;
  NSString *settingsPath, *statePath;
  NSData *lastSettingsData;
  NSDictionary *legacyPressThresholds;
  Feedback feedback;
  CALayer *stage, *ambientShadow, *contactShadow, *glowShadow, *overlay, *windowShade;
  CAGradientLayer *rimShade;
  CAShapeLayer *chevron, *rimLight, *meter, *ripple, *threadShape;
  CALayer *threadGlow, *stringRoot;
  CAShapeLayer *stringOcclusion;
  // Full-screen, click-through effects layer behind the PiP, in screen coordinates minus fxOrigin.
  ExamplePanel *fxPanel;
  CALayer *fxRoot, *dustGlow, *traceBox;
  CAShapeLayer *dustShape, *traceLine, *traceBase, *traceArrow, *traceDot;
  CATextLayer *traceValue, *traceTitle;
  PassView *cardHost, *cardContent;
  NSView *glassSurface;
  CAGradientLayer *glassTint, *glassEdge;
  CAShapeLayer *glassOutline;
  NSPoint fxOrigin;
  std::vector<Speck> dust;
  std::vector<std::pair<double, double>> traceSamples;
  pip_motion::Point traceDirection;
  double dustStart, flightPeak, flightDistance;
  double traceStart, tracePeak;
  BOOL wasSettling, stayDustDone, returnedToBrowser;
  BorderString *borderString;
  std::vector<BorderSample> borderSamples;
  std::array<Membrane, 2> membranes;
  std::vector<Thread> threads;
  double axisGlow[2], breakStart, breakRGB[3];
  BOOL axisPressed[2], wasPressing, cornerString;
  int straightStringAxis;
  BOOL pendingTrackpadPan;
  double meterAlpha, meterProgress, rippleStart, pressHudAlpha, pressHudFill, settleHudAlpha;
  CALayer *pressHud, *pressFill, *pressDockTick, *pressTuckTick, *settleHud, *settleFill;
  CATextLayer *pressValue, *pressDockLabel, *pressTuckLabel, *settleValue;
  double tiltX, tiltY, tiltVX, tiltVY, visVX, visVY, prevX, prevY, prevVelocityTime;
  CATextLayer *intentText, *cueText;
  NSButton *feedbackToggle, *hapticsToggle;
  NSMutableArray<NSSlider *> *feedbackSliders;
  NSMutableArray<NSTextField *> *feedbackFields;
  double lift, liftVelocity, castX, castY, settleAmount, settleVelocity, handSpeed, slowSince, glow, edgeAmount, leanX, leanY, shadowX, shadowY, lastVisualTime, releaseDistance, rimShadeStrength;
  Side chevronSide;
  BOOL leaning, awaitingLanding, moving, settleTapped, settleHudDone;
  double pressStart, lastHaptic, pendingSince;
  int hapticKey, pendingKey;
  Outcome stableOutcome;
  double lastEventTimestamp, lastEventUptime;
}
- (instancetype)initWithSettingsPath:(NSString *)path;
- (void)begin:(NSEvent *)event;
- (void)drag:(NSEvent *)event;
- (void)end:(NSEvent *)event;
- (BOOL)consumeGesture:(NSEvent *)event;
- (void)recognizePinch:(NSMagnificationGestureRecognizer *)recognizer;
@end

@implementation ExampleView
- (BOOL)acceptsFirstResponder { return YES; }
- (void)updateTrackingAreas {
  [super updateTrackingAreas];
  if (self.gestureTracking) [self removeTrackingArea:self.gestureTracking];
  self.gestureTracking = [[NSTrackingArea alloc] initWithRect:NSZeroRect
      options:NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect
      owner:self userInfo:nil];
  [self addTrackingArea:self.gestureTracking];
}
- (void)mouseEntered:(NSEvent *)event {
  // AppKit routes trackpad magnification through the key window. The nonactivating
  // panel can take gesture focus under the pointer without raising the settings window.
  if (!self.window.isKeyWindow) self.previousKeyWindow = NSApp.keyWindow;
  [NSApp activateIgnoringOtherApps:YES];
  [self.window makeKeyWindow]; [self.window makeFirstResponder:self];
}
- (void)mouseExited:(NSEvent *)event {
  if (!self.window.isKeyWindow) return;
  if (self.previousKeyWindow.visible) [self.previousKeyWindow makeKeyWindow];
  else [self.window resignKeyWindow];
  self.previousKeyWindow = nil;
}
- (BOOL)acceptsFirstMouse:(NSEvent *)event { return YES; }
- (BOOL)mouseDownCanMoveWindow { return NO; }
- (void)mouseDown:(NSEvent *)event { [self.lab begin:event]; }
- (void)mouseDragged:(NSEvent *)event { [self.lab drag:event]; }
- (void)mouseUp:(NSEvent *)event { [self.lab end:event]; }
- (void)scrollWheel:(NSEvent *)event {
  if (![self.lab consumeGesture:event]) [super scrollWheel:event];
}
@end

static NSView *makeGlassSurface(NSRect frame, NSView *content) {
  content.frame = NSMakeRect(0, 0, NSWidth(frame), NSHeight(frame));
  content.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
  content.wantsLayer = YES;
  content.layer.cornerRadius = kCardRadius; content.layer.masksToBounds = YES;
  NSWorkspace *workspace = NSWorkspace.sharedWorkspace;
  if (!workspace.accessibilityDisplayShouldReduceTransparency && !workspace.accessibilityDisplayShouldIncreaseContrast) {
    if (@available(macOS 26.0, *)) {
      NSGlassEffectView *glass = [[NSGlassEffectView alloc] initWithFrame:frame];
      glass.style = NSGlassEffectViewStyleClear;
      glass.cornerRadius = kCardRadius;
      glass.tintColor = [NSColor colorWithSRGBRed:.12 green:.26 blue:.32 alpha:.18];
      glass.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
      glass.contentView = content;
      return glass;
    }
    NSVisualEffectView *material = [[NSVisualEffectView alloc] initWithFrame:frame];
    material.material = NSVisualEffectMaterialHUDWindow;
    material.blendingMode = NSVisualEffectBlendingModeBehindWindow;
    material.state = NSVisualEffectStateActive;
    material.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
    material.wantsLayer = YES; material.layer.cornerRadius = kCardRadius; material.layer.masksToBounds = YES;
    [material addSubview:content];
    return material;
  }
  PassView *solid = [[PassView alloc] initWithFrame:frame];
  solid.wantsLayer = YES; solid.layer.cornerRadius = kCardRadius;
  solid.layer.backgroundColor = [NSColor colorWithSRGBRed:.06 green:.10 blue:.13 alpha:1].CGColor;
  [solid addSubview:content];
  return solid;
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
  gestures = std::make_unique<pip_motion::Gestures>(*motion);
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
      @"Daniel’s tuning: the lab defaults, saved from your Oct 28 session, with Press any edge and Smart drops: response 0.62, damping 0.76, projection 0.27, resistance 0.63, leave-here speed 800, inset 22, press to dock 2.4% and tuck 25%; lift 0.75, pickup shadow −0.44, shadow box 0.20, shadow intensity 1.10, settle 0.62 after 0.08 s with ease 0.28, press 0.40, edge shade 0.80, dock lean 40, dock shadow 0.90.\n\n"
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
  for (NSString *name in @[@"Feel", @"Edges", @"Cues", @"Effects"]) {
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
  NSTextField *effectsNote = label(@"Visual effects for the moving window. Each follows Release feedback.",
      NSMakeRect(12, pageTop + 4, pageWidth - 24, 18), 11);
  effectsNote.textColor = NSColor.secondaryLabelColor; [pages[3] addSubview:effectsNote];
  feedbackSliders = NSMutableArray.array; feedbackFields = NSMutableArray.array; feedbackHeadings = NSMutableArray.array;
  int rows[2] = {0, 0};
  for (size_t i = 0; i < feedbackParameterCount; ++i) {
    const auto& parameter = feedbackParameters[i];
    makeRow(@(parameter.label), @(parameter.help), parameter.low, parameter.high, feedback.*parameter.member, i,
            @selector(feedbackSliderChanged:), @selector(feedbackFieldChanged:),
            feedbackSliders, feedbackFields, feedbackHeadings);
    const int row = rows[parameter.effect]++;
    placeRow(parameter.effect ? pages[3] : cues, pageTop - 34 - row * 34, feedbackHeadings[i], @(parameter.help),
             feedbackSliders[i], feedbackFields[i]);
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
  // Effects that travel beyond the PiP's margin draw in a click-through window covering the screen.
  fxOrigin = screen.frame.origin;
  fxPanel = [[ExamplePanel alloc] initWithContentRect:screen.frame
      styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
      backing:NSBackingStoreBuffered defer:NO];
  fxPanel.opaque = NO; fxPanel.backgroundColor = NSColor.clearColor;
  fxPanel.hasShadow = NO; fxPanel.hidesOnDeactivate = NO; fxPanel.ignoresMouseEvents = YES;
  fxPanel.level = panel.level - 1; fxPanel.collectionBehavior = panel.collectionBehavior;
  PassView *fxView = [[PassView alloc] initWithFrame:NSMakeRect(0, 0, NSWidth(screen.frame), NSHeight(screen.frame))];
  fxView.layer = [CALayer layer]; fxView.wantsLayer = YES; fxPanel.contentView = fxView;
  fxRoot = fxView.layer;
  stringRoot = [CALayer layer]; stringRoot.frame = fxRoot.bounds;
  stringOcclusion = [CAShapeLayer layer]; stringOcclusion.frame = fxRoot.bounds;
  stringOcclusion.contentsScale = scale; stringOcclusion.fillRule = kCAFillRuleEvenOdd;
  stringOcclusion.fillColor = gray(0, 1); stringRoot.mask = stringOcclusion;
  [fxRoot addSublayer:stringRoot];
  auto glowingShape = [&](CALayer *__strong *halo, CAShapeLayer *__strong *shape, CGFloat bloom) {
    *halo = [CALayer layer]; (*halo).frame = fxRoot.bounds; (*halo).opacity = 0;
    (*halo).shadowOffset = CGSizeZero; (*halo).shadowOpacity = 1; (*halo).shadowRadius = bloom;
    (*halo).shadowColor = gray(1, 1);
    *shape = [CAShapeLayer layer]; (*shape).frame = fxRoot.bounds; (*shape).contentsScale = scale;
    (*shape).fillColor = nil; (*shape).strokeColor = gray(1, 1);
    (*shape).lineCap = kCALineCapRound; (*shape).lineJoin = kCALineJoinRound;
    [*halo addSublayer:*shape]; [fxRoot addSublayer:*halo];
  };
  glowingShape(&dustGlow, &dustShape, 3);
  dustShape.fillColor = gray(1, .85); dustShape.strokeColor = nil;
  // The dust glow uses the specks as its shadow path; match the fill's alpha.
  dustGlow.shadowOpacity = .85;
  // One stage holds the shadows, card and overlay so they lift and scale together.
  PassView *host = [[PassView alloc] initWithFrame:root.bounds];
  host.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
  host.layer = [CALayer layer]; host.wantsLayer = YES;
  [root addSubview:host];
  borderString = [BorderString new];
  borderString.group = [CALayer layer]; borderString.group.frame = fxRoot.bounds;
  borderString.group.opacity = 0;
  borderString.glow = [CALayer layer]; borderString.glow.frame = fxRoot.bounds;
  borderString.glow.shadowOffset = CGSizeZero; borderString.glow.shadowOpacity = 1;
  borderString.glow.shadowRadius = 18;
  borderString.fields = [CALayer layer]; borderString.fields.frame = fxRoot.bounds;
  borderString.shape = [CAShapeLayer layer]; borderString.shape.frame = fxRoot.bounds;
  borderString.shape.contentsScale = scale;
  borderString.shape.fillColor = nil; borderString.shape.strokeColor = gray(1, 1);
  borderString.shape.lineWidth = 4.5; borderString.shape.lineJoin = kCALineJoinRound;
  borderString.shape.lineCap = kCALineCapRound;
  borderString.fields.mask = borderString.shape;
  borderString.horizontal = [CAGradientLayer layer];
  borderString.vertical = [CAGradientLayer layer];
  for (CAGradientLayer *field in @[borderString.horizontal, borderString.vertical]) {
    field.frame = fxRoot.bounds; field.type = kCAGradientLayerRadial; field.opacity = 0;
    [borderString.fields addSublayer:field];
  }
  [borderString.glow addSublayer:borderString.fields];
  [borderString.group addSublayer:borderString.glow];
  [stringRoot addSublayer:borderString.group];
  cardHost = [[PassView alloc] initWithFrame:NSRectFromCGRect(card)];
  cardHost.wantsLayer = YES;
  [host addSubview:cardHost];
  stage = cardHost.layer;
  CGPathRef shape = CGPathCreateWithRoundedRect(stage.bounds, kCardRadius, kCardRadius, nullptr);
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
  cardContent = [[PassView alloc] initWithFrame:NSRectFromCGRect(stage.bounds)];
  glassSurface = makeGlassSurface(NSRectFromCGRect(stage.bounds), cardContent);
  glassSurface.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
  [cardHost addSubview:glassSurface];
  glassTint = [CAGradientLayer layer]; glassTint.frame = stage.bounds;
  glassTint.colors = @[(__bridge id)[NSColor colorWithSRGBRed:.38 green:.65 blue:.73 alpha:.09].CGColor,
      (__bridge id)[NSColor colorWithSRGBRed:.02 green:.06 blue:.09 alpha:.28].CGColor];
  glassTint.startPoint = CGPointMake(.2, 1); glassTint.endPoint = CGPointMake(.8, 0);
  [cardContent.layer addSublayer:glassTint];
  glassEdge = [CAGradientLayer layer]; glassEdge.frame = stage.bounds;
  glassEdge.colors = @[(__bridge id)gray(1, .12), (__bridge id)gray(1, .05), (__bridge id)gray(1, .55)];
  glassEdge.locations = @[@0, @.45, @1];
  glassOutline = [CAShapeLayer layer]; glassOutline.fillColor = nil;
  glassOutline.strokeColor = gray(1, 1); glassOutline.lineWidth = .8;
  glassEdge.mask = glassOutline;
  [cardContent.layer addSublayer:glassEdge];

  // Live readout on the card: what release would do, and which cues are animating.
  auto textLayer = [&](CGRect frame, NSFont *font, CGFloat alpha) {
    CATextLayer *text = [CATextLayer layer];
    text.frame = frame; text.contentsScale = scale;
    text.font = (__bridge CFTypeRef)font; text.fontSize = font.pointSize;
    text.foregroundColor = gray(1, alpha); text.truncationMode = kCATruncationEnd;
    text.shadowColor = gray(0, 1); text.shadowOpacity = .65;
    text.shadowRadius = 3; text.shadowOffset = CGSizeMake(0, -1);
    text.string = @"";
    [cardContent.layer addSublayer:text];
    return text;
  };
  intentText = textLayer(CGRectZero, [NSFont systemFontOfSize:11 weight:NSFontWeightMedium], .8);
  cueText = textLayer(CGRectZero, [NSFont monospacedDigitSystemFontOfSize:10 weight:NSFontWeightRegular], .8);

  // Overlay on the card: the screen rim's shadow, the chevron and the glowing border.
  overlay = [CALayer layer];
  overlay.frame = stage.bounds; overlay.cornerRadius = kCardRadius; overlay.masksToBounds = YES;
  [cardContent.layer addSublayer:overlay];
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
  CGPathRef rim = CGPathCreateWithRoundedRect(CGRectInset(overlay.bounds, .75, .75), kCardRadius - .75, kCardRadius - .75, nullptr);
  rimLight.path = rim; CGPathRelease(rim);
  rimLight.fillColor = nil; rimLight.strokeColor = gray(1, .9); rimLight.lineWidth = 1.5;
  rimLight.opacity = 0;
  [overlay addSublayer:rimLight];
  // Settle meter: the border traced clockwise from the top center, then a ripple on completion.
  CGMutablePathRef outline = CGPathCreateMutable();
  const CGRect border = CGRectInset(stage.bounds, 1, 1);
  const CGFloat bl = CGRectGetMinX(border), br = CGRectGetMaxX(border), bb = CGRectGetMinY(border), bt = CGRectGetMaxY(border);
  CGPathMoveToPoint(outline, nullptr, CGRectGetMidX(border), bt);
  CGPathAddArcToPoint(outline, nullptr, br, bt, br, CGRectGetMidY(border), kCardRadius - 1);
  CGPathAddArcToPoint(outline, nullptr, br, bb, CGRectGetMidX(border), bb, kCardRadius - 1);
  CGPathAddArcToPoint(outline, nullptr, bl, bb, bl, CGRectGetMidY(border), kCardRadius - 1);
  CGPathAddArcToPoint(outline, nullptr, bl, bt, CGRectGetMidX(border), bt, kCardRadius - 1);
  CGPathCloseSubpath(outline);
  auto outlineLayer = [&]() {
    CAShapeLayer *layer = [CAShapeLayer layer];
    layer.frame = stage.bounds; layer.contentsScale = scale; layer.path = outline;
    layer.fillColor = nil; layer.strokeColor = gray(1, .95); layer.lineWidth = 2; layer.lineCap = kCALineCapRound;
    layer.shadowColor = gray(1, 1); layer.shadowOffset = CGSizeZero; layer.shadowRadius = 4; layer.shadowOpacity = .7;
    layer.opacity = 0;
    [stage addSublayer:layer];
    return layer;
  };
  meter = outlineLayer(); meter.strokeEnd = 0;
  ripple = outlineLayer();
  CGPathRelease(outline);

  // Threads torn from a released membrane fly free of the PiP's margin, glowing in the stress color.
  glowingShape(&threadGlow, &threadShape, 6);
  [stringRoot addSublayer:threadGlow];
  threadShape.lineWidth = 1.25;

  // Recording meters: dark glass capsules floating beside the card, above everything else.
  auto text = [&](CALayer *parent, CGRect frame, NSFont *font, CGFloat alpha, NSString *alignment) {
    CATextLayer *layer = [CATextLayer layer];
    layer.frame = frame; layer.contentsScale = scale; layer.alignmentMode = alignment;
    layer.font = (__bridge CFTypeRef)font; layer.fontSize = font.pointSize;
    layer.foregroundColor = gray(1, alpha); layer.string = @"";
    [parent addSublayer:layer];
    return layer;
  };
  auto hud = [&](NSString *title, CALayer *__strong *fill, CATextLayer *__strong *value) {
    CALayer *box = [CALayer layer];
    box.bounds = CGRectMake(0, 0, kHudW, kHudH); box.cornerRadius = kHudH / 2;
    box.backgroundColor = gray(.08, .72); box.borderColor = gray(1, .18); box.borderWidth = .5;
    box.shadowColor = gray(0, 1); box.shadowOpacity = .35; box.shadowRadius = 14; box.shadowOffset = CGSizeMake(0, -4);
    box.opacity = 0;
    NSFont *titleFont = [NSFont systemFontOfSize:10 weight:NSFontWeightSemibold];
    CATextLayer *name = text(box, CGRectMake(18, 14, 54, 14), titleFont, 1, kCAAlignmentLeft);
    name.string = [[NSAttributedString alloc] initWithString:title attributes:@{NSFontAttributeName:titleFont,
        NSForegroundColorAttributeName:[NSColor colorWithWhite:1 alpha:.62], NSKernAttributeName:@1.6}];
    CALayer *track = [CALayer layer];
    track.frame = CGRectMake(kTrackX, kTrackY, kTrackW, 4); track.cornerRadius = 2; track.backgroundColor = gray(1, .16);
    [box addSublayer:track];
    CALayer *bar = [CALayer layer];
    bar.anchorPoint = CGPointMake(0, .5); bar.frame = CGRectMake(kTrackX, kTrackY, 0, 4); bar.cornerRadius = 2;
    bar.backgroundColor = gray(1, .96);
    bar.shadowColor = gray(1, 1); bar.shadowOpacity = .9; bar.shadowRadius = 5; bar.shadowOffset = CGSizeZero;
    [box addSublayer:bar];
    *fill = bar;
    *value = text(box, CGRectMake(kTrackX + kTrackW + 6, 12, kHudW - kTrackX - kTrackW - 24, 17),
        [NSFont monospacedDigitSystemFontOfSize:12 weight:NSFontWeightMedium], .95, kCAAlignmentRight);
    [host.layer addSublayer:box];
    return box;
  };
  pressHud = hud(@"PRESS", &pressFill, &pressValue);
  settleHud = hud(@"SETTLE", &settleFill, &settleValue);
  auto tick = [&](NSString *name, CALayer *__strong *mark, CATextLayer *__strong *caption) {
    CALayer *line = [CALayer layer];
    line.bounds = CGRectMake(0, 0, 1.5, 12); line.cornerRadius = .75; line.backgroundColor = gray(1, .75);
    [pressHud addSublayer:line];
    *mark = line;
    *caption = text(pressHud, CGRectMake(0, 0, 32, 11), [NSFont systemFontOfSize:8 weight:NSFontWeightMedium], .6,
        kCAAlignmentCenter);
    (*caption).string = name;
  };
  tick(@"dock", &pressDockTick, &pressDockLabel);
  tick(@"tuck", &pressTuckTick, &pressTuckLabel);

  // Velocity belongs to the glass card and inherits its motion and resizing.
  traceBox = [CALayer layer];
  traceBox.opacity = 0;
  NSFont *traceFont = [NSFont systemFontOfSize:10 weight:NSFontWeightSemibold];
  traceTitle = text(traceBox, CGRectZero, traceFont, 1, kCAAlignmentLeft);
  traceTitle.string = [[NSAttributedString alloc] initWithString:@"VELOCITY" attributes:@{NSFontAttributeName:traceFont,
      NSForegroundColorAttributeName:[NSColor colorWithWhite:1 alpha:.82], NSKernAttributeName:@1}];
  traceArrow = [CAShapeLayer layer]; traceArrow.bounds = CGRectMake(-8, -8, 16, 16); traceArrow.contentsScale = scale;
  traceArrow.strokeColor = gray(1, .8); traceArrow.fillColor = nil; traceArrow.lineWidth = 1.4;
  traceArrow.lineCap = kCALineCapRound; traceArrow.lineJoin = kCALineJoinRound;
  [traceBox addSublayer:traceArrow];
  traceValue = text(traceBox, CGRectZero,
      [NSFont monospacedDigitSystemFontOfSize:11 weight:NSFontWeightMedium], .95, kCAAlignmentRight);
  for (CATextLayer *label in @[traceTitle, traceValue]) {
    label.shadowColor = gray(0, 1); label.shadowOpacity = .4;
    label.shadowRadius = 3; label.shadowOffset = CGSizeMake(0, -1);
  }
  traceBase = [CAShapeLayer layer]; traceBase.frame = traceBox.bounds; traceBase.contentsScale = scale;
  traceBase.strokeColor = gray(1, .3); traceBase.lineWidth = 1; traceBase.lineDashPattern = @[@3, @3];
  traceBase.fillColor = nil;
  [traceBox addSublayer:traceBase];
  traceLine = [CAShapeLayer layer]; traceLine.frame = traceBox.bounds; traceLine.contentsScale = scale;
  traceLine.strokeColor = [NSColor colorWithSRGBRed:.66 green:.84 blue:.88 alpha:.9].CGColor;
  traceLine.lineWidth = 1.75; traceLine.fillColor = nil;
  traceLine.lineCap = kCALineCapRound; traceLine.lineJoin = kCALineJoinRound;
  traceLine.shadowColor = gray(1, 1); traceLine.shadowOpacity = .135; traceLine.shadowRadius = 2;
  traceLine.shadowOffset = CGSizeZero;
  [traceBox addSublayer:traceLine];
  traceDot = [CAShapeLayer layer]; traceDot.frame = traceBox.bounds; traceDot.contentsScale = scale;
  traceDot.fillColor = gray(1, .86);
  [traceBox addSublayer:traceDot];
  [cardContent.layer insertSublayer:traceBox below:overlay];
  // Shade the composed window, including native glass chrome, rather than only its content.
  windowShade = [CALayer layer]; windowShade.frame = stage.bounds;
  windowShade.cornerRadius = kCardRadius; windowShade.masksToBounds = YES; windowShade.zPosition = 1;
  [stage addSublayer:windowShade];
  [windowShade addSublayer:rimShade];
  [windowShade addSublayer:chevron];
  [self layoutCardContent];

  // Transparent, unscaled event target over the card.
  example = [[ExampleView alloc] initWithFrame:NSRectFromCGRect(card)];
  example.lab = self;
  example.allowedTouchTypes = NSTouchTypeMaskIndirect;
  [root addSubview:example];
  pinchRecognizer = [[NSMagnificationGestureRecognizer alloc] initWithTarget:self action:@selector(recognizePinch:)];
  pinchRecognizer.delaysMagnificationEvents = YES;
  [example addGestureRecognizer:pinchRecognizer];
  __weak MotionLab *weakSelf = self;
  gestureMonitor = [NSEvent addLocalMonitorForEventsMatchingMask:
      NSEventMaskScrollWheel | NSEventMaskMagnify handler:^NSEvent *(NSEvent *event) {
    MotionLab *lab = weakSelf;
    if (!lab) return event;
    // Let the card's native recognizer own its stream. Events addressed to the
    // settings window still use the screen-coordinate monitor adapter.
    if (event.type == NSEventTypeMagnify) {
      ++lab->pinchEvents; lab->lastPinchRoute = @"monitor"; lab->lastPinchDelta = event.magnification;
      // Per-event logging is opt-in; state.json is written once the pinch ends.
      static const bool logPinch = getenv("OPUS_PIP_LOG_PINCH") != nullptr;
      if (logPinch) {
        const NSPoint point = event.window ? [event.window convertPointToScreen:event.locationInWindow] : event.locationInWindow;
        fprintf(stderr, "pinch event phase=%lu window=%ld key=%ld card_key=%d point=(%.1f,%.1f) delta=%.5f\n",
            (unsigned long)event.phase, (long)event.window.windowNumber, (long)NSApp.keyWindow.windowNumber,
            lab->panel.isKeyWindow, point.x, point.y, event.magnification);
      }
      if (event.window == lab->panel) return event;
    }
    return [lab consumeGesture:event] ? nil : event;
  }];
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
  [fxPanel orderWindow:NSWindowBelow relativeTo:panel.windowNumber];
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
  [self wakeVisuals];
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
- (void)reset:(id)sender {
  [self cancelReturnAnimation];
  pendingTrackpadPan = NO;
  const BOOL wasReturned = returnedToBrowser;
  returnedToBrowser = NO; suppressMouseUp = NO; consumeTrackpadMomentum = NO;
  releaseDistance = 0; awaitingLanding = NO; motion->reset(); [self showPosition]; [self stopAnimation];
  if (wasReturned) {
    [panel orderFrontRegardless];
    [fxPanel orderWindow:NSWindowBelow relativeTo:panel.windowNumber];
  }
}
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
  consumeTrackpadMomentum = NO; pendingTrackpadPan = NO;
  if (returnedToBrowser) return;
  if (gestures->kind() == pip_motion::Gestures::Kind::Pinch) { suppressMouseUp = YES; return; }
  if (event.clickCount == 2 && motion->tucked == Side::None) {
    suppressMouseUp = YES;
    [self returnToBrowser];
    return;
  }
  [NSApp activateIgnoringOtherApps:YES];
  [panel makeKeyWindow]; [panel makeFirstResponder:example];
  [self stopAnimation]; [self noteEvent:event];
  stayDustDone = NO;
  awaitingLanding = NO; hapticKey = pendingKey = -1; slowSince = -1; settleTapped = NO;
  motion->begin([self point:event], event.timestamp);
  [self haptic:NSHapticFeedbackPatternAlignment];
  [self showPosition];
}
- (void)drag:(NSEvent *)event {
  if (returnedToBrowser || gestures->kind() == pip_motion::Gestures::Kind::Pinch) return;
  [self noteEvent:event];
  motion->drag([self point:event], event.timestamp); [self showPosition];
}
- (void)end:(NSEvent *)event {
  if (suppressMouseUp) { suppressMouseUp = NO; return; }
  motion->end(event.timestamp);
  releaseDistance = length(motion->target - motion->position);
  awaitingLanding = YES;
  [self startAnimation];
}
- (void)recognizePinch:(NSMagnificationGestureRecognizer *)recognizer {
  if (returnedToBrowser || motion->tucked != Side::None) return;
  const BOOL cancelled = recognizer.state == NSGestureRecognizerStateCancelled || recognizer.state == NSGestureRecognizerStateFailed;
  const BOOL ended = recognizer.state == NSGestureRecognizerStateEnded;
  if (recognizer.state == NSGestureRecognizerStatePossible) return;
  ++pinchEvents; lastPinchRoute = @"recognizer"; lastPinchDelta = recognizer.magnification;
  consumeTrackpadMomentum = NO; pendingTrackpadPan = NO;
  if (gestures->kind() != pip_motion::Gestures::Kind::Pinch) {
    if (cancelled || ended) return;
    [self stopAnimation]; awaitingLanding = NO; gestures->beginPinch();
  }
  if (!cancelled) gestures->magnify(recognizer.magnification);
  recognizer.magnification = 0;
  if (cancelled || ended) gestures->endPinch(cancelled);
  [self showPosition];
}
- (BOOL)consumeGesture:(NSEvent *)event {
  if (returnedToBrowser) return NO;
  const BOOL magnify = event.type == NSEventTypeMagnify;
  if (!magnify && event.type != NSEventTypeScrollWheel) return NO;
  // Ownership belongs to one scroll sequence, including its trailing inertia.
  // A new sequence over another window must clear the previous card's ownership.
  if (magnify || (event.momentumPhase == NSEventPhaseNone &&
      ((event.phase & (NSEventPhaseBegan | NSEventPhaseMayBegin)) || event.phase == NSEventPhaseNone))) {
    consumeTrackpadMomentum = NO; pendingTrackpadPan = NO;
  }
  if (!magnify && !event.hasPreciseScrollingDeltas) return NO;
  if (!magnify && event.momentumPhase != NSEventPhaseNone) {
    const BOOL consume = consumeTrackpadMomentum;
    if (event.momentumPhase & (NSEventPhaseEnded | NSEventPhaseCancelled))
      consumeTrackpadMomentum = NO;
    return consume;
  }
  const BOOL active = gestures->kind() != pip_motion::Gestures::Kind::None || pendingTrackpadPan;
  const NSPoint point = event.window ? [event.window convertPointToScreen:event.locationInWindow]
                                    : event.locationInWindow;
  const NSRect card = NSMakeRect(motion->position.x, motion->position.y,
                                 motion->size.width, motion->size.height);
  if (!active && !NSPointInRect(point, card)) return NO;
  const BOOL cancelled = (event.phase & NSEventPhaseCancelled) != 0;
  const BOOL ended = (event.phase & NSEventPhaseEnded) != 0;
  [self noteEvent:event];
  if (magnify) {
    pendingTrackpadPan = NO;
    if (motion->tucked != Side::None) return NO;
    if (!active && (ended || cancelled)) return NO;
    if (gestures->kind() != pip_motion::Gestures::Kind::Pinch) {
      [self stopAnimation];
      awaitingLanding = NO;
      gestures->beginPinch();
    }
    if (!cancelled) gestures->magnify(event.magnification);
    if (ended || cancelled || event.phase == NSEventPhaseNone)
      gestures->endPinch(cancelled);
    [self showPosition];
    return YES;
  }
  if (gestures->kind() == pip_motion::Gestures::Kind::Pinch) return YES;
  if (event.phase == NSEventPhaseNone) return NO;
  if (gestures->kind() != pip_motion::Gestures::Kind::Pan) {
    if (ended || cancelled) {
      const BOOL owned = pendingTrackpadPan; pendingTrackpadPan = NO; return owned;
    }
    if (event.phase & (NSEventPhaseBegan | NSEventPhaseMayBegin)) {
      pendingTrackpadPan = YES; consumeTrackpadMomentum = YES;
    }
    // A zero-delta prelude is not pickup. Pinch recognition cancels this pending
    // pan, and its leftover Changed events cannot create a new pickup afterward.
    if (!pendingTrackpadPan) return NO;
    if (event.scrollingDeltaX == 0 && event.scrollingDeltaY == 0) return YES;
    pendingTrackpadPan = NO;
    [self stopAnimation];
    stayDustDone = NO; awaitingLanding = NO; hapticKey = pendingKey = -1;
    slowSince = -1; settleTapped = NO;
    gestures->beginPan(event.timestamp);
  }
  consumeTrackpadMomentum = YES;
  if (!cancelled)
    gestures->pan({event.scrollingDeltaX, -event.scrollingDeltaY}, event.timestamp);
  if (ended || cancelled) {
    gestures->endPan(event.timestamp, cancelled);
    releaseDistance = length(motion->target - motion->position);
    awaitingLanding = !cancelled;
    [self startAnimation];
  } else [self showPosition];
  return YES;
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
- (void)wakeVisuals { [self requestFrame]; }
// Marks the card for the next display frame. When frames are idle, renders now so the first
// response to input is not delayed, then keeps frames running until everything has settled.
- (void)requestFrame {
  if (returnedToBrowser) return;
  frameDirty = YES;
  // A stalled link (display asleep, window between screens) must not freeze the card.
  if (framesRunning && CACurrentMediaTime() - lastRenderAt < .1) return;
  const BOOL wasRunning = framesRunning;
  [self startFrames];  // Before rendering, so a nested request only marks the frame dirty.
  if (!wasRunning) lastVisualTime = CACurrentMediaTime();
  [self renderAt:CACurrentMediaTime()];
}
- (void)startFrames {
  if (framesRunning || returnedToBrowser) return;
  framesRunning = YES;
  if (@available(macOS 14.0, *)) {
    if (!frameLink) {
      // A view's display link follows the display the card is on.
      CADisplayLink *link = [panel.contentView displayLinkWithTarget:self selector:@selector(displayFrame:)];
      [link addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
      frameLink = link;
    }
    [self matchFrameRate];
    ((CADisplayLink *)frameLink).paused = NO;
  } else {
    const NSInteger rate = std::max<NSInteger>(60, (panel.screen ?: NSScreen.mainScreen).maximumFramesPerSecond);
    frameTimer = [NSTimer timerWithTimeInterval:1.0 / rate target:self selector:@selector(timerFrame:) userInfo:nil repeats:YES];
    frameTimer.tolerance = 0;
    [NSRunLoop.mainRunLoop addTimer:frameTimer forMode:NSRunLoopCommonModes];
  }
}
// Ask for the card's display's full rate, so ProMotion and faster external displays are not capped.
- (void)matchFrameRate API_AVAILABLE(macos(14.0)) {
  const float rate = std::max<NSInteger>(60, (panel.screen ?: NSScreen.mainScreen).maximumFramesPerSecond);
  CADisplayLink *link = frameLink;
  if (link.preferredFrameRateRange.preferred != rate) link.preferredFrameRateRange = CAFrameRateRangeMake(60, rate, rate);
}
- (void)stopFrames {
  framesRunning = NO;
  if (@available(macOS 14.0, *)) ((CADisplayLink *)frameLink).paused = YES;
  [frameTimer invalidate]; frameTimer = nil;
}
- (void)displayFrame:(CADisplayLink *)link API_AVAILABLE(macos(14.0)) {
  [self matchFrameRate];
  [self renderAt:link.targetTimestamp];
}
- (void)timerFrame:(NSTimer *)timer { [self renderAt:CACurrentMediaTime()]; }
// One frame: step the spring to the time this frame is shown, place the window, draw once.
- (void)renderAt:(double)target {
  if (returnedToBrowser) { [self stopFrames]; return; }
  frameDirty = NO;
  lastRenderAt = CACurrentMediaTime();
  BOOL finishedSettle = NO;
  if (animating) {
    motion->step(std::clamp(target - lastTick, 0.0, .05)); lastTick = target;
    if (motion->phase != Phase::Settling) {
      animating = NO; finishedSettle = YES;
      if (awaitingLanding) [self land];
    }
  }
  [self placeWindow];
  [self updateStatus:finishedSettle];
  renderTime = target;
  const BOOL settled = [self updateVisuals];
  renderTime = 0;
  if (finishedSettle) [self writeState];
  if (settled && !animating && !frameDirty &&
      motion->phase != Phase::Dragging && motion->phase != Phase::Settling) [self stopFrames];
}
- (void)placeWindow {
  const CGFloat w = motion->size.width, h = motion->size.height;
  const NSRect frame = NSMakeRect(motion->position.x - kPad, motion->position.y - kPad, w + 2 * kPad, h + 2 * kPad);
  if (!NSEqualSizes(panel.frame.size, frame.size)) [panel setFrame:frame display:NO];
  else if (!NSEqualPoints(panel.frame.origin, frame.origin)) [panel setFrameOrigin:frame.origin];
}
// Physical cues derived from the release prediction: lift, hold glow, rim shadow and dock lean.
// Returns YES once every smoothed value has reached its target.
- (BOOL)updateVisuals {
  if (returnedToBrowser) return YES;
  const double now = renderTime > 0 ? renderTime : CACurrentMediaTime();
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
  // The tap and particles share one completion event, rearmed once the card lifts back up.
  bool staySettled = false;
  if (dragging && keep && on && feedback.settle > 0 && !settleTapped && settleAmount >= .95) {
    settleTapped = YES; staySettled = true; rippleStart = now; [self haptic:NSHapticFeedbackPatternAlignment];
  } else if (!keep || settleAmount < .5) settleTapped = NO;
  if (dragging && (!keep || settleAmount < .5)) stayDustDone = NO;
  approach(glow, on ? glowTarget : 0, .09, .14, dt);
  approach(edgeAmount, on ? edgeTarget : 0, .12, .14, dt);
  approach(leanX, leanTarget.x, .08, .10, dt);
  approach(leanY, leanTarget.y, .08, .10, dt);
  approach(shadowX, shadowTarget.x, .26, .16, dt);
  approach(shadowY, shadowTarget.y, .26, .16, dt);

  // Presented velocity for tilt and stretch, measured across frames at least 4 ms apart. After
  // an idle gap it restarts from rest, so a jump while the timer slept is not read as a flick.
  const double vdt = now - prevVelocityTime;
  if (vdt > .25) { prevX = position.x; prevY = position.y; prevVelocityTime = now; visVX = visVY = 0; }
  else if (vdt >= .004) {
    double rx = (position.x - prevX) / vdt, ry = (position.y - prevY) / vdt;
    const double fast = std::hypot(rx, ry);
    if (fast > 5000) { rx *= 5000 / fast; ry *= 5000 / fast; }
    const double blend = 1 - std::exp(-vdt / .05);
    visVX += (rx - visVX) * blend; visVY += (ry - visVY) * blend;
    prevX = position.x; prevY = position.y; prevVelocityTime = now;
    if (std::hypot(visVX, visVY) < 1 && rx == 0 && ry == 0) visVX = visVY = 0;
  }
  // Tilt: the leading edge tips away with speed and springs flat, with a little wobble, on stopping.
  const bool reduceMotion = NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion;
  const double maxTilt = on && !reduceMotion ? feedback.tilt * M_PI / 180 : 0;
  pip_motion::spring(tiltY, tiltVY, maxTilt * std::tanh(visVX / 1600), .32, .6, dt);
  pip_motion::spring(tiltX, tiltVX, -maxTilt * std::tanh(visVY / 1600), .32, .6, dt);
  if (visVX == 0 && visVY == 0 && std::abs(tiltX) + std::abs(tiltY) < 1e-4 && std::abs(tiltVX) + std::abs(tiltVY) < 1e-3)
    tiltX = tiltY = tiltVX = tiltVY = 0;
  // The settle meter keeps its last progress while it fades after release.
  if (dragging) meterProgress = std::clamp(settleAmount / .95, 0.0, 1.0);
  const double meterTarget = on && dragging && keep && settleAmount > .02 ? 1 : 0;
  approach(meterAlpha, meterTarget, .08, .2, dt);
  const bool pressMode = on && dragging && motion->settings.docking == Docking::AllEdges && length(motion->pressed) > .5;

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
  // The card view stays put; lean is a layer translation so the glass view is not laid out per frame.
  const CGRect home = CGRectMake(kPad, kPad, w, h);
  if (!NSEqualRects(cardHost.frame, NSRectFromCGRect(home))) cardHost.frame = NSRectFromCGRect(home);
  // Fast flicks stretch the card along its travel, then lift scale, then tilt in perspective.
  const double speed = std::hypot(visVX, visVY);
  const double stretch = on && !reduceMotion ? feedback.stretch / 100 * smoothstep((speed - 600) / 2400) : 0;
  CATransform3D transform = CATransform3DMakeScale(cardScale, cardScale, 1);
  if (stretch > 1e-4) {
    const double angle = std::atan2(visVY, visVX);
    const CATransform3D along = CATransform3DConcat(CATransform3DConcat(CATransform3DMakeRotation(-angle, 0, 0, 1),
        CATransform3DMakeScale(1 + stretch, 1 - stretch / 2, 1)), CATransform3DMakeRotation(angle, 0, 0, 1));
    transform = CATransform3DConcat(along, transform);
  }
  if (tiltX != 0 || tiltY != 0) {
    CATransform3D perspective = CATransform3DIdentity; perspective.m34 = -1.0 / 900;
    transform = CATransform3DConcat(CATransform3DConcat(CATransform3DConcat(transform,
        CATransform3DMakeRotation(tiltY, 0, 1, 0)), CATransform3DMakeRotation(tiltX, 1, 0, 0)), perspective);
  }
  if (leanX != 0 || leanY != 0) transform = CATransform3DConcat(transform, CATransform3DMakeTranslation(leanX, leanY, 0));
  stage.transform = transform;
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
  // Landing: the contact shadow flares outward, then tightens past rest before easing back.
  const double landAge = now - pressStart, landTime = .45;
  const bool landing = on && feedback.landingShadow > 0 && pressStart > 0 && landAge >= 0 && landAge < landTime;
  if (landing) {
    const double u = landAge / landTime;
    const double flare = std::sin(2 * M_PI * u) * std::exp(-2.2 * u) * feedback.landingShadow;
    contactShadow.shadowRadius = std::max(1.5, contactShadow.shadowRadius + 9 * flare);
    contactShadow.shadowOpacity = std::clamp(contactShadow.shadowOpacity * (1 + .9 * flare), 0.0, 1.0);
  }
  glowShadow.shadowOpacity = .45 * glow * feedback.glow;
  rimLight.opacity = .6 * glow * feedback.glow;

  // Settle meter traces the border as it settles; completion sends a ripple outward with the tap.
  meter.strokeEnd = meterProgress;
  meter.opacity = meterAlpha * feedback.settleMeter;
  const double rippleAge = now - rippleStart, rippleTime = .55;
  const bool rippling = on && rippleStart > 0 && rippleAge >= 0 && rippleAge < rippleTime;
  if (rippling) {
    const double u = rippleAge / rippleTime, grow = 22 * (1 - (1 - u) * (1 - u));
    ripple.transform = CATransform3DMakeScale(1 + 2 * grow / w, 1 + 2 * grow / h, 1);
    ripple.opacity = (1 - u) * (1 - u) * feedback.settleMeter;
  } else ripple.opacity = 0;

  // Straight edge strings join into the inset border loop only during a corner press.
  const pip_motion::Point depthNow = motion->depth();
  const pip_motion::Point panelOrigin{position.x - kPad, position.y - kPad};
  const double grow = (cardScale - 1) / 2;
  const double cardL = kPad + leanX - w * grow, cardR = kPad + leanX + w * (1 + grow);
  const double cardB = kPad + leanY - h * grow, cardT = kPad + leanY + h * (1 + grow);
  const pip_motion::Point pressedNow = motion->pressed;
  auto falloff = [](double outside) { return std::exp(-outside * outside / (105.0 * 105.0)); };
  const auto work = motion->area();
  const double inset = motion->settings.margin;
  double left = work.x + inset, right = work.x + work.width - inset;
  double bottom = work.y + inset, top = work.y + work.height - inset;
  // Preserve the resistance boundary during the rebound, including a restored tucked card.
  for (int axis = 0; axis < 2; ++axis) if (axisGlow[axis] > 0) {
    const auto& m = membranes[axis];
    (axis == 0 ? (m.sign < 0 ? left : right) : (m.sign < 0 ? bottom : top)) = m.boundary;
  }
  auto geometry = [&]() {
    const double width = std::max(1.0, right - left), height = std::max(1.0, top - bottom);
    return BorderGeometry{{left, bottom, width, height}, std::min({double(kCardRadius), width / 2, height / 2})};
  };

  // A tuck consumes every visible part of the loop, including the joined corner and center.
  if (wasPressing && !dragging && motion->decision == Decision::Tuck) {
    static std::mt19937 rng{std::random_device{}()};
    std::uniform_real_distribution<double> unit(0, 1);
    auto r = [&](double a, double b) { return a + (b - a) * unit(rng); };
    const auto border = geometry();
    const double perimeter = border.perimeter();
    double peakStress = -1;
    for (int axis = 0; axis < 2; ++axis) if (axisPressed[axis] && membranes[axis].stress > peakStress) {
      peakStress = membranes[axis].stress; stressColor(peakStress, breakRGB);
    }
    for (size_t first = 0; first + 1 < borderSamples.size(); first += 6) {
      const size_t last = std::min(borderSamples.size() - 1, first + 6);
      double visible = 0;
      for (size_t i = first; i <= last; ++i) visible = std::max(visible, borderSamples[i].visibility);
      if (visible < .01) continue;
      const auto& a = borderSamples[first]; const auto& b = borderSamples[last];
      const double at = (a.perimeter + b.perimeter) / 2;
      int owner = 0; double strongest = -1;
      for (int axis = 0; axis < 2; ++axis) {
        const auto& m = membranes[axis];
        const double distance = std::abs(perimeterDelta(at, border.source(axis, m.sign, m.anchor), perimeter));
        const double strength = axisGlow[axis] * falloff(std::max(0.0, distance - (m.hi - m.lo) / 2));
        if ((!cornerString && axis == straightStringAxis) || (cornerString && strength > strongest)) {
          strongest = strength; owner = axis;
        }
      }
      const auto& m = membranes[owner];
      const double away = perimeterDelta(at, border.source(owner, m.sign, m.anchor), perimeter) < 0 ? -1 : 1;
      const pip_motion::Point tangent = owner == 0 ? pip_motion::Point{0, m.sign} : pip_motion::Point{-m.sign, 0};
      const double local = std::max(.25, m.stress) * (.35 + .65 * strongest);
      const double along = away * (140 + 560 * local) * r(.6, 1.25), inward = (100 + 300 * local) * r(.55, 1.2);
      Thread thread;
      thread.x = a.point.x; thread.y = a.point.y;
      thread.vx = tangent.x * along - m.normal.x * inward;
      thread.vy = tangent.y * along - m.normal.y * inward;
      thread.angle = std::atan2(b.point.y - a.point.y, b.point.x - a.point.x);
      thread.length = length(b.point - a.point); thread.spin = r(-5, 5) * (.5 + local);
      thread.curl = r(-.1, .1) * thread.length; thread.phase = r(0, 2 * M_PI);
      threads.push_back(thread);
    }
    for (int axis = 0; axis < 2; ++axis) {
      axisGlow[axis] = 0; membranes[axis].bend = membranes[axis].bendVelocity = 0;
    }
    borderSamples.clear(); borderString.shape.path = nil; borderString.group.opacity = 0;
    if (peakStress >= 0) breakStart = now;
  }

  // Each field's radial reach in fx coordinates; the string is invisible outside every field.
  CGPoint fieldCenter[2] = {}; CGSize fieldRadius[2] = {};
  for (int axis = 0; axis < 2; ++axis) {
    Membrane& m = membranes[axis];
    const bool side = axis == 0;
    const double pushed = side ? pressedNow.x : pressedNow.y;
    const bool active = pressMode && std::abs(pushed) > .5;
    if (active) {
      const double lo = side ? cardB : cardL, hi = side ? cardT : cardR;
      const double sign = pushed < 0 ? -1 : 1;
      const double edge = pushed < 0 ? (side ? cardL : cardB) : (side ? cardR : cardT);
      const double boundary = (pushed < 0 ? kPad : kPad + (side ? w : h)) - pushed;
      const double center = (lo + hi) / 2 + (side ? panelOrigin.y : panelOrigin.x);
      if (!axisPressed[axis]) m.anchor = center;
      m.anchor = std::clamp(m.anchor, center - 120, center + 120);
      m.boundary = boundary + (side ? panelOrigin.x : panelOrigin.y); m.sign = sign;
      m.lo = lo + (side ? panelOrigin.y : panelOrigin.x);
      m.hi = hi + (side ? panelOrigin.y : panelOrigin.x); m.center = center;
      m.bend = std::max(0.0, sign * (edge - boundary) + 1.5); m.bendVelocity = 0;
      m.pressedBend = std::max(1.0, m.bend);
      const double depth = std::abs(side ? depthNow.x : depthNow.y);
      m.stress = std::clamp(depth / (side ? std::max(1.0, motion->settings.press_tuck) :
          2.5 * std::max(.5, motion->settings.press_dock)), 0.0, 1.0);
      m.normal = side ? pip_motion::Point{sign, 0} : pip_motion::Point{0, sign};
      (side ? (sign < 0 ? left : right) : (sign < 0 ? bottom : top)) = m.boundary;
    } else if (m.bend != 0 || m.bendVelocity != 0) {
      pip_motion::spring(m.bend, m.bendVelocity, 0, .24, .22, dt);
      if (std::abs(m.bend) < .05 && std::abs(m.bendVelocity) < 1) m.bend = m.bendVelocity = 0;
    }
    axisPressed[axis] = active;
    approach(axisGlow[axis], active ? 1 : 0, .05, .45, dt);
    CAGradientLayer *field = side ? borderString.horizontal : borderString.vertical;
    field.opacity = axisGlow[axis];
    if (axisGlow[axis] > 0) {
      const double span = m.hi - m.lo, reach = span / 2 + 260;
      const double crossReach = std::max(reach, std::abs(m.bend) + 80);
      const CGPoint center = side ? CGPointMake(m.boundary - fxOrigin.x, m.anchor - fxOrigin.y) :
          CGPointMake(m.anchor - fxOrigin.x, m.boundary - fxOrigin.y);
      // Start and end points are set once the string's bounds are known.
      fieldCenter[axis] = center;
      fieldRadius[axis] = CGSizeMake(side ? crossReach : reach, side ? reach : crossReach);
      const double stress = active ? m.stress : m.stress * std::min(1.0, std::abs(m.bend) / m.pressedBend);
      double rgb[3]; stressColor(stress, rgb);
      field.colors = @[(__bridge id)rgba(rgb, 1), (__bridge id)rgba(rgb, 1),
          (__bridge id)gray(1, .65), (__bridge id)gray(1, 0)];
      field.locations = @[@0, @(std::min(.85, (span / 2 + 170) / reach)), @.92, @1];
    }
  }
  // The rounded loop is reserved for an actual two-edge corner press. Keep the
  // last held shape during release so its rebound or break remains continuous.
  if (pressMode) {
    const bool corner = axisPressed[0] && axisPressed[1] &&
        std::abs(depthNow.x) >= motion->settings.press_dock &&
        std::abs(depthNow.y) >= motion->settings.press_dock;
    if (!corner && (cornerString || !axisPressed[straightStringAxis]))
      straightStringAxis = axisPressed[0] && (!axisPressed[1] || std::abs(depthNow.x) >= std::abs(depthNow.y)) ? 0 : 1;
    cornerString = corner;
  }
  borderString.horizontal.opacity = cornerString || straightStringAxis == 0 ? axisGlow[0] : 0;
  borderString.vertical.opacity = cornerString || straightStringAxis == 1 ? axisGlow[1] : 0;
  if (axisGlow[0] > 0 || axisGlow[1] > 0) {
    const auto border = geometry();
    const double perimeter = border.perimeter();
    const auto sections = border.sections();
    CGMutablePathRef path = CGPathCreateMutable();
    borderSamples.clear();
    if (cornerString) {
      // The loop circles the whole work area, but only the part inside a glow field can show.
      // Samples stay complete for tearing; the drawn path skips the invisible stretches.
      auto inField = [&](CGPoint p) {
        for (int axis = 0; axis < 2; ++axis) if (axisGlow[axis] > 0) {
          const double rx = fieldRadius[axis].width + 8, ry = fieldRadius[axis].height + 8;
          const double dx = (p.x - fieldCenter[axis].x) / rx, dy = (p.y - fieldCenter[axis].y) / ry;
          if (dx * dx + dy * dy <= 1) return true;
        }
        return false;
      };
      bool drawing = false, closed = true;
      CGPoint previous = CGPointZero;
      double travelled = 0;
      for (size_t edge = 0; edge < sections.size(); ++edge) {
        const double edgeLength = sections[edge];
        const int count = std::max(1, int(std::ceil(edgeLength / 4)));
        for (int i = edge == 0 ? 0 : 1; i <= count; ++i) {
          const double t = double(i) / count, at = travelled + t * edgeLength;
          auto point = border.point(at);
          double visibility = 0;
          for (int axis = 0; axis < 2; ++axis) if (axisGlow[axis] > 0) {
            const auto& m = membranes[axis];
            const double distance = std::abs(perimeterDelta(at, border.source(axis, m.sign, m.anchor), perimeter));
            const double halfSpan = (m.hi - m.lo) / 2, reach = halfSpan + 260;
            point = point + m.normal * (m.bend * falloff(std::max(0.0, distance - halfSpan)));
            visibility = std::max(visibility, axisGlow[axis] * std::clamp((reach - distance) / (reach * .44), 0.0, 1.0));
          }
          const CGPoint local = CGPointMake(point.x - fxOrigin.x, point.y - fxOrigin.y);
          // Each drawn run extends one sample past the field on both sides, where it is transparent.
          const bool inside = inField(local);
          if (inside && !drawing) {
            if (borderSamples.empty()) CGPathMoveToPoint(path, nullptr, local.x, local.y);
            else {
              CGPathMoveToPoint(path, nullptr, previous.x, previous.y);
              CGPathAddLineToPoint(path, nullptr, local.x, local.y);
            }
            drawing = true;
          } else if (drawing) {
            CGPathAddLineToPoint(path, nullptr, local.x, local.y);
            if (!inside) { drawing = false; closed = false; }
          } else closed = false;
          previous = local;
          borderSamples.push_back({point, at, visibility});
        }
        travelled += edgeLength;
      }
      if (closed) CGPathCloseSubpath(path);
    } else {
      const int axis = straightStringAxis;
      const auto& m = membranes[axis];
      const bool side = axis == 0;
      const double offset = side ? fxOrigin.y : fxOrigin.x;
      const double reach = (m.hi - m.lo) / 2 + 260;
      const double extent = side ? fxRoot.bounds.size.height : fxRoot.bounds.size.width;
      const double a0 = std::max(offset + 10, m.anchor - reach);
      const double a1 = std::min(offset + extent - 10, m.anchor + reach);
      for (double u = a0; u <= a1 + .01; u += 4) {
        const double distance = std::abs(u - m.anchor);
        const double bend = m.bend * falloff(std::max({0.0, m.lo - u, u - m.hi}));
        const double cross = m.boundary + m.sign * bend;
        const pip_motion::Point point = side ? pip_motion::Point{cross, u} : pip_motion::Point{u, cross};
        const CGPoint local = CGPointMake(point.x - fxOrigin.x, point.y - fxOrigin.y);
        if (borderSamples.empty()) CGPathMoveToPoint(path, nullptr, local.x, local.y);
        else CGPathAddLineToPoint(path, nullptr, local.x, local.y);
        const double at = border.source(axis, m.sign, m.anchor) + (side ? m.sign : -m.sign) * (u - m.anchor);
        const double visible = axisGlow[axis] * std::clamp((reach - distance) / (reach * .44), 0.0, 1.0);
        borderSamples.push_back({point, at, visible});
      }
    }
    // Size the string's gradient, mask and glow layers to what it covers rather than the screen,
    // keeping fx coordinates inside them. The margin holds the widest glow.
    CGRect extent = CGPathIsEmpty(path) ? CGRectNull : CGPathGetPathBoundingBox(path);
    extent = CGRectIntersection(CGRectInset(extent, -84, -84), fxRoot.bounds);
    if (CGRectIsNull(extent) || CGRectIsEmpty(extent)) extent = CGRectMake(0, 0, 1, 1);
    const CGPoint middle = CGPointMake(CGRectGetMidX(extent), CGRectGetMidY(extent));
    for (CALayer *layer in @[borderString.group, borderString.glow, borderString.fields, borderString.shape]) {
      layer.bounds = extent; layer.position = middle;
    }
    for (int axis = 0; axis < 2; ++axis) {
      CAGradientLayer *field = axis == 0 ? borderString.horizontal : borderString.vertical;
      field.bounds = CGRectMake(0, 0, extent.size.width, extent.size.height); field.position = middle;
      if (axisGlow[axis] <= 0) continue;
      const CGPoint start = CGPointMake((fieldCenter[axis].x - extent.origin.x) / extent.size.width,
          (fieldCenter[axis].y - extent.origin.y) / extent.size.height);
      field.startPoint = start;
      field.endPoint = CGPointMake(start.x + fieldRadius[axis].width / extent.size.width,
          start.y + fieldRadius[axis].height / extent.size.height);
    }
    borderString.shape.path = path; CGPathRelease(path);
    const int peak = cornerString ? (membranes[0].stress * axisGlow[0] > membranes[1].stress * axisGlow[1] ? 0 : 1) : straightStringAxis;
    const auto& m = membranes[peak];
    double rgb[3]; stressColor(m.stress * std::min(1.0, std::abs(m.bend) / m.pressedBend), rgb);
    borderString.glow.shadowColor = rgba(rgb, 1);
    borderString.glow.shadowRadius = 18 + 18 * m.stress;
    borderString.group.opacity = feedback.edgeGlow;
  } else {
    borderString.shape.path = nil; borderString.group.opacity = 0; borderSamples.clear();
  }
  wasPressing = pressMode;

  // Threads drift with drag, spin, curl and fray as they fade, staying planted in screen space.
  const double threadLife = .85, threadAge = now - breakStart;
  if (!threads.empty() && threadAge > threadLife) threads.clear();
  if (!threads.empty()) {
    const double u = threadAge / threadLife, drag = std::exp(-3.2 * dt);
    CGMutablePathRef path = CGPathCreateMutable();
    for (Thread& thread : threads) {
      thread.vx *= drag; thread.vy *= drag;
      thread.x += thread.vx * dt; thread.y += thread.vy * dt;
      thread.angle += thread.spin * dt; thread.length *= std::exp(-1.1 * dt); thread.curl *= 1 + 1.4 * dt;
      const double px = thread.x - fxOrigin.x, py = thread.y - fxOrigin.y;
      const double ex = px + std::cos(thread.angle) * thread.length, ey = py + std::sin(thread.angle) * thread.length;
      const double wobble = thread.curl * std::sin(thread.phase + 9 * u);
      CGPathMoveToPoint(path, nullptr, px, py);
      CGPathAddQuadCurveToPoint(path, nullptr, (px + ex) / 2 - std::sin(thread.angle) * wobble,
          (py + ey) / 2 + std::cos(thread.angle) * wobble, ex, ey);
    }
    threadShape.path = path; CGPathRelease(path);
    // Breaking releases the tension immediately; its stress color relaxes to white.
    const double stressRemaining = std::pow(1 - std::clamp(threadAge / .12, 0.0, 1.0), 3);
    double threadRGB[3];
    for (int c = 0; c < 3; ++c) threadRGB[c] = 1 + (breakRGB[c] - 1) * stressRemaining;
    threadShape.strokeColor = rgba(threadRGB, 1); threadGlow.shadowColor = rgba(threadRGB, 1);
    threadShape.lineWidth = 3 - 1.5 * u;
    // The glow takes its shape from the stroked threads, not from a full-screen alpha pass.
    CGPathRef outline = CGPathCreateCopyByStrokingPath(threadShape.path, nullptr, threadShape.lineWidth,
        kCGLineCapRound, kCGLineJoinRound, 10);
    threadGlow.shadowPath = outline; CGPathRelease(outline);
    threadGlow.opacity = feedback.edgeGlow * std::pow(1 - u, 1.4);
  } else threadGlow.opacity = 0;
  // The string's occlusion mask only matters while some string or thread is visible.
  const bool stringVisible = (borderString.group.opacity > 0 && (axisGlow[0] > 0 || axisGlow[1] > 0)) ||
      threadGlow.opacity > 0;
  stringRoot.hidden = !stringVisible;
  if (stringVisible) [self updateStringOcclusion];

  // Flight state is captured synchronously by startAnimation, before the first spring step.
  const bool settlingNow = motion->phase == Phase::Settling;
  const bool flying = settlingNow && flightDistance > 40;
  if (flying) flightPeak = std::max(flightPeak, length(motion->velocity));
  const bool finishedSettle = wasSettling && !settlingNow && !dragging;
  const bool landed = finishedSettle && flightDistance > 40;
  wasSettling = settlingNow;

  // The display stays visible at rest; motion adds samples, idle leaves the last curve and zero.
  const pip_motion::Point readVelocity = dragging ? pip_motion::Point{visVX, visVY} : motion->velocity;
  if (length(traceDirection) < .5) traceDirection = {1, 0};
  if (dragging && length(readVelocity) > 5) traceDirection = readVelocity * (1 / length(readVelocity));
  const double signedVelocity = readVelocity.x * traceDirection.x + readVelocity.y * traceDirection.y;
  if (traceSamples.empty()) {
    traceStart = now; tracePeak = 100;
    traceSamples.emplace_back(0, signedVelocity);
  }
  const double elapsed = now - traceStart;
  if (((dragging || settlingNow) && elapsed > traceSamples.back().first + 1.0 / 240) ||
      (!dragging && !settlingNow && traceSamples.back().second != 0))
    traceSamples.emplace_back(elapsed, signedVelocity);
  while (traceSamples.size() > 2 && traceSamples[1].first < elapsed - 1.6)
    traceSamples.erase(traceSamples.begin());
  tracePeak = 100;
  for (const auto& sample : traceSamples) tracePeak = std::max(tracePeak, std::abs(sample.second));
  const double gx = 0, gw = traceBox.bounds.size.width, gy = 3;
  const double gh = std::max(12.0, traceBox.bounds.size.height - 30), zero = gy + gh / 2;
  const double firstTime = traceSamples.front().first;
  // Rebuild the graph only when it is shown and its inputs changed; at rest it is static.
  const bool traceShown = on && feedback.springTrace > 0;
  const bool traceChanged = traceKeyCount != traceSamples.size() || traceKeyTime != traceSamples.back().first ||
      traceKeyValue != traceSamples.back().second || traceKeyFirst != firstTime || traceKeyWidth != gw ||
      traceKeyHeight != traceBox.bounds.size.height || traceKeyDX != traceDirection.x ||
      traceKeyDY != traceDirection.y || traceKeyPeak != tracePeak;
  if (traceShown && (traceChanged || traceSamples.size() == 1)) {
    traceKeyCount = traceSamples.size(); traceKeyTime = traceSamples.back().first;
    traceKeyValue = traceSamples.back().second; traceKeyFirst = firstTime; traceKeyWidth = gw;
    traceKeyHeight = traceBox.bounds.size.height; traceKeyDX = traceDirection.x; traceKeyDY = traceDirection.y;
    traceKeyPeak = tracePeak;
    const double span = std::max(.6, traceSamples.back().first - firstTime);
    CGMutablePathRef graph = CGPathCreateMutable();
    double x = gx, y = zero;
    for (size_t i = 0; i < traceSamples.size(); ++i) {
      x = gx + gw * (traceSamples[i].first - firstTime) / span;
      y = zero + (gh / 2 - 2) * std::asinh(traceSamples[i].second / 50) / std::asinh(tracePeak / 50);
      if (i == 0) CGPathMoveToPoint(graph, nullptr, x, y); else CGPathAddLineToPoint(graph, nullptr, x, y);
    }
    if (traceSamples.size() == 1 && std::abs(signedVelocity) < .5) {
      x = gx + gw; CGPathAddLineToPoint(graph, nullptr, x, zero);
    }
    traceLine.path = graph;
    CGPathRef graphOutline = CGPathCreateCopyByStrokingPath(graph, nullptr, traceLine.lineWidth,
        kCGLineCapRound, kCGLineJoinRound, 10);
    traceLine.shadowPath = graphOutline; CGPathRelease(graphOutline); CGPathRelease(graph);
    CGPathRef dot = CGPathCreateWithEllipseInRect(CGRectMake(x - 2, y - 2, 4, 4), nullptr);
    traceDot.path = dot; CGPathRelease(dot);
    CGMutablePathRef base = CGPathCreateMutable();
    CGPathMoveToPoint(base, nullptr, gx, zero); CGPathAddLineToPoint(base, nullptr, gx + gw, zero);
    traceBase.path = base; CGPathRelease(base);
    const double dx = traceDirection.x, dy = traceDirection.y;
    CGMutablePathRef arrow = CGPathCreateMutable();
    CGPathMoveToPoint(arrow, nullptr, -7 * dx, -7 * dy);
    CGPathAddLineToPoint(arrow, nullptr, 7 * dx, 7 * dy);
    CGPathMoveToPoint(arrow, nullptr, 2 * dx - 4 * dy, 2 * dy + 4 * dx);
    CGPathAddLineToPoint(arrow, nullptr, 7 * dx, 7 * dy);
    CGPathAddLineToPoint(arrow, nullptr, 2 * dx + 4 * dy, 2 * dy - 4 * dx);
    traceArrow.path = arrow; CGPathRelease(arrow);
  }
  NSString *reading = std::abs(signedVelocity) < .5 ? @"0 pt/s" : [NSString stringWithFormat:@"%+.0f pt/s", signedVelocity];
  if (![traceValue.string isEqual:reading]) traceValue.string = reading;
  traceBox.opacity = on ? feedback.springTrace : 0;

  // Stay-here completion has a gentle puff, once, even if the pointer is still held.
  const bool stayLanding = staySettled || (finishedSettle && motion->decision == Decision::Keep && !stayDustDone);
  if (stayLanding) stayDustDone = YES;
  if (on && feedback.dust > 0 && (stayLanding || (landed && flightPeak > 300))) {
    static std::mt19937 dustRng{std::random_device{}()};
    std::uniform_real_distribution<double> unit(0, 1);
    const double hard = stayLanding ? .08 : std::clamp((flightPeak - 300) / 2200, 0.0, 1.0);
    const int count = 12 + int(28 * hard);
    dust.clear();
    for (int i = 0; i < count; ++i) {
      // A random point on the window's perimeter, pushed out along that edge's normal.
      const double t = unit(dustRng) * 2 * (w + h);
      double x, y, nx = 0, ny = 0;
      if (t < w) { x = t; y = 0; ny = -1; }
      else if (t < w + h) { x = w; y = t - w; nx = 1; }
      else if (t < 2 * w + h) { x = t - w - h; y = h; ny = 1; }
      else { x = 0; y = t - 2 * w - h; nx = -1; }
      const double speed = (40 + 180 * hard) * (.4 + .9 * unit(dustRng));
      const double slide = (unit(dustRng) - .5) * speed * .8;
      dust.push_back({position.x + x, position.y + y, nx * speed - ny * slide, ny * speed + nx * slide,
          .8 + 1.8 * unit(dustRng)});
    }
    dustStart = now;
  }
  const double dustAge = now - dustStart, dustLife = .7;
  if (!dust.empty() && dustAge > dustLife) dust.clear();
  if (!dust.empty()) {
    const double u = dustAge / dustLife, drag = std::exp(-4.5 * dt);
    CGMutablePathRef specks = CGPathCreateMutable();
    for (Speck& speck : dust) {
      speck.vx *= drag; speck.vy *= drag; speck.x += speck.vx * dt; speck.y += speck.vy * dt;
      const double r = speck.radius * (1 + .6 * u);
      CGPathAddEllipseInRect(specks, nullptr, CGRectMake(speck.x - fxOrigin.x - r, speck.y - fxOrigin.y - r, 2 * r, 2 * r));
    }
    dustShape.path = specks;
    dustGlow.shadowPath = specks; CGPathRelease(specks);
    dustGlow.opacity = feedback.dust * std::pow(1 - u, 1.3);
  } else dustGlow.opacity = 0;

  // Recording meters: PRESS sits above the card (below near the top), SETTLE below (above near the bottom).
  const double hudGrow = (cardScale - 1) / 2, hudX = std::round(kPad + leanX + w / 2);
  const double cardTop = kPad + leanY + h * (1 + hudGrow), cardBottom = kPad + leanY - h * hudGrow;
  const bool nearTop = area.y + area.height - (position.y + h) < 72, nearBottom = position.y - area.y < 72;
  approach(pressHudAlpha, pressMode ? 1 : 0, .06, .25, dt);
  if (pressMode) {
    const pip_motion::Point p = motion->pressed;
    const bool sidePress = std::abs(p.x) >= std::abs(p.y);
    const double dock = motion->settings.press_dock, tuck = motion->settings.press_tuck;
    const double depthShown = sidePress ? std::abs(depthNow.x) : std::abs(depthNow.y);
    const double range = sidePress ? std::max(tuck, dock) * 1.15 : dock * 3;
    pressHudFill = std::clamp(depthShown / range, 0.0, 1.0);
    NSString *value = [NSString stringWithFormat:@"%.1f%%", depthShown];
    if (![pressValue.string isEqual:value]) pressValue.string = value;
    auto placeTick = [&](CALayer *mark, CATextLayer *caption, double at) {
      const double x = std::round(kTrackX + kTrackW * std::min(1.0, at / range));
      mark.position = CGPointMake(x, kTrackY + 2); caption.position = CGPointMake(x, kTrackY + 15);
    };
    placeTick(pressDockTick, pressDockLabel, dock);
    placeTick(pressTuckTick, pressTuckLabel, tuck);
    pressTuckTick.hidden = pressTuckLabel.hidden = !sidePress;
  }
  pressFill.bounds = CGRectMake(0, 0, kTrackW * pressHudFill, 4);
  pressHud.position = CGPointMake(hudX, std::round(nearTop ? cardBottom - 18 - kHudH / 2 : cardTop + 18 + kHudH / 2));
  pressHud.opacity = pressHudAlpha * feedback.meters;

  approach(settleHudAlpha, meterTarget, .08, .3, dt);
  if (dragging) settleHudDone = settleTapped;
  settleFill.bounds = CGRectMake(0, 0, kTrackW * meterProgress, 4);
  NSString *settleText = settleHudDone ? @"SET" : [NSString stringWithFormat:@"%.0f%%", meterProgress * 100];
  if (![settleValue.string isEqual:settleText]) settleValue.string = settleText;
  settleHud.position = CGPointMake(hudX, std::round(nearBottom ? cardTop + 18 + kHudH / 2 : cardBottom - 18 - kHudH / 2));
  const double pop = rippling ? .06 * std::sin(M_PI * rippleAge / rippleTime) : 0;
  settleHud.transform = CATransform3DMakeScale(1 + pop, 1 + pop, 1);
  settleHud.opacity = settleHudAlpha * feedback.meters;

  // Screen edge in card coordinates, accounting for lean and the lift scale about the card's center.
  const double rimScreen = side == Side::Left ? fxOrigin.x : fxOrigin.x + fxRoot.bounds.size.width;
  const double rim = w / 2 + (rimScreen - (position.x + leanX + w / 2)) / cardScale;
  const double reach = std::max(88.0, handle * 3);
  const double bleed = 2 / (std::max(1.0, panel.backingScaleFactor) * cardScale);
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
  // Overscan the screenward edge by two backing pixels; keep peak darkness at the rim.
  // A layer ending at the rim can leave the final physical pixel only partially covered.
  rimShade.frame = side == Side::Left ? CGRectMake(rim - bleed, -bleed, reach + bleed, h + 2 * bleed) :
      CGRectMake(rim - reach, -bleed, reach + bleed, h + 2 * bleed);
  rimShade.startPoint = CGPointMake(side == Side::Left ? bleed / (reach + bleed) : reach / (reach + bleed), .5);
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
  chevron.position = CGPointMake(chevronX, h / 2);
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

  // The settings window's readout refreshes about ten times a second while the card moves.
  if (dragging && statusFresh) {
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
      shadowX == shadowTarget.x && shadowY == shadowTarget.y && !landing && !rippling &&
      meterAlpha == meterTarget && visVX == 0 && visVY == 0 && tiltX == 0 && tiltY == 0 &&
      pressHudAlpha == (pressMode ? 1 : 0) && settleHudAlpha == meterTarget && threads.empty() &&
      axisGlow[0] == (axisPressed[0] ? 1 : 0) && axisGlow[1] == (axisPressed[1] ? 1 : 0) &&
      (axisPressed[0] || (membranes[0].bend == 0 && membranes[0].bendVelocity == 0)) &&
      (axisPressed[1] || (membranes[1].bend == 0 && membranes[1].bendVelocity == 0)) &&
      dust.empty();
}
- (void)startAnimation {
  if (returnedToBrowser) { [self showPosition]; return; }
  if (motion->phase == Phase::Settling) {
    const double now = NSProcessInfo.processInfo.systemUptime;
    flightDistance = length(motion->target - motion->position);
    flightPeak = length(motion->velocity);
    traceSamples.clear(); traceStart = now; tracePeak = std::max(100.0, flightPeak);
    if (flightPeak > 1) traceDirection = motion->velocity * (1 / flightPeak);
    else if (flightDistance > 1) traceDirection = (motion->target - motion->position) * (1 / flightDistance);
    traceSamples.emplace_back(0, flightPeak);
    wasSettling = YES;
  }
  [self showPosition];
  if (motion->phase != Phase::Settling || animating) return;
  // The spring is stepped by the display frame; see renderAt:.
  animating = YES;
  lastTick = CACurrentMediaTime();
  [self startFrames];
}
- (void)stopAnimation { animating = NO; }
- (void)updateStringOcclusion {
  // Glass remains translucent to the desktop, but the string is fully occluded by the card.
  CGMutablePathRef mask = CGPathCreateMutable();
  CGPathAddRect(mask, nullptr, fxRoot.bounds);
  const double bleed = 1 / std::max(1.0, panel.backingScaleFactor);
  const CGRect card = CGRectInset(stage.bounds, -bleed, -bleed);
  const double radius = kCardRadius + bleed;
  const CGPoint centers[] = {{CGRectGetMinX(card) + radius, CGRectGetMinY(card) + radius},
      {CGRectGetMaxX(card) - radius, CGRectGetMinY(card) + radius},
      {CGRectGetMaxX(card) - radius, CGRectGetMaxY(card) - radius},
      {CGRectGetMinX(card) + radius, CGRectGetMaxY(card) - radius}};
  for (int corner = 0; corner < 4; ++corner) for (int i = 0; i <= 8; ++i) {
    const double angle = M_PI + corner * M_PI / 2 + i * M_PI / 16;
    const CGPoint local = CGPointMake(centers[corner].x + radius * std::cos(angle),
        centers[corner].y + radius * std::sin(angle));
    const CGPoint inPanel = [stage convertPoint:local toLayer:panel.contentView.layer];
    const CGPoint point = CGPointMake(inPanel.x + panel.frame.origin.x - fxOrigin.x,
        inPanel.y + panel.frame.origin.y - fxOrigin.y);
    if (corner == 0 && i == 0) CGPathMoveToPoint(mask, nullptr, point.x, point.y);
    else CGPathAddLineToPoint(mask, nullptr, point.x, point.y);
  }
  CGPathCloseSubpath(mask);
  stringOcclusion.path = mask; CGPathRelease(mask);
}
- (void)cancelReturnAnimation {
  [controls.contentView.layer removeAnimationForKey:@"homeReturn"];
  if (!returnTimer) return;
  [returnTimer invalidate]; returnTimer = nil;
  [CATransaction begin]; [CATransaction setDisableActions:YES];
  panel.alphaValue = 1; [panel setFrame:returnFrame display:NO]; stage.transform = returnTransform;
  [CATransaction commit];
}
- (void)landAtHome {
  if (NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion) return;
  controls.contentView.wantsLayer = YES;
  CAKeyframeAnimation *dip = [CAKeyframeAnimation animationWithKeyPath:@"transform.translation.y"];
  dip.values = @[@0, @-3, @.5, @0]; dip.additive = YES;
  CAKeyframeAnimation *compression = [CAKeyframeAnimation animationWithKeyPath:@"transform.scale.y"];
  compression.values = @[@1, @.994, @1.002, @1];
  NSArray *times = @[@0, @.22, @.55, @1];
  NSArray *easing = @[[CAMediaTimingFunction functionWithName:kCAMediaTimingFunctionEaseOut],
      [CAMediaTimingFunction functionWithName:kCAMediaTimingFunctionEaseOut],
      [CAMediaTimingFunction functionWithName:kCAMediaTimingFunctionEaseInEaseOut]];
  for (CAKeyframeAnimation *animation in @[dip, compression]) {
    animation.keyTimes = times; animation.timingFunctions = easing; animation.duration = .32;
  }
  CAAnimationGroup *landing = [CAAnimationGroup animation];
  landing.animations = @[dip, compression]; landing.duration = .32;
  [controls.contentView.layer addAnimation:landing forKey:@"homeReturn"];
}
- (void)returnTick:(NSTimer *)timer {
  const double u = std::clamp((NSProcessInfo.processInfo.systemUptime - returnStart) / .22, 0.0, 1.0);
  const double ease = 1 - std::pow(1 - u, 3);
  [CATransaction begin]; [CATransaction setDisableActions:YES];
  [panel setFrameOrigin:NSMakePoint(returnFrame.origin.x + returnDelta.x * ease,
      returnFrame.origin.y + returnDelta.y * ease)];
  panel.alphaValue = 1 - ease;
  stage.transform = CATransform3DScale(returnTransform, 1 - .16 * ease, 1 - .16 * ease, 1);
  [CATransaction commit];
  if (u >= 1) {
    [panel orderOut:nil]; [self cancelReturnAnimation]; [self landAtHome];
  }
}
- (void)returnToBrowser {
  if (returnedToBrowser) return;
  returnedToBrowser = YES; awaitingLanding = NO; consumeTrackpadMomentum = NO; pendingTrackpadPan = NO;
  [self stopAnimation]; [self stopFrames];
  [fxPanel orderOut:nil];
  const BOOL animate = panel.visible && !NSWorkspace.sharedWorkspace.accessibilityDisplayShouldReduceMotion;
  if (animate) {
    returnFrame = panel.frame; returnTransform = stage.transform;
    const pip_motion::Point toward{NSMidX(controls.frame) - NSMidX(panel.frame), NSMidY(controls.frame) - NSMidY(panel.frame)};
    returnDelta = toward * (std::min(80.0, length(toward)) / std::max(1.0, length(toward)));
    returnStart = NSProcessInfo.processInfo.systemUptime;
    returnTimer = [NSTimer timerWithTimeInterval:1.0/120 target:self selector:@selector(returnTick:) userInfo:nil repeats:YES];
    [NSRunLoop.mainRunLoop addTimer:returnTimer forMode:NSRunLoopCommonModes];
  } else [panel orderOut:nil];
  motion->reset(); [self showPosition];
}
- (void)layoutCardContent {
  const CGFloat w = motion->size.width, h = motion->size.height;
  const BOOL compact = h < 150;
  glassSurface.frame = cardContent.frame = NSMakeRect(0, 0, w, h);
  glassTint.frame = glassEdge.frame = glassOutline.frame = CGRectMake(0, 0, w, h);
  CGPathRef edge = CGPathCreateWithRoundedRect(CGRectInset(glassEdge.bounds, .5, .5),
      kCardRadius - .5, kCardRadius - .5, nullptr);
  glassOutline.path = edge; CGPathRelease(edge);
  cueText.hidden = compact;
  intentText.frame = CGRectMake(compact ? 16 : 20, h - 32, w - (compact ? 32 : 40), 16);
  cueText.frame = CGRectMake(20, 12, w - 40, 14);
  traceBox.frame = CGRectMake(compact ? 16 : 20, compact ? 10 : 36,
      w - (compact ? 32 : 40), std::max(38.0, h - (compact ? 52 : 78)));
  const CGFloat tw = traceBox.bounds.size.width, th = traceBox.bounds.size.height;
  traceTitle.hidden = tw < 180;
  traceTitle.frame = CGRectMake(0, th - 18, 76, 14);
  traceArrow.position = CGPointMake(traceTitle.hidden ? 8 : 86, th - 12);
  const CGFloat valueX = traceTitle.hidden ? 26 : 106;
  traceValue.frame = CGRectMake(valueX, th - 20, tw - valueX, 17);
  traceBase.frame = traceLine.frame = traceDot.frame = traceBox.bounds;
}
- (void)showPosition {
  if (returnedToBrowser) {
    status.stringValue = @"Returned to browser · Reset position to bring card back";
    explanation.stringValue = @"Lab simulation · no browser opened";
    [self writeState];
    return;
  }
  const CGFloat w = motion->size.width, h = motion->size.height;
  // A resize lays out synchronously; a move waits for the next display frame, where the window
  // and its effects are placed together. See renderAt:.
  if (stage.bounds.size.width != w || stage.bounds.size.height != h) {
    [self placeWindow];
    [CATransaction begin]; [CATransaction setDisableActions:YES];
    cardHost.frame = NSMakeRect(kPad, kPad, w, h);
    CGPathRef shape = CGPathCreateWithRoundedRect(stage.bounds, kCardRadius, kCardRadius, nullptr);
    for (CALayer *shadow in @[ambientShadow, contactShadow, glowShadow]) {
      shadow.frame = stage.bounds; shadow.shadowPath = shape;
    }
    CGPathRelease(shape);
    overlay.frame = windowShade.frame = stage.bounds;
    [self layoutCardContent];
    CGPathRef outline = CGPathCreateWithRoundedRect(CGRectInset(stage.bounds, 1, 1), kCardRadius - 1, kCardRadius - 1, nullptr);
    for (CAShapeLayer *line in @[rimLight, meter, ripple]) {
      line.frame = stage.bounds; line.path = outline;
    }
    CGPathRelease(outline);
    example.frame = NSMakeRect(kPad, kPad, w, h);
    const CGRect bounds = panel.contentView.bounds;
    cardHost.superview.frame = NSRectFromCGRect(bounds);
    [CATransaction commit];
  }
  [self updateStatus:NO];
  [self requestFrame];
  // The state file is an observable checkpoint, not a frame-by-frame trace; a pinch writes it once it ends.
  if (motion->phase != Phase::Settling && motion->phase != Phase::Dragging &&
      gestures->kind() != pip_motion::Gestures::Kind::Pinch) [self writeState];
}
// Settings-window readout. While the card moves it refreshes about ten times a second.
- (void)updateStatus:(BOOL)force {
  statusFresh = NO;
  const bool inMotion = motion->phase == Phase::Dragging || motion->phase == Phase::Settling;
  const double now = CACurrentMediaTime();
  if (!force && inMotion && now - lastStatusUpdate < .1) return;
  lastStatusUpdate = now; statusFresh = YES;
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
    @"returned_to_browser":@(returnedToBrowser),
    @"pinch_events":@(pinchEvents), @"last_pinch_route":lastPinchRoute ?: @"none",
    @"last_pinch_delta":@(lastPinchDelta), @"card_is_key":@(panel.isKeyWindow),
    @"phase":phaseName(motion->phase), @"x":@(motion->position.x), @"y":@(motion->position.y),
    @"target_x":@(motion->target.x), @"target_y":@(motion->target.y),
    @"tucked":@(motion->tucked != Side::None), @"settings":[self settingsDictionary],
    @"native_frame":@[@(NSMinX(cardFrame)), @(NSMinY(cardFrame)), @(NSWidth(cardFrame)), @(NSHeight(cardFrame))],
    @"gesture":@(gestures->kind() == pip_motion::Gestures::Kind::Pan ? "pan" :
                 gestures->kind() == pip_motion::Gestures::Kind::Pinch ? "pinch" : "none"),
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
  [self cancelReturnAnimation];
  if (gestureMonitor) [NSEvent removeMonitor:gestureMonitor];
  [self stopAnimation]; [self stopFrames]; [fileTimer invalidate]; [saveTimer invalidate];
  if (@available(macOS 14.0, *)) [(CADisplayLink *)frameLink invalidate];
  frameLink = nil;
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

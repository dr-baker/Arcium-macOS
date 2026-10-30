// App-local dispatch checks, not synthesized hardware input.
#define main opusLabMain
#include "main.mm"
#undef main
#import <objc/runtime.h>

// The user can keep using the real lab. These replacements affect only this
// test process and prevent its fixture windows from ever appearing or activating.
static void suppressFixtureWindows() {
  method_setImplementation(class_getInstanceMethod(NSWindow.class, @selector(orderFrontRegardless)),
      imp_implementationWithBlock(^(id window) {}));
  method_setImplementation(class_getInstanceMethod(NSWindow.class, @selector(makeKeyAndOrderFront:)),
      imp_implementationWithBlock(^(id window, id sender) {}));
  method_setImplementation(class_getInstanceMethod(NSWindow.class, @selector(orderWindow:relativeTo:)),
      imp_implementationWithBlock(^(id window, NSWindowOrderingMode mode, NSInteger other) {}));
  method_setImplementation(class_getInstanceMethod(NSApplication.class, @selector(activateIgnoringOtherApps:)),
      imp_implementationWithBlock(^(id app, BOOL flag) {}));
}

@interface LabGestureEvent : NSEvent
@property(nonatomic) NSEventType gestureType;
@property(nonatomic) NSEventPhase gesturePhase;
@property(nonatomic) NSEventPhase gestureMomentum;
@property(nonatomic) NSWindow *gestureWindow;
@property(nonatomic) NSPoint gestureLocation;
@property(nonatomic) CGFloat gestureX, gestureY, gestureMagnification;
@property(nonatomic) NSTimeInterval gestureTime;
@end
@implementation LabGestureEvent
- (NSEventType)type { return self.gestureType; }
- (NSEventPhase)phase { return self.gesturePhase; }
- (NSEventPhase)momentumPhase { return self.gestureMomentum; }
- (NSWindow *)window { return self.gestureWindow; }
- (NSInteger)windowNumber { return self.gestureWindow.windowNumber; }
- (NSPoint)locationInWindow { return self.gestureLocation; }
- (BOOL)hasPreciseScrollingDeltas { return YES; }
- (CGFloat)scrollingDeltaX { return self.gestureX; }
- (CGFloat)scrollingDeltaY { return self.gestureY; }
- (CGFloat)magnification { return self.gestureMagnification; }
- (NSTimeInterval)timestamp { return self.gestureTime; }
@end

static int nativeChecks;
static void nativeCheck(BOOL value, const char *name) {
  ++nativeChecks;
  if (!value) { fprintf(stderr, "FAIL native: %s\n", name); exit(1); }
}

int main() {
  @autoreleasepool {
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
    suppressFixtureWindows();
    NSString *folder = [NSTemporaryDirectory() stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
    [NSFileManager.defaultManager createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:nil error:nil];
    MotionLab *lab = [[MotionLab alloc] initWithSettingsPath:[folder stringByAppendingPathComponent:@"settings.json"]];
    [lab applicationDidFinishLaunching:[NSNotification notificationWithName:
        NSApplicationDidFinishLaunchingNotification object:NSApp]];
    for (NSWindow *window in NSApp.windows)
      nativeCheck(!window.visible, "fixture cannot display windows over the live lab");
    for (NSWindow *window in NSApp.windows) [window orderOut:nil];
    NSWindow *panel = [lab valueForKey:@"panel"];
    NSWindow *controls = [lab valueForKey:@"controls"];
    auto state = [&]() -> NSDictionary * {
      [lab writeState];
      return [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:
          [folder stringByAppendingPathComponent:@"state.json"]] options:0 error:nil];
    };
    auto send = [&](NSEventType type, NSEventPhase phase, double dx, double dy, double magnification) {
      NSDictionary *before = state();
      const double x = [before[@"x"] doubleValue], y = [before[@"y"] doubleValue];
      NSArray *frame = before[@"native_frame"];
      NSPoint global = NSMakePoint(x + [frame[2] doubleValue] / 2, y + [frame[3] doubleValue] / 2);
      LabGestureEvent *event = [LabGestureEvent new];
      event.gestureType = type; event.gesturePhase = phase;
      // Target the key settings window, not the card's view. This checks the
      // application monitor route that a responder-only pinch handler misses.
      event.gestureWindow = controls;
      event.gestureLocation = [controls convertPointFromScreen:global];
      event.gestureX = dx; event.gestureY = dy; event.gestureMagnification = magnification;
      event.gestureTime = NSProcessInfo.processInfo.systemUptime;
      [NSApp sendEvent:event];
    };
    NSDictionary *before = state();
    const double width = [before[@"native_frame"][2] doubleValue];
    send(NSEventTypeMagnify, NSEventPhaseBegan, 0, 0, 0);
    send(NSEventTypeMagnify, NSEventPhaseChanged, 0, 0, .25);
    NSDictionary *after = state();
    nativeCheck([after[@"native_frame"][2] doubleValue] > width + 1,
                "magnification reaches PiP through application event dispatch");
    NSView *target = [lab valueForKey:@"example"];
    CALayer *stage = [lab valueForKey:@"stage"];
    nativeCheck(std::abs(NSWidth(target.frame) - [after[@"native_frame"][2] doubleValue]) < .01 &&
                std::abs(stage.bounds.size.width - NSWidth(target.frame)) < .01,
                "resizing updates artwork and hit region together");
    send(NSEventTypeMagnify, NSEventPhaseCancelled, 0, 0, 0);
    nativeCheck(std::abs([state()[@"native_frame"][2] doubleValue] - width) < .01,
                "native cancellation restores the original size");
    send(NSEventTypeMagnify, NSEventPhaseBegan, 0, 0, 0);
    send(NSEventTypeMagnify, NSEventPhaseChanged, 0, 0, -.10);
    const double smallerWidth = [state()[@"native_frame"][2] doubleValue];
    nativeCheck(smallerWidth < width - 1,
                "negative native magnification shrinks the card");
    send(NSEventTypeMagnify, NSEventPhaseChanged, 0, 0, .20);
    nativeCheck([state()[@"native_frame"][2] doubleValue] > smallerWidth + 1,
                "positive native magnification grows the card after shrinking");
    send(NSEventTypeMagnify, NSEventPhaseCancelled, 0, 0, 0);
    // Move away from screen resistance before testing diagonal finger motion.
    [lab reset:nil];
    send(NSEventTypeScrollWheel, NSEventPhaseBegan, 0, 0, 0);
    NSDictionary *panStart = state();
    send(NSEventTypeScrollWheel, NSEventPhaseChanged, -50, -40, 0);
    NSDictionary *panMoved = state();
    nativeCheck([panMoved[@"x"] doubleValue] < [panStart[@"x"] doubleValue] - 1 &&
                [panMoved[@"y"] doubleValue] > [panStart[@"y"] doubleValue] + 1,
                "negative native deltas move left and up in screen coordinates");
    send(NSEventTypeScrollWheel, NSEventPhaseChanged, 10, 10, 0);
    NSDictionary *panReversed = state();
    nativeCheck([panReversed[@"x"] doubleValue] > [panMoved[@"x"] doubleValue] + 1 &&
                [panReversed[@"y"] doubleValue] < [panMoved[@"y"] doubleValue] - 1,
                "positive native deltas move right and down without changing horizontal polarity");
    send(NSEventTypeScrollWheel, NSEventPhaseCancelled, 0, 0, 0);
    [lab stopAnimation];
    auto wheelAt = [&](BOOL overCard, NSEventPhase phase, NSEventPhase momentum) {
      NSDictionary *snapshot = state();
      LabGestureEvent *event = [LabGestureEvent new];
      event.gestureType = NSEventTypeScrollWheel;
      event.gesturePhase = phase; event.gestureMomentum = momentum;
      event.gestureWindow = controls;
      NSPoint global = overCard ? NSMakePoint([snapshot[@"x"] doubleValue] + 40,
          [snapshot[@"y"] doubleValue] + 40) : NSMakePoint(NSMinX(controls.frame) + 10, NSMaxY(controls.frame) - 10);
      event.gestureLocation = [controls convertPointFromScreen:global];
      event.gestureTime = NSProcessInfo.processInfo.systemUptime;
      return event;
    };
    [lab consumeGesture:wheelAt(YES, NSEventPhaseBegan, NSEventPhaseNone)];
    [lab consumeGesture:wheelAt(YES, NSEventPhaseEnded, NSEventPhaseNone)];
    nativeCheck([lab consumeGesture:wheelAt(YES, NSEventPhaseNone, NSEventPhaseBegan)],
                "captured card pan consumes its own following inertia");
    [lab consumeGesture:wheelAt(NO, NSEventPhaseBegan, NSEventPhaseNone)];
    nativeCheck(![lab consumeGesture:wheelAt(NO, NSEventPhaseNone, NSEventPhaseBegan)],
                "new settings scroll keeps its own inertia after a card pan");
    [lab stopAnimation];

    NSDictionary *beforeReturn = state();
    NSArray *frame = beforeReturn[@"native_frame"];
    const NSPoint local = NSMakePoint(kPad + [frame[2] doubleValue] / 2,
                                      kPad + [frame[3] doubleValue] / 2);
    NSView *hit = [panel.contentView hitTest:local];
    nativeCheck(hit == target, "glass leaves the card's mouse event target exposed");
    NSEvent *doubleClick = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDown
        location:local modifierFlags:0 timestamp:NSProcessInfo.processInfo.systemUptime
        windowNumber:panel.windowNumber context:nil eventNumber:1 clickCount:2 pressure:1];
    [hit mouseDown:doubleClick];
    NSDictionary *returned = state();
    nativeCheck([returned[@"returned_to_browser"] boolValue] &&
                [returned[@"native_frame"][2] doubleValue] == [frame[2] doubleValue],
                "double click requests return without changing PiP size");
    [lab reset:nil];
    NSDictionary *restored = state();
    nativeCheck(![restored[@"returned_to_browser"] boolValue] &&
                [restored[@"settings"] isEqual:beforeReturn[@"settings"]],
                "lab reset restores the card without changing tuning");
    [lab applicationWillTerminate:[NSNotification notificationWithName:
        NSApplicationWillTerminateNotification object:NSApp]];
    for (NSWindow *window in NSApp.windows) [window orderOut:nil];
    nativeCheck(panel != nil, "test used a real AppKit panel");
    printf("PASS: %d native gesture checks\n", nativeChecks);
  }
}

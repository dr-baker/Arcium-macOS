// Included by Verify.mm: production callbacks with all ordering/activation intercepted.
@interface LifecycleApp : NSObject
@property pid_t processIdentifier;
@end
static int appRestorations=0;
@implementation LifecycleApp
- (BOOL)isTerminated { return NO; }
- (BOOL)activateWithOptions:(NSApplicationActivationOptions)options { ++appRestorations; return YES; }
@end
static LifecycleApp* lifecycleFront;
static id LifecycleFront(id,SEL) { return lifecycleFront; }
static void NoLifecycleOrder(id,SEL,NSWindowOrderingMode,NSInteger) {}
@interface LifecyclePanel : NSPanel
@property BOOL admitted;
@property BOOL syntheticKey;
@property(copy) void (^frameHook)(void);
@end
@implementation LifecyclePanel
- (BOOL)isVisible { return self.admitted; }
- (BOOL)isKeyWindow { return self.syntheticKey; }
- (BOOL)canBecomeKeyWindow { return YES; }
- (void)makeKeyWindow { self.syntheticKey=YES; }
- (void)resignKeyWindow {
  self.syntheticKey=NO;
  [NSNotificationCenter.defaultCenter postNotificationName:NSWindowDidResignKeyNotification object:self];
}
- (void)setFrame:(NSRect)rect display:(BOOL)display {
  [super setFrame:rect display:display];
  if (_frameHook) { auto callback=_frameHook; _frameHook=nil; callback(); }
}
- (void)setFrameOrigin:(NSPoint)point {
  [super setFrameOrigin:point];
  if (_frameHook) { auto callback=_frameHook; _frameHook=nil; callback(); }
}
- (void)orderOut:(id)sender {}
- (void)orderFront:(id)sender { std::abort(); }
- (void)makeKeyAndOrderFront:(id)sender { std::abort(); }
@end
static LifecyclePanel* LifecycleWindow(NSRect frame) {
  auto* window=[[LifecyclePanel alloc] initWithContentRect:frame styleMask:NSWindowStyleMaskBorderless|NSWindowStyleMaskNonactivatingPanel backing:NSBackingStoreBuffered defer:NO];
  window.releasedWhenClosed=NO;
  return window;
}
static void CheckLifecycle() {
  const IMP oldFront=method_setImplementation(class_getInstanceMethod(NSWorkspace.class,@selector(frontmostApplication)),(IMP)LifecycleFront);
  const IMP oldOrder=method_setImplementation(class_getInstanceMethod(NSWindow.class,@selector(orderWindow:relativeTo:)),(IMP)NoLifecycleOrder);
  lifecycleFront=[LifecycleApp new]; lifecycleFront.processIdentifier=getpid();
  @autoreleasepool {
    using namespace arcium::pip;
    LifecyclePanel* panel=LifecycleWindow(NSMakeRect(300,300,640,360)); panel.admitted=YES;
    int returns=0;
    NativeControls controls(panel,[&](Action action,double){if(action==Action::kReturn)++returns;});
    auto* view=(ArciumPiPNativeOverlay*)controls.GetNativeView().Get(); [panel.contentView addSubview:view];
    State state;state.can_play=state.can_seek=true;state.duration=600;controls.Update(state);
    LifecycleApp* previous=[LifecycleApp new];previous.processIdentifier=getpid()+100000;
    [view performSelector:@selector(mouseEntered:) withObject:nil];[view setValue:previous forKey:@"previousApplication"];
    [view applyPinch:.1 ended:NO cancelled:NO];[view flushResizeFrame];[view performSelector:@selector(mouseExited:) withObject:nil];
    Check(panel.keyWindow,"pointer exit defers focus restoration until pinch terminates");
    [view performSelector:@selector(touchesCancelledWithEvent:) withObject:nil];
    Check(![[view valueForKey:@"magnifying"] boolValue] && !panel.keyWindow,"touch cancellation outside releases resize and borrowed key focus");
    Check(appRestorations==1 && [view valueForKey:@"previousApplication"]==nil,"touch cancellation restores prior app exactly once through resign reentry");
    [view performSelector:@selector(touchesCancelledWithEvent:) withObject:nil];Check(appRestorations==1,"repeated touch cancellation cannot restore an app twice");
    [view performSelector:@selector(mouseEntered:) withObject:nil];[view setValue:previous forKey:@"previousApplication"];
    [view applyPinch:.1 ended:NO cancelled:NO];[panel resignKeyWindow];
    Check(![[view valueForKey:@"magnifying"] boolValue] && appRestorations==1,"user-driven focus loss cancels without reactivating prior app");
    auto* recognizer=[TestPinchRecognizer new];recognizer.testState=NSGestureRecognizerStateChanged;recognizer.magnification=.1;
    const NSRect interrupted=panel.frame;
    [view recognizePinch:recognizer];[view flushResizeFrame];
    Check(![[view valueForKey:@"magnifying"] boolValue] && NSEqualRects(interrupted,panel.frame),"late recognizer Changed cannot restart interrupted stream");
    auto* raw=[HoverMagnifyEvent new];raw.targetWindow=panel;raw.targetPoint=NSMakePoint(200,100);raw.eventPhase=NSEventPhaseChanged;raw.delta=.1;
    Check(![view consumeMagnify:raw],"late raw Changed is rejected after interruption");
    [view performSelector:@selector(mouseEntered:) withObject:nil];recognizer.testState=NSGestureRecognizerStateBegan;recognizer.magnification=0;[view recognizePinch:recognizer];
    recognizer.testState=NSGestureRecognizerStateChanged;recognizer.magnification=.1;[view recognizePinch:recognizer];[view flushResizeFrame];
    Check([[view valueForKey:@"magnifying"] boolValue] && NSWidth(panel.frame)>NSWidth(interrupted),"fresh native Began allows resize after focus loss");
    [view cancelGestureInput];
    controls.FocusControls(false);[view setValue:previous forKey:@"previousApplication"];
    const int beforeHide=appRestorations;controls.RestorePlacementForHide();
    Check(![view keepsKeyboardControlsVisible] && [view valueForKey:@"previousApplication"]==nil,"common hide releases keyboard focus and previous-app token");
    Check(appRestorations==beforeHide+1,"keyboard hide restores borrowed application once");
    panel.admitted=NO;
    Placement placement;placement.width=640;controls.PreparePlacement(placement,nil,16./9.,{});panel.admitted=YES;
    auto* home=LifecycleWindow(NSMakeRect(100,100,900,600));home.admitted=YES;[view setValue:home forKey:@"openerWindow"];
    state.effects[static_cast<size_t>(Effect::kReturn)]=true;controls.Update(state);
    if(!ReduceMotion()) {
      const NSRect original=panel.frame;[view returnToTab:nil];
      NSTimer* timer=[view valueForKey:@"returnTimer"];Check(timer!=nil,"return animation starts for visible opener");
      [view setValue:@(NSProcessInfo.processInfo.systemUptime-1) forKey:@"returnStart"];[timer fire];
      Check(panel.alphaValue==0 && !NSEqualRects(panel.frame,original) && returns==0,"completed Return stays invisible while action awaits dispatch");
      controls.RestorePlacementForHide();
      Check(panel.alphaValue==0,"hide does not flash completed Return back to full opacity");
      panel.admitted=NO;controls.PreparePlacement(placement,nil,16./9.,{});
      Check(panel.alphaValue==1 && ![[view valueForKey:@"hiding"] boolValue],"explicit next placement restores reusable opacity");
      panel.admitted=YES;[view setValue:home forKey:@"openerWindow"];
      const NSRect cancelStart=panel.frame;[view returnToTab:nil];
      timer=[view valueForKey:@"returnTimer"];[view setValue:@(NSProcessInfo.processInfo.systemUptime-.1) forKey:@"returnStart"];[timer fire];[view cancelReturn:YES];
      Check(panel.alphaValue==1 && NSEqualRects(panel.frame,cancelStart),"explicit Return cancellation immediately restores frame and opacity");
    }
    LifecyclePanel* reentrant=LifecycleWindow(NSMakeRect(-20000,-20000,640,360));
    NativeControls other(reentrant,[](Action,double){});
    auto* otherView=(ArciumPiPNativeOverlay*)other.GetNativeView().Get();[reentrant.contentView addSubview:otherView];
    State effects;effects.effects[static_cast<size_t>(Effect::kShadows)]=true;effects.show_controls=effects.playing=effects.can_seek=true;effects.duration=600;
    other.Update(effects);reentrant.admitted=YES;
    __block BOOL refreshed=NO, invisibleDuringRefresh=NO;
    reentrant.frameHook=^{refreshed=YES;invisibleDuringRefresh=reentrant.alphaValue==0;[otherView applyState:effects];};
    other.RestorePlacementForHide();
    Check(refreshed,"hide fixture injects actual synchronous host state refresh during final fit");
    Check(invisibleDuringRefresh && reentrant.alphaValue==0,"card is transparent before teardown changes geometry or refreshes presentation");
    Check([otherView valueForKey:@"shadowWindow"]==nil && [otherView valueForKey:@"shadeView"]==nil && reentrant.childWindows.count==0,"reentrant refresh cannot recreate hidden effects or child windows");
    Check(!((NSTimer*)[otherView valueForKey:@"hideTimer"]).valid && !((NSTimer*)[otherView valueForKey:@"progressTimer"]).valid,"reentrant hide cannot restart chrome timers");
    Check(![otherView ensureMotion],"motion creation stays fenced after hide");
    [otherView performSelector:@selector(mouseEntered:) withObject:nil];Check(!reentrant.keyWindow && ![[otherView valueForKey:@"mouseInside"] boolValue],"hidden-session tracking callbacks cannot take focus or rearm hover");
    other.Update(effects);Check([otherView valueForKey:@"shadowWindow"]==nil,"later hidden host refresh stays fenced");
    reentrant.admitted=NO;other.PreparePlacement(placement,nil,16./9.,{});
    Check(![[otherView valueForKey:@"hiding"] boolValue],"placement begins a new native presentation session");
    __block BOOL drained=NO;dispatch_async(dispatch_get_main_queue(),^{drained=YES;});
    for(int i=0;i<50&&!drained;++i)CFRunLoopRunInMode(kCFRunLoopDefaultMode,.01,false);
    Check(drained && returns==0,"hide invalidates queued completed Return from prior session");
    panel.admitted=home.admitted=NO;
  }
  method_setImplementation(class_getInstanceMethod(NSWorkspace.class,@selector(frontmostApplication)),oldFront);
  method_setImplementation(class_getInstanceMethod(NSWindow.class,@selector(orderWindow:relativeTo:)),oldOrder);
}

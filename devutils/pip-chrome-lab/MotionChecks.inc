// Native frame callbacks may synchronously hide, reopen or replace the model.
static void CheckMotionBoundaries() {
  using namespace arcium::pip;
  const IMP oldOrder=method_setImplementation(class_getInstanceMethod(NSWindow.class,@selector(orderWindow:relativeTo:)),(IMP)NoLifecycleOrder);
  for (int path=0;path<5;++path) for (bool effects : {false,true}) for (int replacement=0;replacement<4;++replacement) {
    if(path==4 && !effects) continue;
    @autoreleasepool {
      auto* panel=LifecycleWindow(NSMakeRect(300,300,640,360));panel.admitted=YES;
      NativeControls controls(panel,[](Action,double){});
      auto* view=(ArciumPiPNativeOverlay*)controls.GetNativeView().Get();[panel.contentView addSubview:view];
      State state;state.effects.fill(effects);controls.Update(state);
      auto* pan=[PanTestEvent new];pan.targetWindow=panel;pan.targetPoint=NSMakePoint(200,100);
      pan.eventPhase=NSEventPhaseBegan;pan.dx=12;pan.dy=-8;
      if(path<2 || path==4) {
        Check([view consumeScroll:pan],"motion probe admits native pan");
        [view renderMotionAt:NSProcessInfo.processInfo.systemUptime];
      } else if(path==2) {
        [view applyPinch:.1 ended:NO cancelled:NO];
      } else {
        [view resizeEvent:pan phase:0];
        pan.targetPoint=NSMakePoint(300,180);[view resizeEvent:pan phase:1];
      }
      __block BOOL injected=NO;
      __block uint64_t nextGeneration=0;
      __block NSRect nextFrame=NSZeroRect;
      __weak LifecyclePanel* weakPanel=panel;
      LifecyclePanel* frameOwner=panel;
      if(path==4) {
        id pressure=[view valueForKey:@"pressureFeedback"];
        Check(pressure!=nil,"pressure callback test uses the production string presentation");
        frameOwner=LifecycleWindow(NSZeroRect);frameOwner.admitted=YES;
        [pressure setValue:frameOwner forKey:@"window"];
      }
      frameOwner.frameHook=^{
        injected=YES;
        if(replacement==2) {
          [view stopMotion];[view ensureMotion];
        } else {
          [view prepareForHide];
          if(replacement==1) {
            weakPanel.admitted=NO;
            Placement placement;placement.width=480;
            [view preparePlacement:placement opener:nil aspect:16./9. limits:{}];
            weakPanel.admitted=YES;[view ensureMotion];
          } else if(replacement==3) [view invalidate];
        }
        nextGeneration=[[view valueForKey:@"motionGeneration"] unsignedLongLongValue];
        nextFrame=weakPanel.frame;
      };
      [view setValue:@(NSProcessInfo.processInfo.systemUptime+1) forKey:@"lastRenderAt"];
      pan.eventPhase=NSEventPhaseChanged;pan.dx=36;pan.dy=-20;
      if(path<2 || path==4) Check([view consumeScroll:pan],"motion probe accepts continued two-axis displacement");
      [CATransaction begin];[CATransaction setDisableActions:NO];
      if(path==0 || path==4) [view renderMotionAt:NSProcessInfo.processInfo.systemUptime];
      else if(path==1) {state.effects.fill(!effects);controls.Update(state);}
      else if(path==2) [view applyPinch:0 ended:YES cancelled:NO];
      else [view resizeEvent:pan phase:2];
      Check(![CATransaction disableActions],"reentrant motion exits restore the enclosing Core Animation transaction");
      [CATransaction commit];
      Check(injected,"motion probe reaches the actual native frame setter");
      Check([[view valueForKey:@"motionGeneration"] unsignedLongLongValue]==nextGeneration && NSEqualRects(panel.frame,nextFrame),"old motion frame leaves the replacement geometry and ownership intact");
      if(replacement==0 || replacement==3) {
        Check(panel.alphaValue==0 && [view valueForKey:@"pressureFeedback"]==nil,"hidden motion frame cannot recreate pressure windows or reveal the parent");
      } else {
        Check(![[view valueForKey:@"hiding"] boolValue] && panel.alphaValue==1,"replacement motion remains available and visible");
        [view renderMotionAt:NSProcessInfo.processInfo.systemUptime];
        Check(NSEqualRects(panel.frame,nextFrame),"fresh replacement motion renders its own geometry");
      }
      panel.admitted=NO;
    }
  }
  method_setImplementation(class_getInstanceMethod(NSWindow.class,@selector(orderWindow:relativeTo:)),oldOrder);
}

static __weak ArciumPiPNativeOverlay* startupView;
static void (^startupPressureCallback)(void);
static void StartupPressureOrder(id window,SEL,NSWindowOrderingMode,NSInteger) {
  id pressure=[startupView valueForKey:@"pressureFeedback"];
  if (!startupPressureCallback || !pressure || window != [pressure valueForKey:@"window"]) return;
  auto callback=startupPressureCallback;startupPressureCallback=nil;callback();
}
static void CheckFreshPanBoundary() {
  using namespace arcium::pip;
  const IMP oldOrder=method_setImplementation(class_getInstanceMethod(NSWindow.class,@selector(orderWindow:relativeTo:)),(IMP)StartupPressureOrder);
  for(int replacement=0;replacement<4;++replacement) { @autoreleasepool {
    auto* panel=LifecycleWindow(NSMakeRect(300,300,640,360));panel.admitted=YES;
    NativeControls controls(panel,[](Action,double){});
    auto* view=(ArciumPiPNativeOverlay*)controls.GetNativeView().Get();[panel.contentView addSubview:view];startupView=view;
    State state;state.effects.fill(true);controls.Update(state);
    __block BOOL injected=NO;
    __block uint64_t generation=0;
    __block NSRect expected=NSZeroRect;
    __weak LifecyclePanel* weakPanel=panel;
    startupPressureCallback=^{
      injected=YES;
      if(replacement==2) {[view stopMotion];[view ensureMotion];}
      else {
        [view prepareForHide];
        if(replacement==1) {
          weakPanel.admitted=NO;Placement placement;placement.width=480;
          [view preparePlacement:placement opener:nil aspect:16./9. limits:{}];
          weakPanel.admitted=YES;[view ensureMotion];
        } else if(replacement==3) [view invalidate];
      }
      generation=[[view valueForKey:@"motionGeneration"] unsignedLongLongValue];expected=weakPanel.frame;
    };
    auto* pan=[PanTestEvent new];pan.targetWindow=panel;pan.targetPoint=NSMakePoint(200,100);
    pan.eventPhase=NSEventPhaseBegan;pan.dx=12;pan.dy=-8;
    Check([view consumeScroll:pan],"fresh pan completes safely when its first native presentation is cancelled");
    Check(injected && !startupPressureCallback,"fresh pan reaches the production pressure-window ordering callback");
    Check([[view valueForKey:@"motionGeneration"] unsignedLongLongValue]==generation && NSEqualRects(panel.frame,expected),"fresh pan cannot mutate its replacement after initial presentation");
    Check(![[view valueForKey:@"scrolling"] boolValue] && ![[view valueForKey:@"magnifying"] boolValue],"cancelled startup leaves no stale input ownership");
    panel.admitted=NO;startupView=nil;startupPressureCallback=nil;
  }}
  method_setImplementation(class_getInstanceMethod(NSWindow.class,@selector(orderWindow:relativeTo:)),oldOrder);
}

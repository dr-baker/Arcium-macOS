static void CheckSessionBoundaries() {
  using namespace arcium::pip;
  const IMP oldOrder=method_setImplementation(class_getInstanceMethod(NSWindow.class,@selector(orderWindow:relativeTo:)),(IMP)NoLifecycleOrder);
  @autoreleasepool {
    auto* panel=LifecycleWindow(NSMakeRect(300,300,640,360));
    panel.admitted=YES;
    int returns=0;
    NativeControls controls(panel,[&](Action action,double){if(action==Action::kReturn)++returns;});
    auto* view=(ArciumPiPNativeOverlay*)controls.GetNativeView().Get();
    [panel.contentView addSubview:view];
    State state; state.can_play=true; controls.Update(state);
    const NSRect prePinchFrame=panel.frame;
    auto* recognizer=[TestPinchRecognizer new];
    recognizer.testState=NSGestureRecognizerStateBegan; recognizer.magnification=.1;
    [view recognizePinch:recognizer]; [view flushResizeFrame];
    Check([[view valueForKey:@"magnifying"] boolValue],"extra: nonkey admitted pinch starts");
    controls.RestorePlacementForHide();
    Check(NSEqualRects(panel.frame,prePinchFrame),"hide preserves the cancelled pinch start frame, not its enlarged presentation");
    Check(!controls.TakeUserPlacement(),"hiding a cancelled pinch does not persist its intermediate width");
    panel.admitted=NO;
    Placement placement; placement.width=640;
    controls.PreparePlacement(placement,nil,16./9.,{}); panel.admitted=YES;
    const NSRect reopened=panel.frame;
    recognizer.testState=NSGestureRecognizerStateChanged; recognizer.magnification=.1;
    [view recognizePinch:recognizer]; [view flushResizeFrame];
    fprintf(stderr,"EXTRA hide/reopen without resign: late Changed magnifying=%d width_before=%.0f width_after=%.0f interrupted=%d\n",
      [[view valueForKey:@"magnifying"] boolValue],NSWidth(reopened),NSWidth(panel.frame),[[view valueForKey:@"pinchInterrupted"] boolValue]);
    Check(![[view valueForKey:@"magnifying"] boolValue] && NSEqualRects(panel.frame,reopened),"old native Changed cannot resize a reopened nonkey session");
    [view cancelGestureInput];
    auto* raw=[HoverMagnifyEvent new]; raw.targetWindow=panel; raw.targetPoint=NSMakePoint(200,100);
    raw.eventPhase=NSEventPhaseBegan; raw.delta=.1; [view consumeMagnify:raw]; [view flushResizeFrame];
    Check([[view valueForKey:@"magnifying"] boolValue],"extra: nonkey raw pinch starts");
    controls.RestorePlacementForHide(); panel.admitted=NO;
    controls.PreparePlacement(placement,nil,16./9.,{}); panel.admitted=YES;
    const NSRect rawReopened=panel.frame;
    raw.eventPhase=NSEventPhaseChanged; raw.delta=.1; [view consumeMagnify:raw]; [view flushResizeFrame];
    fprintf(stderr,"EXTRA raw hide/reopen without resign: late Changed magnifying=%d width_before=%.0f width_after=%.0f\n",
      [[view valueForKey:@"magnifying"] boolValue],NSWidth(rawReopened),NSWidth(panel.frame));
    Check(![[view valueForKey:@"magnifying"] boolValue] && NSEqualRects(panel.frame,rawReopened),"old raw Changed cannot resize a reopened nonkey session");
    [view cancelGestureInput];
    raw.eventPhase=NSEventPhaseBegan;raw.delta=.1;[view consumeMagnify:raw];[view flushResizeFrame];
    Check([[view valueForKey:@"magnifying"] boolValue],"fresh raw Began works after hide/reopen fence");
    raw.eventPhase=NSEventPhaseEnded;raw.delta=0;[view consumeMagnify:raw];
    auto* home=LifecycleWindow(NSMakeRect(100,100,900,600)); home.admitted=YES;
    [view setValue:home forKey:@"openerWindow"];
    state.effects[static_cast<size_t>(Effect::kReturn)]=true; controls.Update(state);
    if(!ReduceMotion()) {
      [view returnToTab:nil]; NSTimer* timer=[view valueForKey:@"returnTimer"];
      Check(timer!=nil,"extra: Return timer starts");
      __block BOOL hiddenInside=NO;
      panel.frameHook=^{[view prepareForHide]; hiddenInside=panel.alphaValue==0;};
      [view setValue:@(NSProcessInfo.processInfo.systemUptime-.1) forKey:@"returnStart"];
      [timer fire];
      fprintf(stderr,"EXTRA Return frame callback hides: alpha_inside_zero=%d alpha_after=%.6f hiding=%d timer_valid=%d\n",
        hiddenInside,panel.alphaValue,[[view valueForKey:@"hiding"] boolValue],timer.valid);
      Check(hiddenInside && panel.alphaValue==0 && [[view valueForKey:@"hiding"] boolValue] && !timer.valid,"executing Return cannot overwrite reentrant hide opacity");
      panel.admitted=NO; controls.PreparePlacement(placement,home,16./9.,{}); panel.admitted=YES;
      [view returnToTab:nil]; timer=[view valueForKey:@"returnTimer"];
      Check(timer!=nil,"extra: second Return timer starts");
      __weak LifecyclePanel* weakPanel=panel;
      panel.frameHook=^{
        [view prepareForHide]; weakPanel.admitted=NO;
        [view preparePlacement:placement opener:home aspect:16./9. limits:{}]; weakPanel.admitted=YES;
      };
      [view setValue:@(NSProcessInfo.processInfo.systemUptime-1) forKey:@"returnStart"]; [timer fire];
      __block BOOL drained=NO; dispatch_async(dispatch_get_main_queue(),^{drained=YES;});
      for(int i=0;i<50&&!drained;++i)CFRunLoopRunInMode(kCFRunLoopDefaultMode,.01,false);
      fprintf(stderr,"EXTRA completed Return frame callback hides/reopens: new_session_alpha=%.6f returns=%d hiding=%d\n",panel.alphaValue,returns,[[view valueForKey:@"hiding"] boolValue]);
      Check(drained && returns==0 && panel.alphaValue==1 && ![[view valueForKey:@"hiding"] boolValue],"executing old Return cannot change reopened opacity or deliver through the replacement session");
      [view returnToTab:nil];timer=[view valueForKey:@"returnTimer"];
      const auto sameGeneration=[[view valueForKey:@"sessionGeneration"] unsignedLongLongValue];
      panel.frameHook=^{[view cancelReturn:YES];[view returnToTab:nil];};
      [view setValue:@(NSProcessInfo.processInfo.systemUptime-1) forKey:@"returnStart"];[timer fire];
      NSTimer* replacement=[view valueForKey:@"returnTimer"];
      Check(replacement && replacement!=timer && replacement.valid && !timer.valid,"reentrant Return replacement retains its own timer");
      Check([[view valueForKey:@"sessionGeneration"] unsignedLongLongValue]==sameGeneration && panel.alphaValue==1,"old Return cannot overwrite replacement animation in the same session");
      [view cancelReturn:YES];
      drained=NO;dispatch_async(dispatch_get_main_queue(),^{drained=YES;});
      for(int i=0;i<50&&!drained;++i)CFRunLoopRunInMode(kCFRunLoopDefaultMode,.01,false);
      Check(drained && returns==0,"old completion cannot deliver a replacement Return early");
    }
    panel.admitted=home.admitted=NO;
  }
  method_setImplementation(class_getInstanceMethod(NSWindow.class,@selector(orderWindow:relativeTo:)),oldOrder);
}

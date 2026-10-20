#import <AppKit/AppKit.h>

@interface LabHostPanel : NSPanel
@end

#ifdef __cplusplus
extern "C" {
#endif
NSView* LabCreateMaterialView(void);
void LabApplyMaterial(NSView* view, int material, double red, double green,
                      double blue, double alpha, double radius);
void LabSetWindowAppearance(NSWindow* window, int appearance);
#ifdef __cplusplus
}
#endif

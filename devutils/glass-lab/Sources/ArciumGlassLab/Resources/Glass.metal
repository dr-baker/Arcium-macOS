#include <CoreImage/CoreImage.h>
using namespace metal;

// Port of cc/paint/paint_filter.cc kGlassmorphicSkSL. Image inputs are the
// production two-stage Gaussian backdrop, not the older standalone lab shader.
extern "C" { namespace coreimage {
float boxDistance(float2 p, float2 h, float r) {
    float2 q = abs(p) - h + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
float2 boxNormal(float2 p, float2 h, float r) {
    float2 x = float2(1, 0), y = float2(0, 1);
    float2 g = float2(boxDistance(p+x,h,r)-boxDistance(p-x,h,r),
                      boxDistance(p+y,h,r)-boxDistance(p-y,h,r));
    return g / max(length(g), 0.0001);
}
float4 glassLab(sampler backdrop, sampler softenedBackdrop,
                float2 origin, float2 size, float radius,
                float edgeWidth, float refraction, float dispersion,
                float tintStrength, float3 tint, float specular, float grain,
                destination dest) {
    // CI's y axis points up; Skia's points down. Work in Skia local coordinates
    // for geometry, lighting and grain, then convert samples back to CI.
    float2 ciPosition = dest.coord();
    float2 local = float2(ciPosition.x-origin.x-size.x*.5,
                         origin.y+size.y*.5-ciPosition.y);
    float2 halfSize = size * .5;
    float d = boxDistance(local, halfSize, radius);
    float4 source = backdrop.sample(backdrop.transform(ciPosition));
    float coverage = 1 - smoothstep(-1.0, 1.0, d);
    float edge = smoothstep(-edgeWidth, 0.0, d);
    float2 normal = boxNormal(local, halfSize, radius);
    float2 bend = normal * refraction * edge;
    float2 ciBend = float2(bend.x, -bend.y);
    float3 softened = softenedBackdrop.sample(softenedBackdrop.transform(ciPosition+ciBend)).rgb;
    float2 spectralBend = ciBend * dispersion;
    float4 rs = backdrop.sample(backdrop.transform(ciPosition+ciBend+spectralBend));
    float4 gs = backdrop.sample(backdrop.transform(ciPosition+ciBend));
    float4 bs = backdrop.sample(backdrop.transform(ciPosition+ciBend-spectralBend));
    float3 spectral = float3(rs.r, gs.g, bs.b);
    float3 color = mix(softened, spectral, .42+edge*.38);
    float luminance = dot(color, float3(.2126,.7152,.0722));
    color = mix(float3(luminance), color, 1.10);
    color = mix(color, color*tint+tint*.22, tintStrength);
    float3 light = normalize(float3(-.65,-.75,.85));
    float spec = pow(max(dot(normal, light.xy), 0.0), 4.0);
    color += float3(.82,.92,1)*spec*specular*edge*1.55;
    color += tint*edge*specular*.045;
    float2 position = float2(ciPosition.x, origin.y+size.y-ciPosition.y);
    float noise = fract(sin(dot(floor(position),float2(12.9898,78.233)))*43758.5453);
    color += (noise-.5)*grain;
    float3 complete = clamp(color, 0.0, 1.0);
    return float4(mix(source.rgb, complete, coverage), source.a);
}
}}

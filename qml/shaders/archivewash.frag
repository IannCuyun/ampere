#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float artOpacity;
    float veilOpacity;
    // How much of the SHARP whole-record layer the room carries. 1.0 is the
    // locked Archive Wash. Now Playing drives it to 0 so the page holds one
    // sharp record (its sleeve) over a soft field, never two copies.
    float fitStrength;
    vec2 itemSize;
    vec2 ambientPixels;
    vec2 fitPixels;
};

layout(binding = 1) uniform sampler2D ambientSource;
layout(binding = 2) uniform sampler2D fitSource;

float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

vec4 sampleSoft(sampler2D image, vec2 uv, vec2 stepUv) {
    vec4 c = texture(image, uv) * 4.0;
    c += texture(image, uv + vec2(stepUv.x, 0.0)) * 2.0;
    c += texture(image, uv - vec2(stepUv.x, 0.0)) * 2.0;
    c += texture(image, uv + vec2(0.0, stepUv.y)) * 2.0;
    c += texture(image, uv - vec2(0.0, stepUv.y)) * 2.0;
    c += texture(image, uv + stepUv);
    c += texture(image, uv - stepUv);
    c += texture(image, uv + vec2(stepUv.x, -stepUv.y));
    c += texture(image, uv + vec2(-stepUv.x, stepUv.y));
    return c * (1.0 / 16.0);
}

vec4 tone(vec4 sampleColor) {
    float a = sampleColor.a;
    vec3 straight = a > 0.0001 ? sampleColor.rgb / a : vec3(0.0);
    straight = clamp(0.72 * straight - 0.02, 0.0, 1.0);
    return vec4(straight * a, a);
}

void main() {
    vec2 viewport = max(itemSize, vec2(1.0));
    vec2 ambientSize = max(ambientPixels, vec2(1.0));
    vec2 fitSize = max(fitPixels, vec2(1.0));
    float viewportAspect = viewport.x / viewport.y;
    float sourceAspect = fitSize.x / fitSize.y;

    vec2 cropSpan = vec2(min(1.0, viewportAspect / sourceAspect),
                         min(1.0, sourceAspect / viewportAspect));
    vec2 cropUv = vec2(0.5) + (qt_TexCoord0 - vec2(0.5)) * cropSpan;

    vec2 fitSpan = vec2(min(1.0, sourceAspect / viewportAspect),
                        min(1.0, viewportAspect / sourceAspect));
    vec2 fitUv = vec2(0.5) + (qt_TexCoord0 - vec2(0.5)) / fitSpan;

    vec2 ambientTexel = 1.0 / ambientSize;
    vec2 cropStep = max(cropSpan * (vec2(8.0) / viewport), ambientTexel);
    vec4 crop = tone(sampleSoft(ambientSource,
                                clamp(cropUv, 0.0, 1.0), cropStep));
    // As the sharp layer steps back the soft field carries the record alone,
    // so it comes forward to keep the room unmistakably this album's.
    float cropOpacity = mix(0.88, 0.55, fitStrength) * artOpacity;
    vec3 room = vec3(16.0, 14.0, 13.0) / 255.0;
    room = room * (1.0 - crop.a * cropOpacity) + crop.rgb * cropOpacity;

    // Now Playing drives fitStrength to zero. Avoid nine full-resolution
    // texture reads per output pixel when that layer contributes nothing.
    if (fitStrength > 0.001) {
        vec2 fitEdgePixels = (0.5 * fitSpan
                              - abs(qt_TexCoord0 - vec2(0.5))) * viewport;
        float fitFeather = smoothstep(-18.0, 18.0,
                                      min(fitEdgePixels.x, fitEdgePixels.y));
        vec4 fit = tone(sampleSoft(fitSource, clamp(fitUv, 0.0, 1.0),
                                   1.0 / fitSize));
        float fitOpacity = fitFeather * artOpacity * fitStrength;
        room = room * (1.0 - fit.a * fitOpacity) + fit.rgb * fitOpacity;
    }

    room = mix(room, vec3(10.0, 9.0, 9.0) / 255.0, veilOpacity);
    float n = hash12(gl_FragCoord.xy) + hash12(gl_FragCoord.xy + 41.7) - 1.0;
    room += n * (1.6 / 255.0);
    fragColor = vec4(clamp(room, 0.0, 1.0), 1.0) * qt_Opacity;
}

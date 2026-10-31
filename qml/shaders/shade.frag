#version 440
// The room gradient, computed per-fragment on the GPU. Full float precision
// down the whole screen with a triangular-PDF dither of ~1 LSB added at the
// end — the 8-bit framebuffer physically cannot band, and since nothing is
// ever sampled from a stretched image, it cannot streak either.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec4 cTop;
    vec4 cBot;
};

float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

void main() {
    float t = clamp(qt_TexCoord0.y, 0.0, 1.0);
    t = t * t * (3.0 - 2.0 * t);                    // smoothstep easing
    vec3 c = mix(cTop.rgb, cBot.rgb, t);
    float n = hash12(gl_FragCoord.xy) + hash12(gl_FragCoord.xy + 41.7) - 1.0;
    c += n * (1.6 / 255.0);
    fragColor = vec4(clamp(c, 0.0, 1.0), 1.0) * qt_Opacity;
}

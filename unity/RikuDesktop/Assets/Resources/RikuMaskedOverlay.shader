Shader "Riku/MaskedOverlay"
{
    Properties
    {
        [PerRendererData] _MainTex ("Texture", 2D) = "white" {}
        _Color ("Tint", Color) = (1, 1, 1, 1)
        _MaskCenterA ("Mask Center A", Vector) = (0.5, 0.5, 0, 0)
        _MaskRadiusA ("Mask Radius A", Vector) = (0.1, 0.1, 0, 0)
        _MaskCenterB ("Mask Center B", Vector) = (0.5, 0.5, 0, 0)
        _MaskRadiusB ("Mask Radius B", Vector) = (0, 0, 0, 0)
    }
    SubShader
    {
        Tags { "Queue"="Transparent" "RenderType"="Transparent" "IgnoreProjector"="True" }
        Cull Off
        Lighting Off
        ZWrite Off
        ZTest Always
        Blend SrcAlpha OneMinusSrcAlpha

        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"

            sampler2D _MainTex;
            fixed4 _Color;
            float4 _MaskCenterA;
            float4 _MaskRadiusA;
            float4 _MaskCenterB;
            float4 _MaskRadiusB;

            struct appdata
            {
                float4 vertex : POSITION;
                float2 uv : TEXCOORD0;
                fixed4 color : COLOR;
            };
            struct v2f
            {
                float4 vertex : SV_POSITION;
                float2 uv : TEXCOORD0;
                fixed4 color : COLOR;
            };

            v2f vert(appdata v)
            {
                v2f o;
                o.vertex = UnityObjectToClipPos(v.vertex);
                o.uv = v.uv;
                o.color = v.color;
                return o;
            }

            float ellipse(float2 uv, float2 center, float2 radius)
            {
                float distance = length((uv - center) / max(radius, float2(0.0001, 0.0001)));
                return 1.0 - smoothstep(0.65, 1.0, distance);
            }

            fixed4 frag(v2f i) : SV_Target
            {
                fixed4 color = tex2D(_MainTex, i.uv) * _Color * i.color;
                float mask = ellipse(i.uv, _MaskCenterA.xy, _MaskRadiusA.xy);
                if (_MaskRadiusB.x > 0.0 && _MaskRadiusB.y > 0.0)
                    mask = max(mask, ellipse(i.uv, _MaskCenterB.xy, _MaskRadiusB.xy));
                color.a *= saturate(mask);
                return color;
            }
            ENDCG
        }
    }
}

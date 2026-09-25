using UnityEngine;
using UnityEngine.UI;
using uLipSync;

public sealed class RikuAvatarPresenter : MonoBehaviour
{
    private RawImage baseImage;
    private RawImage mouthClosedImage;
    private RawImage blinkImage;
    private RectTransform artRoot;
    private AudioSource voiceSource;
    private uLipSync.uLipSync analyzer;
    private Material mouthMask;
    private Material blinkMask;
    private readonly float[] outputSamples = new float[256];
    private float targetOpen;
    private float mouthOpen;
    private float lastLipSyncAt;
    private float nextBlinkAt;
    private float blinkEndAt;

    public void Configure(RectTransform root, RawImage portrait, RawImage mouth, RawImage blink, AudioSource source)
    {
        artRoot = root;
        baseImage = portrait;
        mouthClosedImage = mouth;
        blinkImage = blink;
        voiceSource = source;

        baseImage.texture = Resources.Load<Texture2D>("RikuAvatarOpen");
        mouthClosedImage.texture = Resources.Load<Texture2D>("RikuAvatarMouthClosed");
        blinkImage.texture = Resources.Load<Texture2D>("RikuAvatarBlink");
        if (!baseImage.texture || !mouthClosedImage.texture || !blinkImage.texture)
            Debug.LogError("リクの立ち絵素材がResourcesにありません。");

        Shader shader = Resources.Load<Shader>("RikuMaskedOverlay");
        if (!shader) shader = Shader.Find("Riku/MaskedOverlay");
        if (shader)
        {
            mouthMask = MakeMask(shader,
                new Vector2(0.50f, 0.79f), new Vector2(0.13f, 0.06f),
                Vector2.zero, Vector2.zero);
            blinkMask = MakeMask(shader,
                new Vector2(0.41f, 0.82f), new Vector2(0.08f, 0.035f),
                new Vector2(0.50f, 0.85f), new Vector2(0.08f, 0.035f));
            mouthClosedImage.material = mouthMask;
            blinkImage.material = blinkMask;
        }
        else
        {
            // A full-frame overlay would obscure the avatar. Keep it hidden if the mask fails.
            mouthClosedImage.enabled = false;
            blinkImage.enabled = false;
            Debug.LogError("Riku/MaskedOverlay シェーダーが見つかりません。");
        }

        Profile profile = Resources.Load<Profile>("RikuLipSyncProfile");
        if (profile)
        {
            analyzer = voiceSource.gameObject.AddComponent<uLipSync.uLipSync>();
            analyzer.profile = profile;
            analyzer.onLipSyncUpdate.AddListener(OnLipSyncUpdate);
        }
        else
        {
            Debug.LogWarning("uLipSync Profileがありません。音量に基づく口パクを使います。");
        }
        nextBlinkAt = Time.unscaledTime + Random.Range(2.5f, 5.5f);
    }

    private static Material MakeMask(Shader shader, Vector2 centerA, Vector2 radiusA,
        Vector2 centerB, Vector2 radiusB)
    {
        var material = new Material(shader);
        material.SetVector("_MaskCenterA", new Vector4(centerA.x, centerA.y, 0f, 0f));
        material.SetVector("_MaskRadiusA", new Vector4(radiusA.x, radiusA.y, 0f, 0f));
        material.SetVector("_MaskCenterB", new Vector4(centerB.x, centerB.y, 0f, 0f));
        material.SetVector("_MaskRadiusB", new Vector4(radiusB.x, radiusB.y, 0f, 0f));
        return material;
    }

    public void OnLipSyncUpdate(LipSyncInfo info)
    {
        targetOpen = Mathf.Clamp01(info.volume * 1.5f);
        lastLipSyncAt = Time.unscaledTime;
    }

    private void Update()
    {
        if (!artRoot || !voiceSource) return;

        if (!voiceSource.isPlaying)
            targetOpen = 0f;
        else if (analyzer == null || Time.unscaledTime - lastLipSyncAt > 0.25f)
        {
            voiceSource.GetOutputData(outputSamples, 0);
            float energy = 0f;
            foreach (float sample in outputSamples) energy += sample * sample;
            targetOpen = Mathf.Clamp01((Mathf.Sqrt(energy / outputSamples.Length) - 0.012f) * 13f);
        }
        mouthOpen = Mathf.Lerp(mouthOpen, targetOpen, 1f - Mathf.Exp(-18f * Time.unscaledDeltaTime));
        SetAlpha(mouthClosedImage, 1f - mouthOpen);

        if (Time.unscaledTime >= nextBlinkAt)
        {
            blinkEndAt = Time.unscaledTime + 0.16f;
            nextBlinkAt = Time.unscaledTime + Random.Range(2.8f, 6.2f);
        }
        SetAlpha(blinkImage, Time.unscaledTime < blinkEndAt ? 1f : 0f);

        float bob = Mathf.Sin(Time.unscaledTime * 1.4f) * (voiceSource.isPlaying ? 6f : 3f);
        artRoot.anchoredPosition = new Vector2(0f, bob);
        artRoot.localRotation = Quaternion.Euler(0f, 0f, Mathf.Sin(Time.unscaledTime * 0.7f) * 0.6f);
    }

    private static void SetAlpha(RawImage image, float alpha)
    {
        if (!image || !image.enabled) return;
        Color color = image.color;
        color.a = alpha;
        image.color = color;
    }

    private void OnDestroy()
    {
        if (analyzer) analyzer.onLipSyncUpdate.RemoveListener(OnLipSyncUpdate);
        if (mouthMask) Destroy(mouthMask);
        if (blinkMask) Destroy(blinkMask);
    }
}

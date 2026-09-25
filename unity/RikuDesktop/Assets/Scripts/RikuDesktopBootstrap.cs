using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

public sealed class RikuDesktopBootstrap : MonoBehaviour
{
    private static readonly Color Deep = new Color(0.025f, 0.065f, 0.10f);
    private static readonly Color Panel = new Color(0.055f, 0.12f, 0.17f);
    private static readonly Color Accent = new Color(0.32f, 0.89f, 1f);
    private static readonly Color Ink = new Color(0.91f, 0.97f, 1f);
    private Font uiFont;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Boot()
    {
        if (FindFirstObjectByType<RikuDesktopBootstrap>() == null)
            new GameObject("Riku Desktop").AddComponent<RikuDesktopBootstrap>();
    }

    private void Awake()
    {
        Application.targetFrameRate = 60;
        uiFont = Font.CreateDynamicFontFromOSFont(new[] { "Yu Gothic UI", "Meiryo", "Arial" }, 20);

        var canvasObject = new GameObject("Main Canvas", typeof(RectTransform), typeof(Canvas),
            typeof(CanvasScaler), typeof(GraphicRaycaster));
        var canvas = canvasObject.GetComponent<Canvas>();
        canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        var scaler = canvasObject.GetComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        scaler.referenceResolution = new Vector2(1440, 900);
        scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
        scaler.matchWidthOrHeight = 0.5f;

        var background = PanelObject("Background", canvasObject.transform, Deep,
            Vector2.zero, Vector2.one, Vector2.zero, Vector2.zero);
        var left = PanelObject("Avatar Panel", background.transform, Panel,
            Vector2.zero, new Vector2(0.43f, 1f), Vector2.zero, Vector2.zero);
        var right = PanelObject("Conversation Panel", background.transform, Deep,
            new Vector2(0.43f, 0f), Vector2.one, Vector2.zero, Vector2.zero);

        var art = new GameObject("Riku Art", typeof(RectTransform));
        art.transform.SetParent(left.transform, false);
        SetRect(art.GetComponent<RectTransform>(), new Vector2(0.02f, 0.04f),
            new Vector2(0.98f, 0.95f), Vector2.zero, Vector2.zero);
        var fitter = art.AddComponent<AspectRatioFitter>();
        fitter.aspectMode = AspectRatioFitter.AspectMode.FitInParent;
        fitter.aspectRatio = 2f / 3f;
        RawImage portrait = Layer("Portrait", art.transform);
        RawImage mouth = Layer("Mouth Closed", art.transform);
        RawImage blink = Layer("Blink", art.transform);
        portrait.raycastTarget = mouth.raycastTarget = blink.raycastTarget = false;

        Text name = Label("Name", left.transform, "リク", 36, Ink,
            new Vector2(0.05f, 0.90f), new Vector2(0.7f, 0.98f));
        name.fontStyle = FontStyle.Bold;
        Label("Subtitle", left.transform, "DAILY AI PARTNER", 15, Accent,
            new Vector2(0.05f, 0.86f), new Vector2(0.8f, 0.90f));

        Text title = Label("Title", right.transform, "リクと話す", 34, Ink,
            new Vector2(0.05f, 0.88f), new Vector2(0.95f, 0.96f));
        title.fontStyle = FontStyle.Bold;
        Text status = Label("Status", right.transform, "サーバーを確認しています…", 17, Accent,
            new Vector2(0.05f, 0.81f), new Vector2(0.95f, 0.87f));

        var chat = PanelObject("Chat", right.transform, Panel,
            new Vector2(0.05f, 0.29f), new Vector2(0.95f, 0.80f), Vector2.zero, Vector2.zero);
        Text transcript = Label("Transcript", chat.transform,
            "リク：こんにちは。話したいことを聞かせて。", 22, Ink,
            new Vector2(0.035f, 0.05f), new Vector2(0.965f, 0.95f));
        transcript.verticalOverflow = VerticalWrapMode.Truncate;

        var inputPanel = PanelObject("Input", right.transform, Panel,
            new Vector2(0.05f, 0.15f), new Vector2(0.95f, 0.27f), Vector2.zero, Vector2.zero);
        var input = inputPanel.AddComponent<InputField>();
        Text inputText = Label("Input Text", inputPanel.transform, "", 22, Ink,
            new Vector2(0.03f, 0.1f), new Vector2(0.97f, 0.9f));
        Text placeholder = Label("Placeholder", inputPanel.transform, "ここに入力して話す", 21,
            new Color(0.55f, 0.66f, 0.72f), new Vector2(0.03f, 0.1f), new Vector2(0.97f, 0.9f));
        input.textComponent = inputText;
        input.placeholder = placeholder;
        input.lineType = InputField.LineType.MultiLineNewline;

        Button send = ButtonObject("Send", right.transform, "送る", Accent,
            new Vector2(0.05f, 0.055f), new Vector2(0.46f, 0.13f));
        Button mic = ButtonObject("Mic", right.transform, "マイクで話す", new Color(0.18f, 0.31f, 0.38f),
            new Vector2(0.54f, 0.055f), new Vector2(0.95f, 0.13f));

        if (FindFirstObjectByType<EventSystem>() == null)
        {
            var events = new GameObject("Event System", typeof(EventSystem), typeof(StandaloneInputModule));
            events.transform.SetParent(canvasObject.transform, false);
        }

        var voiceObject = new GameObject("Riku Voice");
        var voice = voiceObject.AddComponent<AudioSource>();
        voice.playOnAwake = false;
        voice.spatialBlend = 0f;
        var avatar = gameObject.AddComponent<RikuAvatarPresenter>();
        avatar.Configure(art.GetComponent<RectTransform>(), portrait, mouth, blink, voice);
        var client = gameObject.AddComponent<RikuDesktopClient>();
        client.Configure(input, transcript, status, mic.GetComponentInChildren<Text>(), voice);
        send.onClick.AddListener(client.SendTypedMessage);
        mic.onClick.AddListener(client.ToggleMicrophone);
    }

    private static void SetRect(RectTransform rect, Vector2 min, Vector2 max,
        Vector2 offsetMin, Vector2 offsetMax)
    {
        rect.anchorMin = min;
        rect.anchorMax = max;
        rect.offsetMin = offsetMin;
        rect.offsetMax = offsetMax;
    }

    private static GameObject PanelObject(string name, Transform parent, Color color,
        Vector2 min, Vector2 max, Vector2 offsetMin, Vector2 offsetMax)
    {
        var obj = new GameObject(name, typeof(RectTransform), typeof(Image));
        obj.transform.SetParent(parent, false);
        SetRect(obj.GetComponent<RectTransform>(), min, max, offsetMin, offsetMax);
        obj.GetComponent<Image>().color = color;
        return obj;
    }

    private static RawImage Layer(string name, Transform parent)
    {
        var obj = new GameObject(name, typeof(RectTransform), typeof(RawImage));
        obj.transform.SetParent(parent, false);
        SetRect(obj.GetComponent<RectTransform>(), Vector2.zero, Vector2.one,
            Vector2.zero, Vector2.zero);
        return obj.GetComponent<RawImage>();
    }

    private Text Label(string name, Transform parent, string value, int size,
        Color color, Vector2 min, Vector2 max)
    {
        var obj = new GameObject(name, typeof(RectTransform), typeof(Text));
        obj.transform.SetParent(parent, false);
        SetRect(obj.GetComponent<RectTransform>(), min, max, Vector2.zero, Vector2.zero);
        Text text = obj.GetComponent<Text>();
        text.font = uiFont;
        text.text = value;
        text.fontSize = size;
        text.color = color;
        text.alignment = TextAnchor.MiddleLeft;
        text.horizontalOverflow = HorizontalWrapMode.Wrap;
        text.raycastTarget = false;
        return text;
    }

    private Button ButtonObject(string name, Transform parent, string caption,
        Color background, Vector2 min, Vector2 max)
    {
        var obj = PanelObject(name, parent, background, min, max, Vector2.zero, Vector2.zero);
        Button button = obj.AddComponent<Button>();
        Text label = Label("Caption", obj.transform, caption, 20, Deep,
            Vector2.zero, Vector2.one);
        label.alignment = TextAnchor.MiddleCenter;
        label.fontStyle = FontStyle.Bold;
        return button;
    }
}

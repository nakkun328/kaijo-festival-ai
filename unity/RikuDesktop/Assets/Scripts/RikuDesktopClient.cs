using System;
using System.Collections;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

public sealed class RikuDesktopClient : MonoBehaviour
{
    private const string ApiBase = "http://127.0.0.1:8765";
    private InputField input;
    private Text transcript;
    private Text status;
    private Text micCaption;
    private AudioSource voice;
    private AudioClip recording;
    private float recordingStartedAt;
    private bool busy;

    [Serializable]
    private sealed class ChatRequest { public string message; }
    [Serializable]
    private sealed class VoiceRequest
    {
        public string text;
        public string emotion;
        public float intensity;
    }
    [Serializable]
    private sealed class AnimationInfo
    {
        public string emotion = "neutral";
        public float intensity = 0.65f;
    }
    [Serializable]
    private sealed class ChatReply
    {
        public string answer;
        public string error;
        public AnimationInfo animation;
    }
    [Serializable]
    private sealed class TranscribeReply { public string text; public string error; }
    [Serializable]
    private sealed class BootstrapReply { public bool ready; public string setupIssue; }

    public void Configure(InputField messageInput, Text conversation, Text statusLabel,
        Text microphoneCaption, AudioSource source)
    {
        input = messageInput;
        transcript = conversation;
        status = statusLabel;
        micCaption = microphoneCaption;
        voice = source;
        StartCoroutine(CheckBackend());
    }

    private IEnumerator CheckBackend()
    {
        using (var request = UnityWebRequest.Get(ApiBase + "/api/bootstrap"))
        {
            request.timeout = 8;
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                SetStatus("会話サーバーに接続できません。先にPythonサーバーを起動してください。");
                yield break;
            }
            var bootstrap = JsonUtility.FromJson<BootstrapReply>(request.downloadHandler.text);
            SetStatus(bootstrap != null && bootstrap.ready ? "会話できます" :
                (bootstrap?.setupIssue ?? "AIモデルの準備を確認してください。"));
        }
    }

    public void SendTypedMessage()
    {
        if (busy || recording || input == null) return;
        string message = input.text.Trim();
        if (message.Length == 0) return;
        input.text = "";
        StartCoroutine(Chat(message));
    }

    public void ToggleMicrophone()
    {
        if (busy) return;
        if (recording != null)
        {
            StopRecording();
            return;
        }
        if (Microphone.devices.Length == 0)
        {
            SetStatus("マイクが見つかりません。");
            return;
        }
        try
        {
            recording = Microphone.Start(null, false, 20, 16000);
        }
        catch (Exception error)
        {
            SetStatus("マイクを開始できません: " + error.Message);
            return;
        }
        recordingStartedAt = Time.unscaledTime;
        if (micCaption) micCaption.text = "録音を終了";
        SetStatus("録音中です。話し終えたらもう一度押してください。");
    }

    private void Update()
    {
        if (recording && Time.unscaledTime - recordingStartedAt > 0.5f &&
            !Microphone.IsRecording(null)) StopRecording();
    }

    private void StopRecording()
    {
        if (!recording) return;
        int frames = Microphone.GetPosition(null);
        if (frames <= 0 && Time.unscaledTime - recordingStartedAt >= 19f)
            frames = recording.samples;
        Microphone.End(null);
        AudioClip clip = recording;
        recording = null;
        if (micCaption) micCaption.text = "マイクで話す";
        if (frames < 1600)
        {
            Destroy(clip);
            SetStatus("短すぎて認識できませんでした。もう一度話してください。");
            return;
        }
        byte[] wav = EncodeWav(clip, frames);
        Destroy(clip);
        StartCoroutine(TranscribeAndChat(wav));
    }

    private IEnumerator TranscribeAndChat(byte[] wav)
    {
        busy = true;
        SetStatus("声を文字にしています…");
        using (var request = Post(ApiBase + "/api/transcribe", wav, "audio/wav"))
        {
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                SetStatus("文字起こしに失敗しました: " + ErrorText(request));
                busy = false;
                yield break;
            }
            var result = JsonUtility.FromJson<TranscribeReply>(request.downloadHandler.text);
            if (result == null || string.IsNullOrWhiteSpace(result.text))
            {
                SetStatus("声を認識できませんでした。もう一度話してください。");
                busy = false;
                yield break;
            }
            busy = false;
            yield return Chat(result.text.Trim());
        }
    }

    private IEnumerator Chat(string message)
    {
        busy = true;
        AddLine("あなた", message);
        SetStatus("リクが考えています…");
        byte[] payload = Encoding.UTF8.GetBytes(JsonUtility.ToJson(new ChatRequest { message = message }));
        using (var request = Post(ApiBase + "/api/chat", payload, "application/json"))
        {
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                SetStatus("会話に失敗しました: " + ErrorText(request));
                busy = false;
                yield break;
            }
            var reply = JsonUtility.FromJson<ChatReply>(request.downloadHandler.text);
            if (reply == null || string.IsNullOrWhiteSpace(reply.answer))
            {
                SetStatus("返答を受け取れませんでした。");
                busy = false;
                yield break;
            }
            AddLine("リク", reply.answer);
            string speech = Regex.Replace(reply.answer, @"\[\d+\]", "").Trim();
            if (speech.Length > 0)
                yield return Speak(speech, reply.animation);
        }
        busy = false;
        SetStatus("会話できます");
    }

    private IEnumerator Speak(string text, AnimationInfo animation)
    {
        for (int offset = 0; offset < text.Length; offset += 400)
        {
            string part = text.Substring(offset, Mathf.Min(400, text.Length - offset));
            var body = new VoiceRequest {
                text = part, emotion = animation?.emotion ?? "neutral",
                intensity = animation?.intensity ?? 0.65f,
            };
            string url = ApiBase + "/api/voice";
            using (var request = new UnityWebRequest(url, "POST"))
            {
                request.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(JsonUtility.ToJson(body)));
                request.downloadHandler = new DownloadHandlerAudioClip(url, AudioType.WAV);
                request.SetRequestHeader("Content-Type", "application/json");
                request.timeout = 45;
                SetStatus("リクが話しています…");
                yield return request.SendWebRequest();
                if (request.result != UnityWebRequest.Result.Success)
                {
                    SetStatus("音声を再生できませんでした: " + ErrorText(request));
                    yield break;
                }
                AudioClip clip = DownloadHandlerAudioClip.GetContent(request);
                voice.clip = clip;
                voice.Play();
                while (voice.isPlaying) yield return null;
                voice.clip = null;
                Destroy(clip);
            }
        }
    }

    private static UnityWebRequest Post(string url, byte[] payload, string contentType)
    {
        var request = new UnityWebRequest(url, "POST");
        request.uploadHandler = new UploadHandlerRaw(payload);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", contentType);
        request.timeout = 90;
        return request;
    }

    private static string ErrorText(UnityWebRequest request)
    {
        try
        {
            var body = JsonUtility.FromJson<ChatReply>(request.downloadHandler.text);
            if (!string.IsNullOrWhiteSpace(body?.error)) return body.error;
        }
        catch (Exception) { }
        return request.error;
    }

    private void AddLine(string speaker, string message)
    {
        transcript.text += "\n\n" + speaker + "：" + message;
        if (transcript.text.Length > 2500)
            transcript.text = transcript.text.Substring(transcript.text.Length - 2500);
    }

    private void SetStatus(string message)
    {
        if (status) status.text = message;
    }

    private static byte[] EncodeWav(AudioClip clip, int frames)
    {
        int channels = clip.channels;
        int sampleCount = Mathf.Min(frames, clip.samples) * channels;
        float[] samples = new float[clip.samples * channels];
        clip.GetData(samples, 0);
        using (var memory = new MemoryStream())
        using (var writer = new BinaryWriter(memory))
        {
            writer.Write(Encoding.ASCII.GetBytes("RIFF"));
            writer.Write(36 + sampleCount * 2);
            writer.Write(Encoding.ASCII.GetBytes("WAVEfmt "));
            writer.Write(16);
            writer.Write((short)1);
            writer.Write((short)channels);
            writer.Write(clip.frequency);
            writer.Write(clip.frequency * channels * 2);
            writer.Write((short)(channels * 2));
            writer.Write((short)16);
            writer.Write(Encoding.ASCII.GetBytes("data"));
            writer.Write(sampleCount * 2);
            for (int i = 0; i < sampleCount; i++)
                writer.Write((short)Mathf.RoundToInt(Mathf.Clamp(samples[i], -1f, 1f) * 32767f));
            return memory.ToArray();
        }
    }

    private void OnDestroy()
    {
        if (recording) Microphone.End(null);
    }
}

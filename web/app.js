const messages = document.querySelector("#messages");
const composer = document.querySelector("#composer");
const input = document.querySelector("#message");
const submit = composer.querySelector("button[type='submit']");
const reset = document.querySelector("#reset");
const status = document.querySelector("#status");
const suggestions = document.querySelector("#suggestions");
const provider = document.querySelector("#provider");
const startButton = document.querySelector("#conversation-start");
const stopButton = document.querySelector("#conversation-stop");
const speakerToggle = document.querySelector("#speaker-toggle");
const voiceState = document.querySelector("#voice-state");
const voiceEngineName = document.querySelector("#voice-engine-name");
const identity = document.querySelector(".identity");
const processMonitor = document.querySelector(".process-monitor");
const processNowLabel = document.querySelector("#process-now-label");
const processNowDetail = document.querySelector("#process-now-detail");
const processSteps = [...document.querySelectorAll(".process-step")];
const processDurations = new Map(
  [...document.querySelectorAll("[data-duration]")].map((element) => [element.dataset.duration, element]),
);
const avatarImage = document.querySelector("#avatar-image");
const avatar = document.querySelector(".avatar");
const avatarStateLabel = document.querySelector("#avatar-state-label");
const emotionLabel = document.querySelector("#emotion-label");
const currentDatetime = document.querySelector("#current-datetime");
const liveTranscript = document.querySelector("#live-transcript");
const liveTranscriptText = document.querySelector("#live-transcript-text");
const liveTranscriptHint = document.querySelector("#live-transcript-hint");

const PROCESS_STAGES = ["listening", "transcribing", "judging", "thinking", "synthesizing", "speaking"];
const EMOTION_LABELS = {
  neutral: "通常", happy: "嬉しい", excited: "興奮",
  thinking: "考え中", surprised: "驚き", concerned: "困り",
};
const EMOTIONS = new Set(Object.keys(EMOTION_LABELS));
const GESTURES = new Set(["nod", "tilt", "wave", "point", "cheer"]);
let speechPlaybackStartedAt = 0;
let gestureResetTimer = null;
let currentAnimation = { emotion: "happy", gesture: "wave", intensity: 0.65 };
let clockTimeZone = "Asia/Tokyo";
let clockOffsetMs = 0;

function updateCurrentDatetime() {
  if (!currentDatetime) return;
  const now = new Date(Date.now() + clockOffsetMs);
  const formatted = new Intl.DateTimeFormat("ja-JP", {
    timeZone: clockTimeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(now);
  currentDatetime.textContent = formatted;
  currentDatetime.dateTime = now.toISOString();
}

updateCurrentDatetime();
setInterval(updateCurrentDatetime, 1000);

function applyAnimation(animation = {}) {
  const emotion = EMOTIONS.has(animation.emotion) ? animation.emotion : "neutral";
  const gesture = GESTURES.has(animation.gesture) ? animation.gesture : "nod";
  const intensity = Math.min(1, Math.max(0.3, Number(animation.intensity) || 0.65));
  currentAnimation = { emotion, gesture, intensity };
  if (!identity) return;
  identity.dataset.emotion = emotion;
  if (emotionLabel) emotionLabel.textContent = EMOTION_LABELS[emotion];
  identity.style.setProperty("--gesture-offset", `${(intensity * 12).toFixed(1)}px`);
  identity.style.setProperty("--gesture-angle", `${(intensity * 3.2).toFixed(2)}deg`);
  identity.style.setProperty("--gesture-scale", (1 + intensity * 0.024).toFixed(3));
  delete identity.dataset.gesture;
  void identity.offsetWidth;
  identity.dataset.gesture = gesture;
  if (gestureResetTimer) clearTimeout(gestureResetTimer);
  gestureResetTimer = setTimeout(() => { delete identity.dataset.gesture; }, 2900);
}

function formatDuration(milliseconds) {
  if (!Number.isFinite(milliseconds)) return "--";
  if (milliseconds < 1000) return `${Math.round(milliseconds)}ms`;
  return `${(milliseconds / 1000).toFixed(milliseconds < 10000 ? 1 : 0)}s`;
}

function setStepDuration(stage, milliseconds) {
  const element = processDurations.get(stage);
  if (milliseconds === null || milliseconds === undefined || milliseconds === "") return;
  if (element && Number.isFinite(Number(milliseconds))) element.textContent = formatDuration(Number(milliseconds));
}

function resetStepDurations() {
  processDurations.forEach((element) => { element.textContent = "--"; });
}

function setProcessStage(stage, label, detail = "") {
  const stageIndex = PROCESS_STAGES.indexOf(stage);
  processMonitor.classList.toggle("is-running", stageIndex >= 0);
  processMonitor.classList.toggle("is-error", stage === "error");
  processNowLabel.textContent = label;
  processNowDetail.textContent = detail;
  if (identity) identity.dataset.state = stage;
  const avatarLabels = {
    idle: "STANDBY",
    listening: "LISTENING",
    transcribing: "TRANSCRIBING",
    judging: "CHECKING TURN",
    thinking: "THINKING",
    synthesizing: "VOICE READY",
    speaking: "SPEAKING",
    error: "ERROR",
  };
  if (avatarStateLabel) avatarStateLabel.textContent = avatarLabels[stage] || "STANDBY";
  processSteps.forEach((step, index) => {
    step.classList.toggle("is-active", index === stageIndex);
    step.classList.toggle("is-complete", stageIndex > index);
  });
  if (stageIndex >= 0) processSteps[stageIndex].scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
}

let personaName = "リク";
let providerReady = false;
let sttReady = false;
let busy = false;
let speechEnabled = true;
let voiceEngine = "browser";
let voiceLabel = "音声生成API";
let currentAudio = null;
let currentAudioUrl = "";
let speechResolver = null;
let speechSequenceId = 0;
let speechQueueId = 0;
let conversationActive = false;
let mediaStream = null;
let mediaRecorder = null;
let audioContext = null;
let analyser = null;
let levelData = null;
let audioChunks = [];
let vadTimer = null;
let recorderAction = "stop";
let noiseFloor = 0.008;
let calibrationUntil = 0;
let cycleStartedAt = 0;
let speechStartedAt = 0;
let lastVoiceAt = 0;
let voiceFrames = 0;
let pendingText = "";
let decisionInFlight = false;
let conversationHeartbeat = null;
let lipSyncContext = null;
let lipSyncSource = null;
let lipSyncAnalyser = null;
let lipSyncData = null;
let lipSyncFrame = null;
let syntheticLipTimer = null;
let smoothedMouthOpen = 0;

const AudioContextClass = window.AudioContext || window.webkitAudioContext;
const recorderSupported = Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder && AudioContextClass);
const CONTEXT_CHECK_INTERVAL_MS = 2400;
const MIN_CONTINUATION_SPEECH_MS = 180;

function updateLiveTranscript(text = "", state = "idle", hint = "") {
  if (!liveTranscript || !liveTranscriptText || !liveTranscriptHint) return;
  liveTranscript.classList.toggle("is-listening", state === "listening");
  liveTranscript.classList.toggle("is-finalizing", state === "finalizing");
  liveTranscriptText.textContent = text || "マイクで話すと、ここに認識中の内容が表示されます";
  liveTranscriptHint.textContent = hint || "話し終わりを検出すると自動で送信します";
}

function setMouthOpen(value) {
  const normalized = Math.min(1, Math.max(0, Number(value) || 0));
  document.querySelector(".avatar")?.style.setProperty("--mouth-open", normalized.toFixed(3));
}

function stopLipSync() {
  if (lipSyncFrame) cancelAnimationFrame(lipSyncFrame);
  if (syntheticLipTimer) clearInterval(syntheticLipTimer);
  lipSyncFrame = null;
  syntheticLipTimer = null;
  try { lipSyncSource?.disconnect(); } catch {}
  try { lipSyncAnalyser?.disconnect(); } catch {}
  lipSyncSource = null;
  lipSyncAnalyser = null;
  lipSyncData = null;
  smoothedMouthOpen = 0;
  setMouthOpen(0);
}

async function prepareAudioLipSync(audio) {
  stopLipSync();
  if (!AudioContextClass) return;
  if (!lipSyncContext || lipSyncContext.state === "closed") lipSyncContext = new AudioContextClass();
  if (lipSyncContext.state === "suspended") await lipSyncContext.resume();
  lipSyncSource = lipSyncContext.createMediaElementSource(audio);
  lipSyncAnalyser = lipSyncContext.createAnalyser();
  lipSyncAnalyser.fftSize = 256;
  lipSyncAnalyser.smoothingTimeConstant = 0.58;
  lipSyncData = new Uint8Array(lipSyncAnalyser.fftSize);
  lipSyncSource.connect(lipSyncAnalyser);
  lipSyncAnalyser.connect(lipSyncContext.destination);

  const updateMouth = () => {
    if (!lipSyncAnalyser) return;
    lipSyncAnalyser.getByteTimeDomainData(lipSyncData);
    let energy = 0;
    for (const sample of lipSyncData) {
      const centered = (sample - 128) / 128;
      energy += centered * centered;
    }
    const rms = Math.sqrt(energy / lipSyncData.length);
    const target = Math.min(1, Math.max(0, (rms - 0.012) * 13));
    smoothedMouthOpen = smoothedMouthOpen * 0.48 + target * 0.52;
    setMouthOpen(smoothedMouthOpen < 0.07 ? 0 : smoothedMouthOpen);
    lipSyncFrame = requestAnimationFrame(updateMouth);
  };
  updateMouth();
}

function startSyntheticLipSync() {
  stopLipSync();
  let phase = 0;
  syntheticLipTimer = setInterval(() => {
    phase += 1;
    const pause = phase % 9 === 0 || phase % 13 === 0;
    setMouthOpen(pause ? 0 : 0.28 + Math.random() * 0.72);
  }, 110);
}

function updateControls() {
  input.disabled = !providerReady;
  input.readOnly = conversationActive;
  submit.disabled = !providerReady || busy || conversationActive;
  input.placeholder = conversationActive ? "音声対話中です" : providerReady ? "文字でも話しかけられます" : "選択したAIの準備が必要です";
  startButton.disabled = !providerReady || !sttReady || !recorderSupported || conversationActive || busy;
  stopButton.disabled = !conversationActive;
}

function reportConversationState(active) {
  fetch("/api/conversation-state", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active }),
    keepalive: true,
  }).catch(() => {});
}

function startConversationHeartbeat() {
  if (conversationHeartbeat) clearInterval(conversationHeartbeat);
  reportConversationState(true);
  conversationHeartbeat = setInterval(() => reportConversationState(true), 8000);
}

function stopConversationHeartbeat() {
  if (conversationHeartbeat) clearInterval(conversationHeartbeat);
  conversationHeartbeat = null;
  reportConversationState(false);
}

function applyProviderStatus(data) {
  providerReady = data.ready;
  status.classList.toggle("ready", data.ready);
  status.querySelector("span").textContent = data.ready ? `${data.model} / 会話できます` : "準備が必要です";
  updateControls();
  if (!data.ready && data.reason) addMessage("ai", data.reason);
}

function finishSpeechPlayback(continueSequence = false) {
  if (speechPlaybackStartedAt) setStepDuration("speaking", performance.now() - speechPlaybackStartedAt);
  speechPlaybackStartedAt = 0;
  stopLipSync();
  identity?.classList.remove("speaking");
  if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
  currentAudioUrl = "";
  currentAudio = null;
  const resolve = speechResolver;
  speechResolver = null;
  if (!continueSequence) {
    if (conversationActive) setProcessStage("listening", "聞いています", "次の発言を待っています");
    else setProcessStage("idle", "待機中", "対話スタートを待っています");
  }
  if (resolve) resolve();
}

function stopVoice() {
  speechQueueId += 1;
  speechSequenceId += 1;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
  }
  finishSpeechPlayback();
}

function browserSpeak(text) {
  return new Promise((resolve) => {
    if (!speechEnabled || !("speechSynthesis" in window)) {
      resolve();
      return;
    }
    speechResolver = resolve;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "ja-JP";
    const browserVoiceProfiles = {
      neutral: [1.02, 1.04], happy: [1.06, 1.1], excited: [1.13, 1.16],
      thinking: [0.95, 1.0], surprised: [1.09, 1.18], concerned: [0.93, 0.96],
    };
    [utterance.rate, utterance.pitch] = browserVoiceProfiles[currentAnimation.emotion] || browserVoiceProfiles.neutral;
    const voices = window.speechSynthesis.getVoices();
    utterance.voice = voices.find((voice) => voice.lang.toLowerCase().startsWith("ja")) || null;
    utterance.onstart = () => {
      speechPlaybackStartedAt = performance.now();
      identity?.classList.add("speaking");
      voiceState.textContent = `${personaName}が話しています`;
      setProcessStage("speaking", "話しています", "ブラウザ音声を再生中");
      startSyntheticLipSync();
    };
    utterance.onend = utterance.onerror = finishSpeechPlayback;
    window.speechSynthesis.speak(utterance);
  });
}

function splitSpeechChunks(text, maxLength = 64) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  if (!normalized) return [];
  const sentences = normalized.match(/[^。！？!?]+[。！？!?]+|[^。！？!?]+$/g) || [normalized];
  const chunks = [];
  for (const sentence of sentences) {
    if (sentence.length <= maxLength) {
      chunks.push(sentence.trim());
      continue;
    }
    const clauses = sentence.match(/[^、，,；;：:]+[、，,；;：:]?|[、，,；;：:]+/g) || [sentence];
    let current = "";
    for (const clause of clauses) {
      let remaining = clause;
      while (remaining.length > maxLength) {
        if (current) {
          chunks.push(current.trim());
          current = "";
        }
        chunks.push(remaining.slice(0, maxLength).trim());
        remaining = remaining.slice(maxLength);
      }
      if (current && current.length + remaining.length > maxLength) {
        chunks.push(current.trim());
        current = "";
      }
      current += remaining;
    }
    if (current.trim()) chunks.push(current.trim());
  }
  return chunks.filter(Boolean);
}

async function synthesizeSpeechChunk(text) {
  const attempts = [
    text,
    text.replace(/[、，,；;：:]/g, "。").replace(/[「」『』（）()【】]/g, ""),
  ].filter((value, index, values) => value && values.indexOf(value) === index);
  let lastError = "";
  for (const candidate of attempts) {
    const response = await fetch("/api/voice", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: candidate, emotion: currentAnimation.emotion, intensity: currentAnimation.intensity }),
    });
    if (response.ok) {
      return {
        blob: await response.blob(),
        durationMs: Number(response.headers.get("X-Process-Duration-Ms")) || 0,
      };
    }
    try { lastError = (await response.json()).error || lastError; } catch {}
  }
  throw new Error(lastError || `${voiceLabel}の音声を生成できませんでした`);
}

async function playSpeechChunk(blob, chunkNumber, chunkCount) {
  currentAudioUrl = URL.createObjectURL(blob);
  currentAudio = new Audio(currentAudioUrl);
  try {
    await prepareAudioLipSync(currentAudio);
  } catch {
    startSyntheticLipSync();
  }
  await new Promise((resolve, reject) => {
    speechResolver = resolve;
    currentAudio.onplay = () => {
      speechPlaybackStartedAt = performance.now();
      identity?.classList.add("speaking");
      voiceState.textContent = `${personaName}が${voiceLabel}で話しています（${chunkNumber}/${chunkCount}）`;
      setProcessStage("speaking", "話しています", `短い文を順番に再生中 ${chunkNumber}/${chunkCount}`);
    };
    currentAudio.onended = () => finishSpeechPlayback(true);
    currentAudio.onerror = () => {
      speechResolver = null;
      finishSpeechPlayback(true);
      reject(new Error("生成した音声を再生できませんでした"));
    };
    currentAudio.play().catch((error) => {
      speechResolver = null;
      finishSpeechPlayback(true);
      reject(error);
    });
  });
}

async function prepareSpeechSegment(text) {
  if (!speechEnabled) return { engine: "silent", text, parts: [] };
  if (!new Set(["voicevox", "aivisspeech", "coeiroink"]).has(voiceEngine)) {
    return { engine: "browser", text, parts: [] };
  }
  const chunks = splitSpeechChunks(text, 42);
  const parts = [];
  let durationMs = 0;
  for (let index = 0; index < chunks.length; index += 1) {
    voiceState.textContent = `${voiceLabel}で次の音声を先に作っています`;
    setProcessStage("synthesizing", "次の音声を準備中", `再生と並行して句を生成中 ${index + 1}/${chunks.length}`);
    const synthesized = await synthesizeSpeechChunk(chunks[index]);
    durationMs += synthesized.durationMs;
    parts.push(synthesized.blob);
  }
  setStepDuration("synthesizing", durationMs);
  return { engine: "local", text, parts };
}

async function playPreparedSpeechSegment(prepared) {
  if (!speechEnabled || prepared.engine === "silent") return;
  if (prepared.engine === "browser") {
    await browserSpeak(prepared.text);
    return;
  }
  for (let index = 0; index < prepared.parts.length; index += 1) {
    if (!speechEnabled) return;
    await playSpeechChunk(prepared.parts[index], index + 1, prepared.parts.length);
  }
  finishSpeechPlayback();
}

function preferredAudioType() {
  return ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]
    .find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function rmsLevel() {
  analyser.getFloatTimeDomainData(levelData);
  let sum = 0;
  for (const sample of levelData) sum += sample * sample;
  return Math.sqrt(sum / levelData.length);
}

function clearListeningTimers() {
  if (vadTimer) clearInterval(vadTimer);
  vadTimer = null;
}

function stopRecording(action) {
  clearListeningTimers();
  recorderAction = action;
  if (mediaRecorder?.state === "recording") mediaRecorder.stop();
}

function joinedTranscript(existing, addition) {
  const first = String(existing || "").trim();
  const second = String(addition || "").trim();
  if (!first) return second;
  if (!second || first === second) return first;
  if (second.startsWith(first)) return second;
  if (first.endsWith(second)) return first;
  return `${first}${/[。！？!?]$/.test(first) ? "" : "、"}${second}`;
}

function quickTurnDecision(text) {
  const normalized = String(text || "").replace(/\s+/g, "").trim();
  if (!normalized) return false;
  if (/[！？!?]$/.test(normalized)) return true;
  const stem = normalized.replace(/[。！？!?]+$/, "");
  if (new Set(["はい", "いいえ", "うん", "いや", "ありがとう", "お願い", "やめて",
               "こんにちは", "おはよう", "こんばんは", "おやすみ"]).has(stem)) return true;
  if ([
    "教えて", "案内して", "どこ", "いつ", "何時", "ある", "ない", "できる",
    "買える", "行ける", "おすすめ", "オススメ", "知りたい", "お願い",
  ].some((ending) => stem.endsWith(ending))) return true;
  if ([
    "けど", "けれど", "けれども", "から", "ので", "て", "で", "し", "たり",
    "というか", "というより", "言い直すと", "えっと", "あの", "その", "それで", "あと", "例えば",
    "について", "は", "が", "を", "に", "へ", "と", "も", "の",
  ].some((ending) => stem.endsWith(ending))) return false;
  if (/[。]$/.test(normalized)) return true;
  return null;
}

function watchVoice() {
  const now = performance.now();
  const level = rmsLevel();
  if (now < calibrationUntil) {
    noiseFloor = noiseFloor * 0.85 + level * 0.15;
    voiceState.textContent = "周囲の音を確認中…";
    setProcessStage("listening", "マイクを調整中", "周囲の音量を確認しています");
    return;
  }
  const threshold = Math.max(0.008, noiseFloor * 2.2);
  if (level > threshold) {
    voiceFrames += 1;
    lastVoiceAt = now;
    if (!speechStartedAt && voiceFrames >= 3) {
      speechStartedAt = now;
      voiceState.textContent = pendingText ? "続きを聞いています…" : "聞いています…";
      setProcessStage("listening", "聞いています", "声をリアルタイムで収集中");
      updateLiveTranscript(input.value, "listening", "認識しながら聞いています");
      startButton.classList.add("listening");
    }
  } else {
    voiceFrames = 0;
    if (!speechStartedAt) noiseFloor = noiseFloor * 0.995 + level * 0.005;
  }
  if (!decisionInFlight && now - cycleStartedAt >= CONTEXT_CHECK_INTERVAL_MS && audioChunks.length) {
    if (speechStartedAt) {
      setStepDuration("listening", now - speechStartedAt);
      startButton.classList.remove("listening");
      stopRecording("analyze");
    } else {
      stopRecording("restart");
    }
  }
}

function beginListeningCycle(calibrate = false) {
  if (!conversationActive || busy || !mediaStream) return;
  audioChunks = [];
  speechStartedAt = 0;
  lastVoiceAt = 0;
  voiceFrames = 0;
  cycleStartedAt = performance.now();
  calibrationUntil = calibrate ? cycleStartedAt + 1000 : 0;
  const mimeType = preferredAudioType();
  const recorder = new MediaRecorder(mediaStream, mimeType ? { mimeType } : undefined);
  mediaRecorder = recorder;
  recorder.ondataavailable = (event) => {
    if (event.data.size) audioChunks.push(event.data);
  };
  recorder.onstop = async () => {
    const action = recorderAction;
    const completedAudio = new Blob([...audioChunks], { type: recorder.mimeType || "audio/webm" });
    audioChunks = [];
    if (!conversationActive || action === "stop") return;
    if (action === "restart") {
      beginListeningCycle();
      return;
    }
    if (action === "finalize") await answerToPendingText();
    if (action === "discard") return;
    if (action === "analyze") {
      beginListeningCycle();
      await analyzeRecordedTurn(completedAudio);
    }
  };
  recorder.onerror = () => {
    voiceState.textContent = "録音に失敗しました。対話を再スタートしてください";
    setProcessStage("error", "録音エラー", "対話を再スタートしてください");
    stopConversation();
  };
  recorderAction = "stop";
  recorder.start(250);
  voiceState.textContent = calibrate ? "周囲の音を確認中…" : pendingText ? "続きを待っています…" : "話しかけてください";
  setProcessStage("listening", calibrate ? "マイクを調整中" : "聞いています", pendingText ? "発言の続きを待っています" : "話しかけてください");
  vadTimer = setInterval(watchVoice, 50);
}

async function startConversation() {
  if (conversationActive || busy) return;
  stopVoice();
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    audioContext = new AudioContextClass();
    const source = audioContext.createMediaStreamSource(mediaStream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024;
    levelData = new Float32Array(analyser.fftSize);
    source.connect(analyser);
    pendingText = "";
    conversationActive = true;
    updateLiveTranscript("", "listening", "話しかけてください。区切りを検出すると自動送信します");
    startConversationHeartbeat();
    updateControls();
    beginListeningCycle(true);
  } catch (error) {
    voiceState.textContent = error.name === "NotAllowedError" ? "マイクの使用を許可してください" : "マイクを開始できませんでした";
    setProcessStage("error", "マイクを開始できません", "ブラウザのマイク許可を確認してください");
    stopConversation();
  }
}

function stopConversation() {
  conversationActive = false;
  stopConversationHeartbeat();
  pendingText = "";
  updateLiveTranscript("", "idle", "対話スタートを押すと文字起こしを始めます");
  startButton.classList.remove("listening");
  stopRecording("stop");
  stopVoice();
  if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
  mediaStream = null;
  if (audioContext) audioContext.close();
  audioContext = null;
  analyser = null;
  voiceState.textContent = "対話を停止しました";
  setProcessStage("idle", "停止中", "対話スタートを待っています");
  updateControls();
}

async function analyzeRecordedTurn(blob) {
  if (decisionInFlight || !conversationActive || !blob.size) {
    if (conversationActive && (!mediaRecorder || mediaRecorder.state !== "recording")) beginListeningCycle();
    return;
  }
  decisionInFlight = true;
  voiceState.textContent = "文字起こしと発話の区切りを確認中…";
  setProcessStage("transcribing", "文字にしています", "faster-whisperで発言全体を認識中");
  try {
    const response = await fetch("/api/analyze-turn", {
      method: "POST",
      headers: { "Content-Type": blob.type || "audio/webm" },
      body: blob,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "発話判定に失敗しました");
    if (!conversationActive) return;
    pendingText = joinedTranscript(pendingText, data.text);
    setStepDuration("transcribing", data.timings?.transcribing);
    setStepDuration("judging", data.timings?.judging);
    input.value = pendingText;
    if (!pendingText) {
      voiceState.textContent = "話しかけてください";
      setProcessStage("listening", "聞いています", "発言を待っています");
      updateLiveTranscript("", "listening", "話した内容の文脈から区切りを判断します");
      return;
    }
    updateLiveTranscript(pendingText, "finalizing", "発言が意味として完結したか判断しています…");
    setProcessStage("judging", "文脈を判定中", "会話履歴と発言内容から話し終わりを判断しています");
    const audioComplete = Boolean(data.complete);
    const quickDecision = quickTurnDecision(pendingText);
    let contextComplete = quickDecision ?? audioComplete;
    if (quickDecision === null) {
      try {
        const turnState = await api("/api/turn-state", { text: pendingText });
        contextComplete = Boolean(turnState.complete);
        setStepDuration("judging", turnState.timings?.judging ?? data.timings?.judging);
      } catch {
        // Smart Turnの音声文脈判定をフォールバックとして使う。
      }
    }
    if (!conversationActive) return;
    const userContinuedSpeaking = Boolean(
      speechStartedAt && lastVoiceAt - speechStartedAt >= MIN_CONTINUATION_SPEECH_MS
    );
    if (contextComplete && !userContinuedSpeaking) {
      stopRecording("discard");
      decisionInFlight = false;
      await answerToPendingText();
      return;
    }
    voiceState.textContent = "まだ発言の途中です。続きを待っています…";
    setProcessStage(
      "listening",
      userContinuedSpeaking ? "続きを聞いています" : "続きを待っています",
      userContinuedSpeaking ? "話し続けているため送信を待っています" : "まだ発言の途中と判断しました",
    );
    updateLiveTranscript(pendingText, "listening", "続きを話してください。意味が完結すると自動送信します");
    decisionInFlight = false;
  } catch (error) {
    voiceState.textContent = error.message;
    setProcessStage("error", "判定でエラー", error.message);
    decisionInFlight = false;
    if (!mediaRecorder || mediaRecorder.state !== "recording") beginListeningCycle();
  } finally {
    decisionInFlight = false;
  }
}

async function answerToPendingText() {
  const text = pendingText.trim();
  pendingText = "";
  if (!text) {
    busy = false;
    if (conversationActive) beginListeningCycle();
    return;
  }
  busy = false;
  updateLiveTranscript(text, "finalizing", "区切りを検出しました。自動送信しています…");
  await sendMessage(text);
  updateLiveTranscript("", conversationActive ? "listening" : "idle", conversationActive ? "次の発言を待っています" : "対話スタートを押してください");
  if (conversationActive) beginListeningCycle();
}

function addGuideCards(article, guideCards = []) {
  if (Array.isArray(guideCards) && guideCards.length && !article.querySelector(".guide-card-gallery")) {
    const gallery = document.createElement("div");
    gallery.className = "guide-card-gallery";
    gallery.setAttribute("aria-label", "パンフレット案内カード");
    const revealAnswer = () => {
      messages.scrollTop = Math.max(0, article.offsetTop - messages.offsetTop - 8);
    };
    for (const card of guideCards.slice(0, 3)) {
      if (!card?.imageUrl) continue;
      const figure = document.createElement("figure");
      figure.className = "guide-card";
      const image = document.createElement("img");
      image.src = card.imageUrl;
      image.alt = card.alt || "パンフレット案内カード";
      image.loading = "lazy";
      image.decoding = "async";
      image.addEventListener("load", revealAnswer, { once: true });
      figure.append(image);
      gallery.append(figure);
    }
    if (gallery.childElementCount) {
      article.append(gallery);
      requestAnimationFrame(revealAnswer);
    }
  }
}

function addMessage(role, text, extraClass = "", guideCards = []) {
  const article = document.createElement("article");
  article.className = `message ${role} ${extraClass}`;
  const speaker = document.createElement("span");
  speaker.className = "speaker";
  speaker.textContent = role === "ai" ? personaName : "あなた";
  const body = document.createElement("p");
  body.textContent = text;
  article.append(speaker, body);
  if (role === "ai") addGuideCards(article, guideCards);
  messages.append(article);
  messages.scrollTop = messages.scrollHeight;
  return article;
}

function addSources(article, evidence) {
  if (!evidence.sources?.length) return;
  const references = document.createElement('div');
  references.className = 'answer-sources';
  evidence.sources.forEach((source, index) => {
    try {
      const url = new URL(source.url);
      if (!['https:', 'http:'].includes(url.protocol)) return;
      const link = document.createElement('a');
      link.href = url.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = `[${index + 1}] ${source.title}`;
      references.append(link, document.createElement('br'));
    } catch {}
  });
  if (evidence.retrievedAt) references.append(document.createTextNode('取得：' + new Date(evidence.retrievedAt).toLocaleString('ja-JP')));
  article.append(references);
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "通信に失敗しました。");
  return data;
}

async function streamChat(message, onEvent) {
  const response = await fetch("/api/chat-stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) {
    let detail = "";
    try { detail = (await response.json()).error || ""; } catch {}
    throw new Error(detail || "AIへ接続できませんでした。");
  }
  if (!response.body) throw new Error("このブラウザーは回答ストリーミングに対応していません。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const dispatchLines = () => {
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line));
    }
  };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    dispatchLines();
  }
  buffer += decoder.decode();
  if (buffer.trim()) onEvent(JSON.parse(buffer));
}

function createStreamingSpeechQueue() {
  const queueId = ++speechQueueId;
  let pending = "";
  let synthesisChain = Promise.resolve();
  let playbackChain = Promise.resolve();
  const enqueue = (phrase) => {
    const clean = phrase.trim();
    if (!clean) return;
    const prepared = synthesisChain.then(() => (
      queueId === speechQueueId ? prepareSpeechSegment(clean) : null
    ));
    synthesisChain = prepared.catch(() => null);
    playbackChain = playbackChain.then(async () => {
      const item = await prepared;
      if (item && queueId === speechQueueId) await playPreparedSpeechSegment(item);
    });
  };
  const push = (text) => {
    pending += text;
    while (true) {
      const strongBreak = pending.search(/[。！？!?]/);
      const softBreaks = [...pending.matchAll(/[、，,；;：:]/g)];
      const softBreak = softBreaks.find((match) => match.index >= 10)?.index ?? -1;
      let breakAt = strongBreak;
      if (softBreak >= 0 && (breakAt < 0 || softBreak < breakAt)) breakAt = softBreak;
      if (breakAt < 0 && pending.length < 36) break;
      if (breakAt < 0 || breakAt >= 42) breakAt = 35;
      enqueue(pending.slice(0, breakAt + 1));
      pending = pending.slice(breakAt + 1);
    }
  };
  return {
    push,
    finish(extra = "") {
      push(extra);
      enqueue(pending);
      pending = "";
      return playbackChain;
    },
  };
}

async function sendMessage(text) {
  if (!text.trim() || !providerReady) return;
  addMessage("user", text);
  input.value = "";
  busy = true;
  updateControls();
  voiceState.textContent = `${personaName}が考えています…`;
  setProcessStage("thinking", "返事を考えています", "対話AIが内容を理解して回答を作成中");
  applyAnimation({ emotion: "thinking", gesture: "tilt", intensity: 0.55 });
  const thinking = addMessage("ai", "考え中…", "thinking");
  const answerBody = thinking.querySelector("p");
  const speechQueue = createStreamingSpeechQueue();
  let streamedAnswer = "";
  let finalEvent = null;
  try {
    await streamChat(text, (event) => {
      if (event.type === 'status') {
        answerBody.textContent = event.text;
        setProcessStage('thinking', event.text, '');
      } else if (event.type === "animation") {
        applyAnimation(event.animation);
      } else if (event.type === "delta") {
        if (!streamedAnswer) {
          thinking.classList.remove("thinking");
          answerBody.textContent = "";
        }
        streamedAnswer += event.text;
        answerBody.textContent = streamedAnswer;
        messages.scrollTop = messages.scrollHeight;
        speechQueue.push(event.text);
      } else if (event.type === "done") {
        finalEvent = event;
      } else if (event.type === "error") {
        throw new Error(event.error || "回答の生成中にエラーが発生しました。");
      }
    });
    if (!finalEvent) throw new Error("AIの回答が途中で終了しました。");
    if (finalEvent.memoriesChanged) await Promise.all([loadMemories(), loadMemoryProposal()]);
    if (finalEvent.proposalResolved) renderMemoryProposal(null);
    if (finalEvent.memoryProposal) renderMemoryProposal(finalEvent.memoryProposal);
    thinking.classList.remove("thinking");
    answerBody.textContent = finalEvent.answer;
    applyAnimation(finalEvent.animation);
    addGuideCards(thinking, finalEvent.guideCards);
    if (finalEvent.sources?.length) {
      const references = document.createElement('div');
      references.className = 'answer-sources';
      finalEvent.sources.forEach((source, index) => {
        try {
          const url = new URL(source.url);
          if (!['https:', 'http:'].includes(url.protocol)) return;
          const link = document.createElement('a');
          link.href = url.href;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          link.textContent = `[${index + 1}] ${source.title}`;
          references.append(link, document.createElement('br'));
        } catch {}
      });
      if (finalEvent.retrievedAt) references.append(document.createTextNode('取得：' + new Date(finalEvent.retrievedAt).toLocaleString('ja-JP')));
      thinking.append(references);
    }
    setStepDuration("thinking", finalEvent.timings?.firstToken || finalEvent.timings?.thinking);
    const additionalText = finalEvent.answer.startsWith(streamedAnswer)
      ? finalEvent.answer.slice(streamedAnswer.length)
      : streamedAnswer ? "" : finalEvent.answer;
    await speechQueue.finish(additionalText);
  } catch (error) {
    thinking.remove();
    addMessage("ai", error.message);
    setProcessStage("error", "応答エラー", error.message);
  } finally {
    busy = false;
    updateControls();
  }
}

async function bootstrap() {
  try {
    const data = await api("/api/bootstrap");
    personaName = data.name;
    if (data.history?.length) {
      messages.replaceChildren();
      for (const item of data.history) {
        const article = addMessage(item.role === 'assistant' ? 'ai' : 'user', item.content);
        addSources(article, item);
      }
    }
    await loadMemories();
    await loadMemoryProposal();
    await loadThemes();
    await loadAccount();
    if (data.clock?.timeZone) clockTimeZone = data.clock.timeZone;
    if (data.clock?.serverNow) {
      const serverNow = Date.parse(data.clock.serverNow);
      if (Number.isFinite(serverNow)) clockOffsetMs = serverNow - Date.now();
    }
    updateCurrentDatetime();
    voiceEngine = data.voice?.engine || "browser";
    voiceLabel = data.voice?.label || "音声生成API";
    if (voiceEngineName) voiceEngineName.textContent = voiceEngine === "browser" ? "ブラウザ音声" : voiceLabel;
    sttReady = Boolean(data.stt?.ready && data.turnDetection?.ready);
    document.querySelector("#title").textContent = data.title;
    const personaNameElement = document.querySelector("#persona-name");
    const avatarLetterElement = document.querySelector("#avatar-letter");
    if (personaNameElement) personaNameElement.textContent = personaName;
    if (avatarLetterElement) avatarLetterElement.textContent = personaName.slice(0, 1);
    provider.replaceChildren();
    for (const item of data.providers) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = `${item.label} / ${item.model}${item.ready ? "" : "（未準備）"}`;
      option.selected = item.id === data.provider;
      provider.append(option);
    }
    applyProviderStatus({ ...data.providers.find((item) => item.id === data.provider), reason: data.setupIssue });
    speakerToggle.title = data.voice?.ready ? `${voiceLabel} ${data.voice.version}` : data.voice?.reason || "ブラウザ音声を使用します";
    startButton.title = sttReady ? `faster-whisper ${data.stt.model} / ${data.turnDetection.model}` : data.stt?.reason || data.turnDetection?.reason || "音声入力は準備中です";
    voiceState.textContent = sttReady ? "対話スタートを押すと、発言の区切りを自動判断します" : data.stt?.reason || "音声入力は準備中です";
    setProcessStage("idle", "待機中", sttReady ? "対話スタートを待っています" : "音声入力を準備できませんでした");
    for (const text of data.suggestions) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = text;
      button.addEventListener("click", () => { input.value = text; input.focus(); });
      suggestions.append(button);
    }
    if (!data.guide?.ready) {
      addMessage("ai", data.guide?.reason || "パンフレット案内を準備できていません。受付か公式サイトで確認してください。");
    }
    updateControls();
  } catch {
    status.querySelector("span").textContent = "接続できません";
    setProcessStage("error", "接続できません", "サーバーとの接続を確認してください");
  }
}

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const text = input.value.trim();
  if (!text) return;
  if (conversationActive) stopRecording("stop");
  await sendMessage(text);
  if (conversationActive) beginListeningCycle();
});

startButton.addEventListener("click", startConversation);
stopButton.addEventListener("click", stopConversation);

speakerToggle.addEventListener("click", () => {
  speechEnabled = !speechEnabled;
  speakerToggle.setAttribute("aria-pressed", String(speechEnabled));
  speakerToggle.innerHTML = `<span aria-hidden="true">◉</span> 読み上げ ${speechEnabled ? "ON" : "OFF"}`;
  if (!speechEnabled) stopVoice();
});

provider.addEventListener("change", async () => {
  stopConversation();
  provider.disabled = true;
  try {
    const data = await api("/api/provider", { provider: provider.value });
    messages.replaceChildren();
    resetStepDurations();
    addMessage("ai", `接続先を${data.label}に切り替えた。ここから新しい会話だ！`);
    applyAnimation({ emotion: "excited", gesture: "cheer", intensity: 0.72 });
    applyProviderStatus(data);
  } catch (error) {
    addMessage("ai", error.message);
  } finally {
    provider.disabled = false;
  }
});

reset.addEventListener("click", async () => {
  stopConversation();
  reset.disabled = true;
  try {
    await api("/api/reset", {});
    messages.replaceChildren();
    resetStepDurations();
    addMessage("ai", "ここから新しい会話にしよう。今日あったことでも、考えていることでも聞かせて。");
    applyAnimation({ emotion: "happy", gesture: "wave", intensity: 0.72 });
  } catch (error) {
    addMessage("ai", error.message);
  } finally {
    reset.disabled = false;
  }
});

if (!recorderSupported) voiceState.textContent = "このブラウザは連続音声対話に対応していません";
avatarImage?.addEventListener("error", () => avatarImage.classList.add("is-missing"));
if (identity && avatar && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
  const scheduleBlink = () => {
    window.setTimeout(() => {
      if (!document.hidden) {
        avatar.classList.add("is-blinking");
        window.setTimeout(() => avatar.classList.remove("is-blinking"), 170);
      }
      scheduleBlink();
    }, 2600 + Math.random() * 3500);
  };
  scheduleBlink();

  identity.addEventListener("pointermove", (event) => {
    if (event.pointerType === "touch") return;
    const bounds = identity.getBoundingClientRect();
    const x = (event.clientX - bounds.left) / bounds.width - 0.5;
    const y = (event.clientY - bounds.top) / bounds.height - 0.5;
    identity.style.setProperty("--look-x", `${(x * 12).toFixed(1)}px`);
    identity.style.setProperty("--look-y", `${(y * 8).toFixed(1)}px`);
    identity.style.setProperty("--look-angle", `${(x * 1.3).toFixed(2)}deg`);
  });
  identity.addEventListener("pointerleave", () => {
    identity.style.setProperty("--look-x", "0px");
    identity.style.setProperty("--look-y", "0px");
    identity.style.setProperty("--look-angle", "0deg");
  });
}
window.addEventListener("pagehide", () => {
  if (!conversationActive) return;
  const payload = new Blob([JSON.stringify({ active: false })], { type: "application/json" });
  navigator.sendBeacon("/api/conversation-state", payload);
});
applyAnimation(currentAnimation);
let currentMemoryProposal = null;
function renderMemoryProposal(proposal) {
  currentMemoryProposal = proposal;
  const panel = document.querySelector('#memory-proposal');
  panel.hidden = !proposal;
  if (proposal) document.querySelector('#memory-proposal-content').value = proposal.content;
  document.querySelector('#memory-proposal-status').textContent = '';
}
async function loadMemoryProposal() {
  try { renderMemoryProposal((await api('/api/memory-proposals')).proposal); }
  catch (error) { document.querySelector('#memory-proposal-status').textContent = error.message; }
}
async function resolveMemoryProposal(action) {
  if (!currentMemoryProposal) return;
  const body = {id:currentMemoryProposal.id, action};
  if (action === 'save') body.content = document.querySelector('#memory-proposal-content').value;
  for (const button of document.querySelectorAll('#memory-proposal button')) button.disabled = true;
  try {
    const result = await api('/api/memory-proposals', body);
    renderMemoryProposal(result.proposal);
    if (result.saved) renderMemories(result.memories);
    document.querySelector('#memory-status').textContent = result.saved ? '確認した内容を記憶しました。' : 'この提案は保存しませんでした。';
  } catch (error) { document.querySelector('#memory-proposal-status').textContent = error.message; }
  finally { for (const button of document.querySelectorAll('#memory-proposal button')) button.disabled = false; }
}
document.querySelector('#memory-proposal-save').addEventListener('click', () => resolveMemoryProposal('save'));
document.querySelector('#memory-proposal-dismiss').addEventListener('click', () => resolveMemoryProposal('dismiss'));
async function loadMemories() {
  try { renderMemories((await api('/api/memories')).memories); }
  catch (error) { document.querySelector('#memory-status').textContent = error.message; }
}

function renderMemories(items) {
  const list = document.querySelector('#memory-list');
  list.replaceChildren();
  for (const item of items) {
    const row = document.createElement('div');
    const field = document.createElement('textarea');
    field.value = item.content;
    field.maxLength = 2000;
    field.setAttribute('aria-label', '保存済みの記憶');
    const save = document.createElement('button');
    save.textContent = '変更を保存';
    const remove = document.createElement('button');
    remove.textContent = '削除';
    async function change(payload) {
      save.disabled = remove.disabled = true;
      try {
        renderMemories((await api('/api/memories', payload)).memories);
        document.querySelector('#memory-status').textContent = payload.action === 'delete' ? '記憶を削除しました。' : '記憶を更新しました。';
      } catch (error) {
        document.querySelector('#memory-status').textContent = error.message;
        save.disabled = remove.disabled = false;
      }
    }
    save.onclick = () => change({id:item.id, content:field.value});
    remove.onclick = () => { if (confirm('この記憶を削除しますか？')) change({id:item.id, action:'delete'}); };
    row.append(field, save, remove);
    list.append(row);
  }
  if (!items.length) list.textContent = '保存された記憶はまだありません。';
}
document.querySelector('#memory-form').addEventListener('submit', async event => {
  event.preventDefault();
  const field = document.querySelector('#memory-content');
  const button = event.target.querySelector('button');
  button.disabled = true;
  try {
    renderMemories((await api('/api/memories', {content:field.value})).memories);
    field.value = '';
    document.querySelector('#memory-status').textContent = '記憶を保存しました。';
  } catch (error) { document.querySelector('#memory-status').textContent = error.message; }
  finally { button.disabled = false; }
});
let savedThemes = [];
const themeSelect = document.querySelector('#theme-select');
const themeStatus = document.querySelector('#theme-status');
const themeFields = {title:'#theme-title', goal:'#theme-goal', options:'#theme-options', open_questions:'#theme-open', decisions:'#theme-decisions'};
function selectedThemeId() { return Number(themeSelect.value) || null; }
function fillTheme(theme) {
  for (const [key, selector] of Object.entries(themeFields)) document.querySelector(selector).value = theme?.[key] || '';
}
function renderThemes(data, selectedId = data.selectedId ?? data.activeThemeId) {
  savedThemes = data.themes;
  themeSelect.replaceChildren(new Option('新しいテーマ', ''));
  for (const theme of savedThemes) themeSelect.add(new Option(theme.title, String(theme.id)));
  themeSelect.value = selectedId && savedThemes.some(item => item.id === selectedId) ? String(selectedId) : '';
  fillTheme(savedThemes.find(item => item.id === selectedThemeId()));
  document.querySelector('#theme-save').textContent = selectedThemeId() ? 'テーマを保存' : 'このテーマで相談を始める';
  const active = savedThemes.find(item => item.id === data.activeThemeId);
  document.querySelector('#active-theme-label').textContent = active ? `（続き：${active.title}）` : '（選択なし）';
}
async function loadThemes() {
  try { renderThemes(await api('/api/themes')); }
  catch (error) { themeStatus.textContent = error.message; }
}
themeSelect.addEventListener('change', () => {
  fillTheme(savedThemes.find(item => item.id === selectedThemeId()));
  document.querySelector('#theme-save').textContent = selectedThemeId() ? 'テーマを保存' : 'このテーマで相談を始める';
});
document.querySelector('#theme-form').addEventListener('submit', async event => {
  event.preventDefault();
  const body = {id:selectedThemeId()};
  for (const [key, selector] of Object.entries(themeFields)) body[key] = document.querySelector(selector).value;
  try {
    renderThemes(await api('/api/themes', body));
    themeStatus.textContent = 'テーマを保存しました。';
  } catch (error) { themeStatus.textContent = error.message; }
});
document.querySelector('#theme-draft').addEventListener('click', async event => {
  const button = event.currentTarget;
  if (Object.values(themeFields).some(selector => document.querySelector(selector).value.trim()) &&
      !confirm('入力中の内容を会話から作った下書きで置き換えますか？')) return;
  button.disabled = true;
  themeStatus.textContent = '会話を整理しています…';
  try {
    const result = await api('/api/themes/draft', {id:selectedThemeId()});
    fillTheme(result.draft);
    themeStatus.textContent = '下書きを表示しました。内容を確認・修正し、「テーマを保存」で確定してください。';
  } catch (error) { themeStatus.textContent = error.message; }
  finally { button.disabled = false; }
});
document.querySelector('#theme-activate').addEventListener('click', async () => {
  if (!selectedThemeId()) { themeStatus.textContent = '先にテーマを保存してください。'; return; }
  try {
    renderThemes(await api('/api/themes', {action:'select', id:selectedThemeId()}), selectedThemeId());
    themeStatus.textContent = '次の会話から、このテーマの続きを話せます。';
  } catch (error) { themeStatus.textContent = error.message; }
});
document.querySelector('#theme-clear').addEventListener('click', async () => {
  try {
    const selected = selectedThemeId();
    renderThemes(await api('/api/themes', {action:'select', id:null}), selected);
    themeStatus.textContent = '相談テーマを会話から外しました。';
  } catch (error) { themeStatus.textContent = error.message; }
});
document.querySelector('#theme-delete').addEventListener('click', async () => {
  const id = selectedThemeId();
  if (!id || !confirm('この相談テーマを削除しますか？')) return;
  try {
    renderThemes(await api('/api/themes', {action:'delete', id}));
    themeStatus.textContent = 'テーマを削除しました。';
  } catch (error) { themeStatus.textContent = error.message; }
});
let accountCounts = {messages:0, memories:0, themes:0};
const accountStatus = document.querySelector('#account-status');
function describeCounts(counts) {
  return `会話${counts.messages}件・記憶${counts.memories}件・相談テーマ${counts.themes}件`;
}
async function loadAccount() {
  try {
    const data = await api('/api/account');
    accountCounts = data.localCounts;
    document.querySelector('#account-label').textContent = data.signedIn ? `（${data.username}）` : '（未ログイン）';
    document.querySelector('#account-form').hidden = data.signedIn;
    document.querySelector('#account-signed-in').hidden = !data.signedIn;
    document.querySelector('#account-migrate').hidden = !Object.values(accountCounts).some(Boolean);
    document.querySelector('#account-description').textContent = data.signedIn
      ? `ログイン中です。このブラウザに残る未移行データ：${describeCounts(accountCounts)}。`
      : `このブラウザの保存データ：${describeCounts(accountCounts)}。新規登録時に確認して移せます。別端末では同じユーザー名でログインしてください。`;
  } catch (error) { accountStatus.textContent = error.message; }
}
async function accountAction(action, body = {}) {
  try {
    const result = await api(`/api/account/${action}`, body);
    if (result.recoveryCode) {
      document.querySelector('#account-form').hidden = true;
      document.querySelector('#account-signed-in').hidden = true;
      document.querySelector('#account-recovery-result').hidden = false;
      document.querySelector('#account-new-recovery-code').textContent = result.recoveryCode;
      document.querySelector('.account-panel').open = true;
      accountStatus.textContent = '復旧コードを保存してから続けてください。';
    } else if (result.ok) window.location.reload();
  } catch (error) { accountStatus.textContent = error.message; }
}
document.querySelector('#account-form').addEventListener('submit', event => {
  event.preventDefault();
  accountAction('login', {
    username:document.querySelector('#account-username').value,
    password:document.querySelector('#account-password').value,
  });
});
document.querySelector('#account-register').addEventListener('click', () => {
  const migrateLocal = document.querySelector('#account-migrate-confirm').checked;
  if (Object.values(accountCounts).some(Boolean) && !migrateLocal) {
    accountStatus.textContent = 'このブラウザのデータ移行を確認してください。';
    return;
  }
  accountAction('register', {
    username:document.querySelector('#account-username').value,
    password:document.querySelector('#account-password').value,
    migrateLocal,
  });
});
document.querySelector('#account-logout').addEventListener('click', () => accountAction('logout'));
document.querySelector('#account-reissue').addEventListener('click', () => accountAction('reissue', {
  password:document.querySelector('#account-reissue-password').value,
}));
document.querySelector('#account-recovery-toggle').addEventListener('click', () => {
  document.querySelector('#account-recovery-fields').hidden = false;
  document.querySelector('#account-password').autocomplete = 'new-password';
  accountStatus.textContent = 'ユーザー名、保存した復旧コード、新しいパスワードを入力してください。';
});
document.querySelector('#account-recover').addEventListener('click', () => accountAction('recover', {
  username:document.querySelector('#account-username').value,
  password:document.querySelector('#account-password').value,
  recoveryCode:document.querySelector('#account-recovery-code').value,
}));
document.querySelector('#account-recovery-continue').addEventListener('click', () => window.location.reload());
document.querySelector('#account-migrate').addEventListener('click', () => {
  if (confirm(`${describeCounts(accountCounts)}をこのアカウントに移します。元のブラウザだけのデータは移行後に削除されます。続けますか？`)) {
    accountAction('migrate', {confirm:true});
  }
});
bootstrap();

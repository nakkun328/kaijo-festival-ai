# リク デスクトップ版（Unity）

Unity 6.3 LTS用のPCアプリです。既存のPythonサーバーを会話・音声・文字起こしのバックエンドとして使います。アバターの描画、再生、口パク、マイク入力をUnityが担当します。ブラウザ版は引き続き利用できます。

## 起動準備

1. Unity HubまたはUnity CLIで Unity 6000.3.13f1（Unity 6.3 LTS）をインストールし、Unityアカウントでサインインしてライセンスを有効化します。
2. この `unity/RikuDesktop` フォルダーをUnity Editorで開きます。初回はuLipSync 3.1.5を含むパッケージの取得が必要です。
3. プロジェクトを開くと `Assets/Scenes/Main.unity` が自動生成されます。自動生成されない場合はメニューの `Riku > Create Main Scene` を実行します。
4. 別のターミナルでプロジェクトルートから `\.venv\Scripts\python.exe exhibition_server.py` を起動し、OllamaとVOICEVOX Engineも起動します。
5. Unityで `Main` シーンを再生します。送信ボタンで文字会話、マイクボタンで録音開始・停止ができます。

Unity Editorの `Riku > Build Windows App` でWindows版を `Builds/Windows/RikuDesktop.exe` に出力できます。その後は、プロジェクトルートの `start-desktop-ai.ps1` で会話サーバーとアプリをまとめて起動できます。既にサーバーが起動している場合は、そのサーバーを利用します。

## 口パク

VOICEVOXのWAVをUnityの `AudioSource` で再生し、同じオブジェクトのuLipSyncが音声を分析します。アバターは既存のリクの開口・閉口差分を切り替えます。初回セットアップはuLipSync同梱の男性サンプルProfileを `Assets/Resources/RikuLipSyncProfile.asset` にコピーします。VOICEVOXの声に合わせて精度を上げるには、Unity EditorでこのProfileを再調整してください。Profileの取得に失敗した場合も、音量検出による口パクに切り替わります。

現在の素材は開口・閉口の2形態です。母音ごとに異なる口形まで表現するには、追加の差分素材が必要です。

## 制約

- 現在のPCにはUnity Editorを導入済みですが、Unityライセンスが未認証のためコンパイルとWindowsビルドは未検証です。
- 音声入力はマイクボタンをもう一度押して録音を終える方式です。自動発話区切りはブラウザ版に残っています。
- 初期API接続先は `http://127.0.0.1:8765` です。ローカルPCのみを想定します。

using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEditor.Build.Reporting;
using UnityEngine;

[InitializeOnLoad]
public static class RikuProjectSetup
{
    private const string ScenePath = "Assets/Scenes/Main.unity";
    private const string ProfilePath = "Assets/Resources/RikuLipSyncProfile.asset";

    static RikuProjectSetup()
    {
        EditorApplication.delayCall += EnsureProject;
    }

    [MenuItem("Riku/Create Main Scene")]
    public static void EnsureProject()
    {
        string sceneFile = Path.Combine(Application.dataPath, "Scenes", "Main.unity");
        if (!File.Exists(sceneFile))
        {
            Directory.CreateDirectory("Assets/Scenes");
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            EditorSceneManager.SaveScene(scene, ScenePath);
            Debug.Log("リクのMainシーンを作成しました。");
        }

        bool inBuild = false;
        foreach (var scene in EditorBuildSettings.scenes)
            if (scene.path == ScenePath) inBuild = true;
        if (!inBuild)
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };

        string profileFile = Path.Combine(Application.dataPath, "Resources", "RikuLipSyncProfile.asset");
        if (!File.Exists(profileFile))
        {
            string[] profiles = AssetDatabase.FindAssets("uLipSync-Profile-Sample-Male");
            foreach (string guid in profiles)
            {
                string source = AssetDatabase.GUIDToAssetPath(guid);
                if (AssetDatabase.CopyAsset(source, ProfilePath))
                {
                    AssetDatabase.SaveAssets();
                    Debug.Log("uLipSyncの男性サンプルProfileをコピーしました。VOICEVOXに合わせた再調整を推奨します。");
                    break;
                }
            }
        }
    }

    [MenuItem("Riku/Build Windows App")]
    public static void BuildWindows()
    {
        EnsureProject();
        string output = Path.Combine(Application.dataPath, "..", "Builds", "Windows", "RikuDesktop.exe");
        Directory.CreateDirectory(Path.GetDirectoryName(output));
        var options = new BuildPlayerOptions
        {
            scenes = new[] { ScenePath },
            locationPathName = output,
            target = BuildTarget.StandaloneWindows64,
            options = BuildOptions.None,
        };
        BuildReport report = BuildPipeline.BuildPlayer(options);
        if (report.summary.result != BuildResult.Succeeded)
            throw new System.Exception("RikuDesktop Windows build failed: " + report.summary.result);
        Debug.Log("RikuDesktop Windows build: " + output);
    }
}

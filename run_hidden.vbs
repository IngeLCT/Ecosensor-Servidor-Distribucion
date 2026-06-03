Option Explicit

Dim shell, fso, scriptDir, runBat
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
runBat = fso.BuildPath(scriptDir, "run.bat")

If Not fso.FileExists(runBat) Then
    MsgBox "No se encontro run.bat en: " & scriptDir, vbCritical, "EcoSensor Servidor"
    WScript.Quit 1
End If

shell.CurrentDirectory = scriptDir
shell.Run Chr(34) & runBat & Chr(34), 0, False

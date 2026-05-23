Set shell = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
If Not fso.FileExists(folder & "\Clickless.exe") Then
    MsgBox "找不到 Clickless.exe" & vbCrLf & "请解压完整的 Clickless 文件夹。", vbCritical, "Clickless"
    WScript.Quit 1
End If
If Not fso.FolderExists(folder & "\_internal") Then
    MsgBox "找不到 _internal 文件夹" & vbCrLf & "exe 和 _internal 必须在一起。", vbCritical, "Clickless"
    WScript.Quit 1
End If
shell.Run """" & folder & "\Clickless.exe""", 1, False

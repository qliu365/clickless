Set shell = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
If Not fso.FileExists(folder & "\OfficeLego.exe") Then
    MsgBox "找不到 OfficeLego.exe" & vbCrLf & "请解压完整的 OfficeLego 文件夹。", vbCritical, "OfficeLego"
    WScript.Quit 1
End If
If Not fso.FolderExists(folder & "\_internal") Then
    MsgBox "找不到 _internal 文件夹" & vbCrLf & "exe 和 _internal 必须在一起。", vbCritical, "OfficeLego"
    WScript.Quit 1
End If
shell.Run """" & folder & "\OfficeLego.exe""", 1, False

Option Explicit

Dim shell, fso, root, pythonw, mode, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(pythonw) Then
    MsgBox "Jarvis is not installed yet. Run install.bat first.", vbExclamation, "Jarvis"
    WScript.Quit 1
End If

mode = "--show"
If WScript.Arguments.Count > 0 Then
    If LCase(WScript.Arguments(0)) = "--background" Then mode = "--background"
End If

shell.CurrentDirectory = root
command = """" & pythonw & """ """ & root & "\jarvis_workplace_server.py"" " & mode
shell.Run command, 0, False

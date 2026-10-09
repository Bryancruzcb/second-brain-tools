' Runs start-night-atlas.ps1 with no visible console window, passing through
' any arguments. The Startup-folder shortcut and the optional logon task made
' by install-autostart.ps1 both point here (same pattern as
' scripts/run_hidden.vbs for the nightly archive). Does not wait: the
' launcher logs to %LOCALAPPDATA%\NightAtlas\logs\autostart.log.
Dim shell, scriptDir, cmd, i, a
Set shell = CreateObject("WScript.Shell")
scriptDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & scriptDir & "start-night-atlas.ps1"""
For i = 0 To WScript.Arguments.Count - 1
    a = WScript.Arguments(i)
    If InStr(a, " ") > 0 Then a = """" & a & """"
    cmd = cmd & " " & a
Next
shell.Run cmd, 0, False

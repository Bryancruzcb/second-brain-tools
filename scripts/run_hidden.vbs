' Launches run_auto_archive.cmd with no visible console window.
' Task Scheduler runs this via wscript.exe so the nightly pipeline never
' pops a console (and can't be killed by someone closing that window).
' Waits for the pipeline and propagates its exit code to Task Scheduler.
Dim shell, scriptDir, exitCode
Set shell = CreateObject("WScript.Shell")
scriptDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
exitCode = shell.Run("""" & scriptDir & "run_auto_archive.cmd""", 0, True)
WScript.Quit exitCode

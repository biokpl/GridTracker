Set oShell = CreateObject("WScript.Shell")
oShell.Run "pythonw """ & Replace(WScript.ScriptFullName, "start_server.vbs", "server.py") & """", 0, False

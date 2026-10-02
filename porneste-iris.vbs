' Pornește Iris fără consolă. `pythonw.exe`, nu `python.exe`: altfel rămâne
' o fereastră neagră deschisă cât ține programul.
'
' Calea către venv e explicită, nu `py`: mediul ăsta e propriu, tocmai ca un
' `pip install` de aici să nu poată atinge Python-ul global — și ca o actualizare
' făcută în cel global să nu poată schimba ce vede Iris.
'
' Folderul e cel în care stă scriptul, oriunde ar fi clonat depozitul.
Set ws = CreateObject("WScript.Shell")
acasa = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = acasa
ws.Run """" & acasa & "\.venv\Scripts\pythonw.exe"" iris.py", 0

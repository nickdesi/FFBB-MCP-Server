@echo off
chcp 65001 > nul
cls
echo 🏀 Lancement de l'installateur FFBB MCP pour Windows...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "iwr -useb https://ffbb.desimone.fr/install.ps1 | iex"
echo.
pause

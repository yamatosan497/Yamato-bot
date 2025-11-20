# Yamato Bot - Replit + UptimeRobot ready

Contenido:
- bot.py (tu código original, sin cambios)
- main.py (inicia keep_alive y luego ejecuta bot.py)
- keep_alive.py (servidor Flask para que UptimeRobot haga pings)
- requirements.txt
- .env.example
- Procfile (opcional)

Instrucciones rápidas:
1. Sube este repo a Replit (Import from GitHub).
2. En Secrets / Environment, añade las variables:
   TELEGRAM_BOT_TOKEN, API_ID, API_HASH, STORAGE_CHAT_ID
3. Ejecuta el Repl (Run). Copia la URL pública.
4. En UptimeRobot crea un monitor HTTP(s) apuntando a la URL del Repl (interval 5 min).

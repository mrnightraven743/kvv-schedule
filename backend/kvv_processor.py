import requests
import json
import os
from datetime import datetime, timedelta

# --- НАСТРОЙКИ ---
STOP_ID = "7001862"  # Bad Schönborn Süd
BASE_URL = "http://www.kvv.de/tunnelEfaDirect.php"

REPLACEMENTS = {
    "Hauptbahnhof": "Hbf",
    "Bahnhof": "Bhf",
    "Straße": "Str.",
    "Platz": "Pl.",
}

def shorten_text(text):
    for full, short in REPLACEMENTS.items():
        text = text.replace(full, short)
    if len(text) > 22: text = text[:22] + "."
    return text

def main():
    print("🚀 Running KVV Update Action...")
    
    # Берем "завтра", чтобы получить полные сутки с 00:00
    tomorrow = datetime.now() + timedelta(days=1)
    
    date_params = {
        "itdDateYear": tomorrow.year,
        "itdDateMonth": tomorrow.month,
        "itdDateDay": tomorrow.day
    }
    
    final_schedule = {}

    # Проходим по часам 0-23
    for hour in range(24):
        print(f"Processing {hour:02d}:00...")
        params = {
            "action": "XSLT_DM_REQUEST",
            "outputFormat": "JSON",
            "mode": "direct",
            "type_dm": "any",
            "useRealtime": "0",
            "limit": "100", # Берем с запасом!
            "name_dm": STOP_ID,
            "time": f"{hour:02d}:00",
            **date_params
        }

        try:
            resp = requests.get(BASE_URL, params=params, timeout=30)
            data = resp.json()
            raw_list = data.get('departureList', [])
            deps_for_hour = []
            
            for dep in raw_list:
                dt = dep.get('dateTime', {})
                h = int(dt.get('hour', -1))
                
                # Строгий фильтр по часу
                if h != hour: continue
                
                # Фильтр S-Bahn
                line = dep.get('servingLine', {}).get('symbol', '?')
                if not line.startswith('S'): continue
                
                m = int(dt.get('minute', 0))
                direction = dep.get('servingLine', {}).get('direction', 'Unknown')
                if '>' in direction: direction = direction.split('>')[0].strip()
                
                entry = (m, line, shorten_text(direction))
                if entry not in deps_for_hour:
                    deps_for_hour.append(entry)
            
            deps_for_hour.sort(key=lambda x: x[0])
            final_schedule[hour] = deps_for_hour

        except Exception as e:
            print(f"Error on hour {hour}: {e}")
            final_schedule[hour] = []

    # Записываем файл offline_data.py
    with open("offline_data.py", "w", encoding="utf-8") as f:
        f.write(f"# Auto-generated via GitHub Actions: {datetime.now()}\n")
        f.write("SCHEDULE = {\n")
        for h in range(24):
            f.write(f"    {h}: {str(final_schedule[h])},\n")
        f.write("}\n")
    
    print("✅ Done. offline_data.py updated.")

if __name__ == "__main__":
    main()
